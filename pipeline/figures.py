"""Figures: find them, show them to a vision model, and say how far the answer can be trusted.

The old approach looked at pages with few words, or a figure word and fewer than 200 words, and sent the first five whole.
On real papers it picked no page at all for two of three papers (figures sit on pages full of text) and picked reference
pages for the third. This module finds figures from what the PDF contains: a caption line ("Figure 3.", "Fig. 3:") with a
picture or a drawing beside it. Only that region is rendered and sent, with its caption, and the answer is checked: numbers
the model reports that appear nowhere in the caption or the page text are listed, because they are readings of the plot
(or invented) rather than quotations.
"""
from __future__ import annotations

import re
import time

try:
    import pymupdf
except ImportError:                       # PyMuPDF < 1.24.3 only exposes the legacy module name
    import fitz as pymupdf

from utils.azure_client import unwrap

FIGURES_STAGE_VERSION = 2
MAX_FIGURES = 8
# "Figure 3." / "Fig. 3:" / "Fig. 3 | Title" -- or "Figure 3 Title" when a capitalised word follows; a sentence that merely
# starts with "Figure 3 shows ..." is not a caption
_CAPTION_RE = re.compile(r"^\s*(Fig(?:ure)?\.?)\s*(S?\d+[A-Za-z]?)(?:\s*[.:|\-–—]\s|\s+(?=[A-Z][a-z]))", re.IGNORECASE)
_SENTENCE_VERB = re.compile(r"^\s*(?:shows?|illustrates?|depicts?|presents?|displays?|summari[sz]es?|compares?|is|are|was|were|and)\b",
                            re.IGNORECASE)
_MIN_IMAGE_SHARE = 0.03               # an embedded picture smaller than this share of the page is a logo or an icon
_MIN_DRAWINGS = 25                    # a chart drawn as vectors has many paths; a rule or a box has a few
_REACH = 380                          # points: how far from its caption a picture may sit and still be its figure
_PAD = 8
_VISION_BUDGET_SECONDS = 150
_MAX_VISION_FAILURES_IN_A_ROW = 2

SYSTEM_PROMPT = (
    "You read ONE figure from a research paper, given as an image with its caption. Describe only what is visible in the "
    "image and stated in the caption: what is plotted or shown, the axes and units, the groups compared, and the trend or "
    "difference. Quote a value only if you can read it; say 'about' for anything estimated from the position of a bar, "
    "point or line. Do not add background knowledge, do not interpret beyond what the figure shows, and do not describe "
    "page layout, logos or the surrounding text. Plain text only: no LaTeX, no markdown. Be concise: at most 120 words."
)


def _page_blocks(page) -> list:
    return [b for b in page.get_text("blocks") if b[6] == 0 and (b[4] or "").strip()]


def _visuals(page) -> list:
    """Bounding boxes of pictures and charts on the page: embedded images that are not logos, and dense clusters of
    vector drawings."""
    area = page.rect.width * page.rect.height
    boxes = []
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"])
        if r.get_area() >= _MIN_IMAGE_SHARE * area:
            boxes.append((r, "raster"))
    drawings = [d["rect"] for d in page.get_drawings() if d.get("rect") is not None]
    if len(drawings) >= _MIN_DRAWINGS:
        # one box around the drawings, split by large vertical gaps so two charts are two boxes
        drawings.sort(key=lambda r: r.y0)
        cluster = [drawings[0]]
        groups = []
        for r in drawings[1:]:
            if r.y0 - max(c.y1 for c in cluster) > 60:
                groups.append(cluster)
                cluster = [r]
            else:
                cluster.append(r)
        groups.append(cluster)
        for g in groups:
            if len(g) >= _MIN_DRAWINGS // 2:
                box = pymupdf.Rect(min(c.x0 for c in g), min(c.y0 for c in g), max(c.x1 for c in g), max(c.y1 for c in g))
                if box.get_area() >= 0.02 * area:
                    boxes.append((box, "vector"))
    return boxes


