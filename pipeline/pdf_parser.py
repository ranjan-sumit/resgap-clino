"""
Stage 1: Multimodal PDF Parser
Extracts text by section, tables, and optionally figures via GPT-4o Vision.
"""
import io
import re
import pdfplumber
from utils.azure_client import unwrap

# PyMuPDF — needed for page-to-image conversion (vision analysis).
# If import fails, vision features are disabled but text/table extraction still works.
# Fix: pip uninstall fitz frontend PyMuPDF -y && pip install PyMuPDF
try:
    import fitz
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False

# Section headers commonly found in research papers
SECTION_PATTERNS = [
    r"abstract",
    r"introduction",
    r"related work",
    r"background",
    r"literature review",
    r"methodology|method|approach|proposed",
    r"experiment|evaluation|results",
    r"discussion",
    r"limitation",
    r"conclusion|future work|summary",
    r"references|bibliography",
]

# A line is a section header only if it IS the keyword (case-insensitive),
# optionally plural ("Methods"), preceded by numbering ("3. Methods") and/or
# followed by punctuation or a trailing number ("REFERENCES:", "Methods 3").
# A body sentence that merely contains a keyword ("We took an approach
# based on...") must not be treated as a header.
_SECTION_HEADER_RE = re.compile(
    r"^(?:[0-9]+(?:\.[0-9]+)*\.?\s+|[IVXLCDM]+\.?\s+)?"
    r"(?:" + "|".join(f"(?:{p})s?" for p in SECTION_PATTERNS) + r")"
    r"[.:]?(?:\s+[0-9]+)?\s*$",
    re.IGNORECASE,
)


def _detect_section(text: str) -> str | None:
    """Return a normalized section name if the line looks like a section header."""
    clean = text.strip()
    if len(clean) > 80 or len(clean) < 2:
        return None
    if _SECTION_HEADER_RE.match(clean):
        return clean
    return None


def _extract_text_by_section(pdf_path: str) -> dict:
    """
    Use pdfplumber to extract text, grouping content by detected section headers.
    Returns dict: {section_name: text_content}
    """
    sections = {"_header": ""}
    current_section = "_header"
    full_text = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            for line in page_text.split("\n"):
                sec = _detect_section(line)
                if sec:
                    current_section = sec
                    if current_section not in sections:
                        sections[current_section] = ""
                else:
                    sections[current_section] = sections.get(current_section, "") + line + "\n"
                full_text.append(line)

    return {
        "sections": sections,
        "full_text": "\n".join(full_text),
        "char_count": len("\n".join(full_text)),
    }


_REFERENCE_HEADINGS = frozenset({"references", "bibliography", "literature cited", "reference list"})
_VISION_BUDGET_SECONDS = 150
_MAX_VISION_FAILURES_IN_A_ROW = 2
_NON_BODY_LABELS = frozenset({"page_header", "page_footer", "page_number"})
_MIN_STRUCTURAL_SECTIONS = 3


def _structural_segments(pdf_path: str, filename: str) -> list:
    """The page-tagged text blocks from the structural parser ([] when it cannot
    run). They carry real page numbers and heading labels, which is what lets
    evidence be traced to a page and section."""
    try:
        from pipeline.docling_parser import extract_with_docling  # lazy: it imports this module
        return list(extract_with_docling(pdf_path, filename).get("text_segments", []))
    except Exception:
        return []


def _sections_from_structure(pdf_path: str, filename: str) -> dict | None:
    """Split the paper at the headings the structural parser found (bold or
    larger numbered lines), so "2. CFTR expression" becomes a section even
    though it is not one of the fixed keywords. Returns None when the parser
    cannot be used or finds too few headings to be trustworthy."""
    return _sections_from_segments(_structural_segments(pdf_path, filename))


def _sections_from_segments(segments: list) -> dict | None:
    if not segments:
        return None
    sections: dict = {"_header": ""}
    current = "_header"
    for seg in segments:
        label, text = seg.get("label"), (seg.get("text") or "").strip()
        if not text or label in _NON_BODY_LABELS:
            continue
        if label == "section_header" and len(text) <= 80:
            name, n = text, 2
            while name in sections and name != current:
                name, n = f"{text} ({n})", n + 1
            current = name
            sections.setdefault(current, "")
        else:
            sections[current] += text + "\n"
    if sum(1 for k, v in sections.items() if k != "_header" and v.strip()) < _MIN_STRUCTURAL_SECTIONS:
        return None
    return sections


