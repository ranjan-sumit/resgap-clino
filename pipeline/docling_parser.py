"""
Stage 1 (Clinova Phase 1, Epic 1.1): structural second-parser extraction.

Second, independent parser alongside pipeline/pdf_parser.py's pdfplumber
extraction -- feeds pipeline/extraction_reconciler.py's multi-parser
reconciliation (05-data-architecture.md §2-3).

History: this module used to wrap Docling, which dragged in torch + CUDA +
triton + opencv + transformers (~5.8GB installed, ~1.1GB RSS, ~86s/paper) and
could not run on Streamlit Cloud. It now uses PyMuPDF, which is already a
hard dependency: font-size/bold statistics give section headers, repeated
margin text gives page headers/footers, and Page.find_tables() gives tables.
No model weights, no GPU, ~0.1s/paper.

The public names (`extract_with_docling`, `DOCLING_STAGE_VERSION`, the
"docling" source label, the docling_extractions cache table) are kept as-is
so the reconciler, evidence extractor, lineage and DB schema need no change;
"docling" is now only a legacy label for "the structural parser".
"""
import hashlib
import re
from collections import Counter
from pathlib import Path

from utils.database import get_cached_docling_extraction, save_cached_docling_extraction
from pipeline.pdf_parser import _detect_section
from utils.text_hygiene import strip_invisible, visible_span

try:
    import pymupdf
except ImportError:  # PyMuPDF < 1.24.3 only exposes the legacy module name
    import fitz as pymupdf

# Bumped 2 -> 3 on the Docling -> PyMuPDF swap: a v2 cache row holds Docling
# output (different segmentation and labels) and must not be served as if the
# new engine produced it (AD-3's stage_logic_version convention).
DOCLING_STAGE_VERSION = 5     # 5: hidden text left out, invisible characters removed (4: furniture anywhere; tables as segments)

_MARGIN_FRACTION = 0.08        # top/bottom band scanned for running headers/footers
_REPEAT_FRACTION = 0.5         # margin text on >= this share of pages is a running header/footer
_HEADING_SIZE_RATIO = 1.15     # heading font must exceed body font by this factor
_HEADING_MAX_CHARS = 120
_BOLD_HEADING_MAX_CHARS = 80
_BOLD_FLAG = 16                # PyMuPDF span flag bit for bold
_NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s+[A-Z]")
_NUMBERED_HEADING_MAX_CHARS = 100
_MIN_RULING_LINES = 4          # a ruled table needs at least this many vector segments


def _content_hash(pdf_path: str) -> str:
    return hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()


def _norm_margin(text: str) -> str:
    return re.sub(r"\d+", "#", " ".join(text.lower().split()))


def _read_blocks(doc, stats: dict | None = None) -> list[dict]:
    """Flatten every text block of every page into
    {page, text, size, bold, y0, y1, page_h, bbox}. Text a reader cannot see (microscopic, or white and
    instruction-like) is left out and invisible characters are removed; both are counted in `stats`."""
    stats = stats if stats is not None else {}
    blocks = []
    for pno, page in enumerate(doc, 1):
        page_h = page.rect.height
        for b in page.get_text("dict").get("blocks", []):
            if b.get("type") != 0:
                continue
            line_texts, chars, size_sum, bold_chars = [], 0, 0.0, 0
            for line in b.get("lines", []):
                parts = []
                for span in line.get("spans", []):
                    t = span.get("text", "")
                    if not t.strip():
                        continue
                    if not visible_span(span):
                        stats["hidden_chars"] = stats.get("hidden_chars", 0) + len(t)
                        continue
                    t, removed = strip_invisible(t)
                    stats["invisible_removed"] = stats.get("invisible_removed", 0) + removed
                    if not t.strip():
                        continue
                    parts.append(t)
                    n = len(t)
                    chars += n
                    size_sum += span.get("size", 0.0) * n
                    is_bold = bool(span.get("flags", 0) & _BOLD_FLAG) or "bold" in span.get("font", "").lower()
                    bold_chars += n if is_bold else 0
                joined = " ".join(" ".join(parts).split())
                if joined:
                    line_texts.append(joined)
            if not line_texts or chars == 0:
                continue
            x0, y0, x1, y1 = b["bbox"]
            blocks.append({
                "page": pno,
                "text": " ".join(line_texts).strip(),
                "n_lines": len(line_texts),
                "size": size_sum / chars,
                "bold": bold_chars / chars > 0.6,
                "chars": chars,
                "bbox": (x0, y0, x1, y1),
                "page_h": page_h,
            })
    return blocks


