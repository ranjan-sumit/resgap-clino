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

DOCLING_STAGE_VERSION = 1


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

    result = {
        "filename": filename,
        "source": "docling",
        "full_text": full_text,
        "char_count": len(full_text),
        "tables": tables,
        "from_cache": False,
    }

    save_cached_docling_extraction(cache_key, content_hash, DOCLING_STAGE_VERSION, result)
    return result