def _extract_tables(pdf_path: str) -> list:
    """Extract tables from PDF using pdfplumber."""
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            page_tables = page.extract_tables()
            for tbl in page_tables:
                if tbl and len(tbl) > 1:
                    # Convert to readable markdown-style string
                    rows = []
                    for row in tbl:
                        cleaned = [str(cell).strip() if cell else "" for cell in row]
                        rows.append(" | ".join(cleaned))
                    # pdfplumber reports figure frames and ruled boxes as tables with every
                    # cell empty; they are not tables and only show up as blank entries.
                    if not any(cell for row in tbl for cell in (str(c).strip() if c else "" for c in row)):
                        continue
                    tables.append({
                        "page": page_num,
                        "content": "\n".join(rows),
                        "rows": len(tbl),
                        "cols": len(tbl[0]) if tbl else 0,
                    })
    return tables


def _get_figure_pages(pdf_path: str) -> list:
    """
    Detect pages that are likely figure-heavy (low text density).
    Returns list of page indices (0-based).
    """
    figure_pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            # Heuristic: page has images but few words → figure page
            words = len(text.split())
            has_image_ref = bool(re.search(r"figure|fig\.|chart|graph|diagram", text.lower()))
            if words < 80 or (has_image_ref and words < 200):
                figure_pages.append(i)
    return figure_pages[:5]  # Cap at 5 pages to control API cost


def _page_to_image_bytes(pdf_path: str, page_index: int, dpi: int = 150) -> bytes:
    """Convert a PDF page to PNG image bytes using PyMuPDF."""
    if not FITZ_AVAILABLE:
        raise RuntimeError("PyMuPDF not available. Run: pip uninstall fitz frontend PyMuPDF -y && pip install PyMuPDF")
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")


def _analyze_figures_with_vision(pdf_path: str, client, figure_pages: list, on_progress=None) -> list:
    """
    Send figure-heavy pages to client.vision() (utils/azure_client.py's
    VISION_MODEL -- meta/llama-3.2-11b-vision-instruct on NVIDIA NIM as of
    B26, 2026-08-22) for analysis. Returns list of figure descriptions.

    B26 fix note: this docstring previously said "GPT-4o Vision" -- a
    leftover from a different provider/model that was never actually
    wired up here. The real model in use (gpt-oss-120b, before B26) had
    no confirmed image support at all and was silently returning "I can't
    see an image" as if it were a real description; nothing here would
    have caught that, since unwrap() only raises on a Failure, not on a
    Success carrying a wrong-but-well-formed answer. Fixed at the source
    (VISION_MODEL now points at a model that actually works), not by
    adding output-sniffing here.
    """
    import time
    descriptions = []
    system = (
        "You are a research paper analyst. Analyze this page from a research paper. "
        "Identify and describe any figures, charts, graphs, or result tables. "
        "Focus on: what is being shown, key values or trends, and any stated limitations or caveats."
    )
    started, failures_in_a_row = time.monotonic(), 0
    for n, page_idx in enumerate(figure_pages, 1):
        # Figure analysis is a bonus, never worth stalling the run: stop after
        # two failures in a row, or once this paper has used its time budget.
        if failures_in_a_row >= _MAX_VISION_FAILURES_IN_A_ROW or time.monotonic() - started > _VISION_BUDGET_SECONDS:
            descriptions.append({"page": page_idx + 1,
                                 "description": "[Skipped: figure analysis was failing or taking too long]"})
            continue
        if on_progress:
            on_progress(f"page {n}/{len(figure_pages)}")
        try:
            img_bytes = _page_to_image_bytes(pdf_path, page_idx)
            desc = unwrap(client.vision(
                system=system,
                user_text="Describe the figures and tables on this page in detail.",
                image_bytes=img_bytes,
            ))
            descriptions.append({"page": page_idx + 1, "description": desc})
            failures_in_a_row = 0
        except Exception as e:
            failures_in_a_row += 1
            descriptions.append({"page": page_idx + 1, "description": f"[Vision analysis failed: {e}]"})
    return descriptions