def _body_font_size(blocks: list[dict]) -> float:
    """Character-weighted modal font size (rounded to 0.5pt) = body text."""
    weight: Counter = Counter()
    for b in blocks:
        weight[round(b["size"] * 2) / 2] += b["chars"]
    return weight.most_common(1)[0][0] if weight else 0.0


def _margin_labels(blocks: list[dict], n_pages: int) -> dict[int, str]:
    """id(block) -> page_header | page_footer | page_number for margin blocks."""
    candidates = []
    for b in blocks:
        _, y0, _, y1 = b["bbox"]
        h = b["page_h"]
        if y1 <= h * _MARGIN_FRACTION:
            candidates.append((b, "page_header"))
        elif y0 >= h * (1 - _MARGIN_FRACTION):
            candidates.append((b, "page_footer"))

    seen_on_pages: dict[str, set] = {}
    for b, _ in candidates:
        seen_on_pages.setdefault(_norm_margin(b["text"]), set()).add(b["page"])

    labels = {}
    for b, kind in candidates:
        if re.fullmatch(r"\s*(page\s+)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*", b["text"], re.I):
            labels[id(b)] = "page_number"
        elif n_pages >= 3 and len(seen_on_pages[_norm_margin(b["text"])]) >= max(2, _REPEAT_FRACTION * n_pages):
            labels[id(b)] = kind
    return labels


def _exact_key(text: str) -> str:
    """Whitespace- and case-folded text WITHOUT masking digits: "2. Results" and "3. Results" are
    different headings, whereas a margin running header ("... 2021;12:34") has its own rule."""
    return " ".join(text.lower().split())


_FURNITURE_MAX_CHARS = 90
_FURNITURE_PAGE_FRACTION = 0.3


def _repeated_furniture(blocks: list[dict], n_pages: int, already: dict) -> dict[int, str]:
    """id(block) -> page_header | page_footer for short blocks whose text repeats on many pages
    wherever they sit (a journal name set in a bold banner below the margin band is still a
    running header). Real section headings are never repeated page after page, and a heading
    keyword ("Methods", "Results") is never treated as furniture."""
    if n_pages < 3:
        return {}
    pages_of: dict[str, set] = {}
    for b in blocks:
        if id(b) in already or len(b["text"]) > _FURNITURE_MAX_CHARS or b["n_lines"] > 2:
            continue
        pages_of.setdefault(_exact_key(b["text"]), set()).add(b["page"])
    need = max(3, _FURNITURE_PAGE_FRACTION * n_pages)
    out = {}
    for b in blocks:
        if id(b) in already or len(b["text"]) > _FURNITURE_MAX_CHARS or b["n_lines"] > 2:
            continue
        if len(pages_of.get(_exact_key(b["text"]), ())) >= need and not _detect_section(b["text"]):
            out[id(b)] = "page_header" if b["bbox"][1] < b["page_h"] / 2 else "page_footer"
    return out


def _is_heading(b: dict, body_size: float) -> bool:
    text = b["text"]
    if len(text) < 2 or b["n_lines"] > 2 or not re.search(r"[A-Za-z]", text):
        return False
    if _detect_section(text):
        return True
    # "2.1. Study Design" -- numbered headings are often body-size and
    # regular-weight (e.g. MDPI), so numbering is the only reliable signal.
    # Short, <=2 lines and no sentence-ending punctuation keeps list items
    # and reference entries ("1. European Cystic Fibrosis Society. ...") out.
    if (_NUMBERED_HEADING_RE.match(text) and len(text) <= _NUMBERED_HEADING_MAX_CHARS
            and not text.endswith((".", ",", ";", ":"))):
        return True
    if len(text) > _HEADING_MAX_CHARS:
        return False
    if body_size and b["size"] >= body_size * _HEADING_SIZE_RATIO:
        return True
    return b["bold"] and len(text) <= _BOLD_HEADING_MAX_CHARS and not text.endswith((".", ","))


