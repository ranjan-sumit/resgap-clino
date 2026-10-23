"""
Stage 1: Multimodal PDF Parser
Extracts text by section, tables, and optionally figures via GPT-4o Vision.
"""
import io
import os
import re
import pdfplumber
from pipeline import figures as figure_reader
from pipeline import pdf_limits
from utils.text_hygiene import find_instructions, strip_invisible, visible_char
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


_X_TOLERANCE = 1.5            # pdfplumber's default (3) fuses words in tightly set PDFs ("Rowe,S.M.;Miller,S.;...")
_RUN_TOGETHER_SHARE = 0.03    # more than this share of words 18+ letters long means the spaces were lost


def _words_run_together(text: str) -> bool:
    words = text.split()
    return len(words) >= 40 and sum(1 for w in words if re.search(r"[A-Za-z]{18,}", w)) / len(words) > _RUN_TOGETHER_SHARE


def _page_text(page) -> str:
    """One page's text with spaces between words. If the words still run together at the usual spacing
    tolerance, the page is read again with a tighter one."""
    visible = page.filter(visible_char)
    text = visible.extract_text(x_tolerance=_X_TOLERANCE) or ""
    if _words_run_together(text):
        text = visible.extract_text(x_tolerance=1.0) or text
    return text


def _extract_text_by_section(pdf_path: str) -> dict:
    """
    Use pdfplumber to extract text, grouping content by detected section headers.
    Returns dict: {section_name: text_content}
    """
    sections = {"_header": ""}
    current_section = "_header"
    full_text = []

    removed = 0
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text, n = strip_invisible(_page_text(page))
            removed += n
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
        "invisible_removed": removed,
    }


_REFERENCE_HEADINGS = frozenset({"references", "bibliography", "literature cited", "reference list"})
_NON_BODY_LABELS = frozenset({"page_header", "page_footer", "page_number"})
_MIN_STRUCTURAL_SECTIONS = 3


def _structural_extraction(pdf_path: str, filename: str) -> dict:
    """The structural parser's output ({} when it cannot run): page-tagged text blocks that carry
    real page numbers and heading labels, and the ruled tables it found."""
    try:
        from pipeline.docling_parser import extract_with_docling  # lazy: it imports this module
        return extract_with_docling(pdf_path, filename)
    except Exception:
        return {}


def _structural_segments(pdf_path: str, filename: str) -> list:
    """The page-tagged text blocks from the structural parser ([] when it cannot run)."""
    return list(_structural_extraction(pdf_path, filename).get("text_segments", []))


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
        if not text or label in _NON_BODY_LABELS or label == "table":      # tables live in paper["tables"]
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


def _strip_furniture(result: dict, segments: list) -> None:
    """Running headers, footers and page numbers the structural parser recognised are removed
    from the keyword-based sections and the full text too (they would otherwise be read as
    paper content and, for a journal-name banner, as a section)."""
    junk = {" ".join((s.get("text") or "").lower().split()) for s in segments if s.get("label") in _NON_BODY_LABELS}
    junk.discard("")
    if not junk:
        return

    def clean(text: str) -> str:
        return "\n".join(line for line in text.split("\n") if " ".join(line.lower().split()) not in junk)

    result["sections"] = {k: clean(v) if isinstance(v, str) else v for k, v in result["sections"].items()}
    result["full_text"] = clean(result["full_text"])
    result["char_count"] = len(result["full_text"])


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


MIN_READABLE_CHARS = 200


def check_pdf_readable(pdf_path: str) -> str | None:
    """Returns None when the PDF has a usable text layer, otherwise a short
    reason it cannot be analysed (so the wiki model is never given nothing)."""
    try:
        too_big = pdf_limits.size_problem(os.path.getsize(pdf_path))
        if too_big:
            return too_big
        if FITZ_AVAILABLE:
            doc = fitz.open(pdf_path)
            try:
                if doc.needs_pass or doc.is_encrypted:
                    return "password-protected (encrypted)"
                too_long = pdf_limits.page_problem(len(doc))      # before any page is read
                if too_long:
                    return too_long
                chars = sum(len(page.get_text().strip()) for page in doc)
            finally:
                doc.close()
        else:
            with pdfplumber.open(pdf_path) as pdf:
                too_long = pdf_limits.page_problem(len(pdf.pages))
                if too_long:
                    return too_long
                chars = sum(len((p.extract_text() or "").strip()) for p in pdf.pages)
    except Exception as e:
        msg = str(e).lower()
        if "password" in msg or "encrypt" in msg:
            return "password-protected (encrypted)"
        return "corrupt or not a valid PDF"
    if chars < MIN_READABLE_CHARS:
        return "no text layer (a scanned image?) - run OCR on it first"
    return None


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
    structural_out = _structural_extraction(pdf_path, filename)
    segments = list(structural_out.get("text_segments", []))
    result["text_segments"] = segments          # page-tagged blocks: the evidence reader's input
    structural = _sections_from_segments(segments)
    if structural is not None and (
        legacy_named < _MIN_STRUCTURAL_SECTIONS
        or len(result["sections"].get("_header", "")) > 0.5 * max(1, text_data["char_count"])
    ):
        result["sections"] = structural
    result["full_text"] = text_data["full_text"]
    result["char_count"] = text_data["char_count"]
    _strip_furniture(result, segments)
    seg_hygiene = structural_out.get("hygiene") or {}
    result["hygiene"] = {                       # what was found in, or taken out of, this paper's text
        "hidden_chars": int(seg_hygiene.get("hidden_chars", 0)),
        "invisible_removed": int(seg_hygiene.get("invisible_removed", 0)) + int(text_data.get("invisible_removed", 0)),
        "instruction_hits": find_instructions(result["full_text"]),
    }

    # Tables: the structural parser reads ruled tables as real rows; pdfplumber is the fallback.
    result["tables"] = list(structural_out.get("tables") or []) or _extract_tables(pdf_path)

    # Figures are found from the PDF itself (a caption with a picture or chart beside it); no model is involved in that.
    # With vision on, the first few are shown to the model, each with its caption.
    if FITZ_AVAILABLE:
        try:
            located = figure_reader.find_figures(pdf_path, max_figures=50)
        except Exception:
            located = []
        result["figure_list"] = [{k: f[k] for k in ("label", "page", "caption", "kind")} for f in located]
        if use_vision and client and located:
            result["figures"] = figure_reader.analyze_figures(
                pdf_path, client, located[:figure_reader.MAX_FIGURES], on_progress)

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
    figures = [f for f in paper.get("figures", []) if f.get("description")]
    if figures:
        fig_summary = "[FIGURES -- described by a model from the images; values may be approximate]\n"
        for f in figures[:3]:
            fig_summary += (f"{f.get('label', 'Figure')} (page {f['page']}): "
                            f"{figure_reader.mark_unsupported(f['description'], f.get('numbers_not_in_text', []))[:360]}\n\n")
        if used_chars + len(fig_summary) < max_chars:
            excerpt_parts.append(fig_summary)

    return "".join(excerpt_parts)[:max_chars]