def parse_pdf(pdf_path: str, filename: str, client=None, use_vision: bool = False,
              on_progress=None) -> dict:
    """
    Full PDF parsing pipeline for one paper.
    Returns structured content dict.
    """
    result = {
        "filename": filename,
        "sections": {},
        "full_text": "",
        "tables": [],
        "figures": [],
        "char_count": 0,
    }

    # Text extraction
    text_data = _extract_text_by_section(pdf_path)
    result["sections"] = text_data["sections"]
    # The keyword splitter only recognises headings like "Results"; papers with
    # topic headings end up as one huge "_header" blob. Prefer the structural split.
    legacy_named = sum(1 for k, v in result["sections"].items() if k != "_header" and v.strip())
    segments = _structural_segments(pdf_path, filename)
    result["text_segments"] = segments          # page-tagged blocks: the evidence reader's input
    structural = _sections_from_segments(segments)
    if structural is not None and (
        legacy_named < _MIN_STRUCTURAL_SECTIONS
        or len(result["sections"].get("_header", "")) > 0.5 * max(1, text_data["char_count"])
    ):
        result["sections"] = structural
    result["full_text"] = text_data["full_text"]
    result["char_count"] = text_data["char_count"]

    # Table extraction
    result["tables"] = _extract_tables(pdf_path)

    # Vision-based figure extraction (optional, requires PyMuPDF)
    if use_vision and client and FITZ_AVAILABLE:
        figure_pages = _get_figure_pages(pdf_path)
        if figure_pages:
            result["figures"] = _analyze_figures_with_vision(pdf_path, client, figure_pages, on_progress)

    return result


def get_smart_excerpt(paper: dict, max_chars: int = 12000) -> str:
    """
    Build a smart excerpt from the paper that prioritizes
    Limitations, Future Work, Results, and Abstract for gap analysis.
    """
    priority_keywords = [
        "limitation", "future work", "conclusion", "discussion",
        "abstract", "result", "experiment", "finding"
    ]
    # The reference list is the longest and least informative part of most papers;
    # it must not use up the excerpt budget (the Stage 1B reference extractor reads it).
    sections = {k: v for k, v in paper.get("sections", {}).items()
                if k.strip().lower() not in _REFERENCE_HEADINGS}
    excerpt_parts = []
    used_chars = 0

    def _fit(sec_name, sec_text, budget):
        """The section as a chunk, cut down to the room left rather than dropped:
        a paper whose text is one big section must still reach the model."""
        room = int(budget - used_chars)
        head = f"[{sec_name}]\n"
        if room <= len(head) + 200:
            return None
        return head + sec_text.strip()[: room - len(head) - 2] + "\n\n"

    # First: add priority sections
    for sec_name, sec_text in sections.items():
        if any(kw in sec_name.lower() for kw in priority_keywords) and sec_text.strip():
            chunk = _fit(sec_name, sec_text, max_chars * 0.7)
            if chunk:
                excerpt_parts.append(chunk)
                used_chars += len(chunk)

    # Then: fill with other sections
    for sec_name, sec_text in sections.items():
        if not any(kw in sec_name.lower() for kw in priority_keywords) and sec_text.strip():
            chunk = _fit(sec_name, sec_text, max_chars)
            if chunk:
                excerpt_parts.append(chunk)
                used_chars += len(chunk)

    # Add table summaries
    tables = paper.get("tables", [])
    if tables:
        table_summary = f"[TABLES]\n"
        for t in tables[:5]:
            table_summary += f"Table (page {t['page']}, {t['rows']}x{t['cols']}):\n{t['content'][:500]}\n\n"
        if used_chars + len(table_summary) < max_chars:
            excerpt_parts.append(table_summary)

    # Add figure descriptions
    figures = paper.get("figures", [])
    if figures:
        fig_summary = "[FIGURES]\n"
        for f in figures[:3]:
            fig_summary += f"Page {f['page']}: {f['description'][:300]}\n\n"
        if used_chars + len(fig_summary) < max_chars:
            excerpt_parts.append(fig_summary)

    return "".join(excerpt_parts)[:max_chars]