def _inside(bbox, outer) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def _extract_tables(doc) -> tuple[list[dict], dict[int, list]]:
    """Returns (tables, {page_no: [bbox, ...]}) -- bboxes let the caller keep
    table cell text out of the prose segments."""
    tables, boxes = [], {}
    for pno, page in enumerate(doc, 1):
        try:
            # find_tables() is the slow call (~0.4s/page); its default strategy
            # needs ruling lines, so a page with no vector drawings cannot
            # yield a table -- skip it.
            if len(page.get_drawings()) < _MIN_RULING_LINES:
                continue
            found = page.find_tables().tables
        except Exception:
            continue
        for t in found:
            try:
                rows = [[(c or "").replace("\n", " ").strip() for c in row] for row in t.extract()]
            except Exception:
                continue
            if len(rows) < 2:
                continue
            cols = max(len(r) for r in rows)
            tables.append({
                "page": pno,
                "content": "\n".join("|".join(r) for r in rows),
                "rows": len(rows),
                "cols": cols,
                "index": len(tables),
            })
            boxes.setdefault(pno, []).append(tuple(t.bbox))
    return tables, boxes


def extract_with_docling(pdf_path: str, filename: str) -> dict:
    """
    Run (or fetch cached) structural extraction for one PDF.

    Returns:
        {
          "filename": str,
          "source": "docling",     # legacy label, see module docstring
          "full_text": str,        # markdown-ish export (## headings)
          "char_count": int,
          "tables": [{"page": int|None, "content": str, "rows": int, "cols": int}],
          "text_segments": [{"text": str, "page": int|None, "label": str}],
            # Real per-block page numbers read from the PDF itself -- not
            # inferred. `label` is one of "text", "section_header",
            # "page_header", "page_footer", "page_number"; pipeline/
            # evidence_extractor.py filters the last three out of provenance.
          "from_cache": bool,
        }
    """
    content_hash = _content_hash(pdf_path)
    cache_key = f"{content_hash}:none:{DOCLING_STAGE_VERSION}"

    cached = get_cached_docling_extraction(cache_key)
    if cached is not None:
        result = dict(cached)
        result["from_cache"] = True
        return result

    with pymupdf.open(pdf_path) as doc:
        hygiene = {}
        blocks = _read_blocks(doc, hygiene)
        tables, table_boxes = _extract_tables(doc)
        n_pages = len(doc)

    body_size = _body_font_size(blocks)
    margin = _margin_labels(blocks, n_pages)
    margin.update(_repeated_furniture(blocks, n_pages, margin))

    text_segments, md_parts = [], []
    for b in blocks:
        if any(_inside(b["bbox"], tb) for tb in table_boxes.get(b["page"], [])):
            continue
        label = margin.get(id(b)) or ("section_header" if _is_heading(b, body_size) else "text")
        text_segments.append({"text": b["text"], "page": b["page"], "label": label})
        if label == "section_header":
            md_parts.append(f"## {b['text']}")
        elif label == "text":
            md_parts.append(b["text"])
    for t in tables:
        md_parts.append(f"[Table, page {t['page']}]\n{t['content']}")
        # The table is also a segment of its own, so what a reader quotes from it can be found again.
        seg = {"text": f"Table (page {t['page']}):\n{t['content']}", "page": t["page"], "label": "table"}
        at = max((i + 1 for i, x in enumerate(text_segments) if (x.get("page") or 0) <= t["page"]), default=len(text_segments))
        text_segments.insert(at, seg)
    full_text = "\n\n".join(md_parts)

    result = {
        "filename": filename,
        "source": "docling",
        "full_text": full_text,
        "char_count": len(full_text),
        "tables": tables,
        "text_segments": text_segments,
        "hygiene": {"hidden_chars": hygiene.get("hidden_chars", 0),
                    "invisible_removed": hygiene.get("invisible_removed", 0)},
        "from_cache": False,
    }

    try:
        save_cached_docling_extraction(cache_key, content_hash, DOCLING_STAGE_VERSION, result)
    except Exception:
        # A cache-write failure must not discard the extraction that was just
        # produced -- mirrors pipeline/reference_extractor.py's save guard:
        # swallow, and still return the real extraction.
        pass
    return result
