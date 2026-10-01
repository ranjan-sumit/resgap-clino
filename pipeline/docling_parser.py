"""
Stage 1 (Clinova Phase 1, Epic 1.1): Docling-based structural extraction.

Second, independent parser alongside pipeline/pdf_parser.py's PyMuPDF/
pdfplumber extraction -- feeds pipeline/extraction_reconciler.py's
multi-parser reconciliation (05-data-architecture.md §2-3).

Docling is measured heavy on this dev machine (no GPU): ~1.1GB process RSS,
~86s/paper steady-state convert time (evals/benchmarks/baseline/
docling-resource-measurement.md). Caching by content hash is therefore a
binding requirement, not an optimization -- every call goes through the
cache-aside check here before running a real conversion (same AD-2 pattern
already used for LLM calls).
"""
import hashlib
from pathlib import Path

from utils.database import get_cached_docling_extraction, save_cached_docling_extraction

# Clinova Phase 2, Story 2.1.1: bumped 1 -> 2. The cached result shape gained
# `text_segments` (page-tagged body text, sourced from doc.texts) -- a v1
# cache row lacks that field entirely, so old entries must not be served as
# if they had it (AD-3's stage_logic_version convention, unchanged from
# Phase 1's use of it).
DOCLING_STAGE_VERSION = 2


def _content_hash(pdf_path: str) -> str:
    return hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()


def extract_with_docling(pdf_path: str, filename: str) -> dict:
    """
    Run (or fetch cached) Docling extraction for one PDF.

    Returns:
        {
          "filename": str,
          "source": "docling",
          "full_text": str,        # markdown export
          "char_count": int,
          "tables": [{"page": int|None, "content": str, "rows": int, "cols": int}],
          "text_segments": [{"text": str, "page": int|None, "label": str}],
            # Real per-segment page numbers from Docling's own document
            # model (doc.texts[i].prov[0].page_no) -- not inferred, not a
            # best guess. This is what gives pipeline/evidence_extractor.py
            # (Phase 2, Epic 2.1) genuine page-level provenance instead of
            # section-only. `label` is Docling's own semantic tag
            # (e.g. "text", "section_header", "page_header") -- callers can
            # filter out headers/footers rather than treating every segment
            # as body prose.
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

    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    conv_result = converter.convert(pdf_path)
    doc = conv_result.document

    full_text = doc.export_to_markdown()
    tables = []
    for i, table in enumerate(doc.tables):
        try:
            df = table.export_to_dataframe()
            rows, cols = df.shape
            content = df.to_csv(index=False, sep="|")
        except Exception:
            rows, cols = 0, 0
            content = ""
        page = None
        prov = getattr(table, "prov", None)
        if prov:
            try:
                page = prov[0].page_no
            except Exception:
                page = None
        tables.append({"page": page, "content": content, "rows": rows, "cols": cols, "index": i})

    text_segments = []
    for item in getattr(doc, "texts", []):
        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        page = None
        prov = getattr(item, "prov", None)
        if prov:
            try:
                page = prov[0].page_no
            except Exception:
                page = None
        label = str(getattr(item, "label", "") or "")
        text_segments.append({"text": text, "page": page, "label": label})

    result = {
        "filename": filename,
        "source": "docling",
        "full_text": full_text,
        "char_count": len(full_text),
        "tables": tables,
        "text_segments": text_segments,
        "from_cache": False,
    }

    try:
        save_cached_docling_extraction(cache_key, content_hash, DOCLING_STAGE_VERSION, result)
    except Exception:
        # A cache-write failure must not discard the ~90s conversion result
        # that was just produced -- mirrors pipeline/reference_extractor.py's
        # save guard: swallow, and still return the real extraction.
        pass
    return result