def find_figures(pdf_path: str, max_figures: int = MAX_FIGURES) -> list[dict]:
    """[{"label": "Figure 3", "page": 5, "caption": "...", "bbox": (x0, y0, x1, y1), "kind": "raster|vector"}] in
    reading order. A caption with no picture or chart near it (a table title, a reference to a figure) is not a figure."""
    found = []
    with pymupdf.open(pdf_path) as doc:
        for pno, page in enumerate(doc, 1):
            visuals = _visuals(page)
            if not visuals:
                continue
            for b in _page_blocks(page):
                m = _CAPTION_RE.match(b[4])
                if not m or _SENTENCE_VERB.match(b[4][m.end():]):
                    continue
                cap = pymupdf.Rect(b[:4])
                near = [(r, k) for r, k in visuals if abs(r.y1 - cap.y0) <= _REACH or abs(cap.y1 - r.y0) <= _REACH]
                # the nearest picture above the caption, else below it (some journals put the caption above)
                above = [(r, k) for r, k in near if r.y1 <= cap.y0 + 4]
                below = [(r, k) for r, k in near if r.y0 >= cap.y1 - 4]
                pick = max(above, key=lambda rk: rk[0].y1) if above else (min(below, key=lambda rk: rk[0].y0) if below else None)
                if pick is None:
                    continue
                rect, kind = pick
                region = pymupdf.Rect(rect)
                region.include_rect(cap)
                region = (region + (-_PAD, -_PAD, _PAD, _PAD)) & page.rect
                label = f"Figure {m.group(2)}"
                if any(f["label"] == label and f["page"] == pno for f in found):
                    continue
                found.append({"label": label, "page": pno, "caption": " ".join(b[4].split())[:600],
                              "bbox": tuple(round(v, 1) for v in region), "kind": kind})
    return found[:max_figures]


def render_figure(pdf_path: str, figure: dict, dpi: int = 150) -> bytes:
    with pymupdf.open(pdf_path) as doc:
        page = doc[figure["page"] - 1]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), clip=pymupdf.Rect(figure["bbox"]))
        return pix.tobytes("png")


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def plain_text(text: str) -> str:
    """The model's answer as plain text: markdown emphasis and LaTeX fragments ("$7\\ \\mu\\text{m}$") turned into what they say."""
    t = str(text or "")
    t = re.sub(r"\*\*|__", "", t)
    t = re.sub(r"\$([^$]*)\$", lambda m: m.group(1), t)
    for tex, ch in ((r"\mu", "µ"), (r"\beta", "β"), (r"\alpha", "α"), (r"\gamma", "γ"), (r"\pm", "±"), (r"\times", "×"),
                    (r"\approx", "≈"), (r"\%", "%")):
        t = t.replace(tex, ch)
    t = re.sub(r"\\text\{([^}]*)\}|\\mathrm\{([^}]*)\}", lambda m: m.group(1) or m.group(2), t)
    t = t.replace("\\ ", " ").replace("\\,", " ")
    return " ".join(t.split())


def mark_unsupported(description: str, numbers: list[str]) -> str:
    """The description with each number that is not in the paper's text marked `*`, and a line saying what the mark means."""
    if not numbers:
        return description
    marked = description
    for n in sorted(set(numbers), key=len, reverse=True):
        marked = re.sub(rf"(?<![\d.]){re.escape(n)}(?![\d.]|\*)", f"{n}*", marked)
    return marked + " (* read from the image; not stated in the text)"


def numbers_not_in_text(description: str, *sources: str) -> list[str]:
    """Multi-digit numbers in the description that appear in none of the sources (the caption and the page's text).
    They are readings taken from the plot, or inventions; either way they are not quotations."""
    have = {n.replace(",", ".") for s in sources for n in _NUM.findall(s or "")}
    out = []
    for n in _NUM.findall(description or ""):
        norm = n.replace(",", ".")
        if len(norm.replace(".", "")) >= 2 and norm not in have and n not in out:
            out.append(n)
    return out


def analyze_figures(pdf_path: str, client, figures: list[dict], on_progress=None) -> list[dict]:
    """One vision call per figure. Each result: label, page, caption, kind, description ('' when the call failed),
    error (None when it worked), numbers_not_in_text. Never raises; stops after two failures in a row or when the time
    budget is used up (the remaining figures get an error, not a made-up description)."""
    out, started, failures = [], time.monotonic(), 0
    with pymupdf.open(pdf_path) as doc:
        page_text = {f["page"]: doc[f["page"] - 1].get_text() for f in figures}
    for n, fig in enumerate(figures, 1):
        base = {"label": fig["label"], "page": fig["page"], "caption": fig["caption"], "kind": fig["kind"],
                "description": "", "error": None, "numbers_not_in_text": []}
        if failures >= _MAX_VISION_FAILURES_IN_A_ROW or time.monotonic() - started > _VISION_BUDGET_SECONDS:
            out.append({**base, "error": "skipped: figure analysis was failing or taking too long"})
            continue
        if on_progress:
            on_progress(f"{fig['label']} ({n}/{len(figures)})")
        try:
            image = render_figure(pdf_path, fig)
            desc = unwrap(client.vision(system=SYSTEM_PROMPT,
                                        user_text=f"Caption: {fig['caption']}\n\nDescribe this figure.",
                                        image_bytes=image))
            desc = plain_text(desc)
            if not desc:
                raise ValueError("empty answer")
            out.append({**base, "description": desc,
                        "numbers_not_in_text": numbers_not_in_text(desc, fig["caption"], page_text.get(fig["page"], ""))})
            failures = 0
        except Exception as e:
            failures += 1
            out.append({**base, "error": f"{type(e).__name__}: {e}"[:200]})
    return out
