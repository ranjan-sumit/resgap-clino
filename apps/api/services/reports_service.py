"""Report export (Clinova Phase 5, Epic 5.5). Wraps utils/export.py's
existing HTML/PDF/Markdown/JSON report builders -- already real, already
used by the Streamlit app's download buttons (app.py ~2595-2647) -- rather
than reimplementing report generation. Uses the deterministic narrative
fallback (no LLM client passed to generate_report_narrative), matching this
project's "never a surprise LLM cost on a plain GET" discipline; the
fallback text is real structured-data-derived prose, not a placeholder.
"""
from apps.api.errors import NotFoundError
from utils.database import load_run
from utils.export import to_enterprise_html_report, to_enterprise_pdf_report, to_json, to_markdown_report

REPORT_FORMATS = ("html", "pdf", "markdown", "json")

_MEDIA_TYPES = {
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
    "markdown": "text/markdown; charset=utf-8",
    "json": "application/json",
}


def get_run_report(run_id: str, fmt: str) -> tuple[bytes | str, str, str]:
    """Returns (content, filename, media_type)."""
    if fmt not in REPORT_FORMATS:
        raise NotFoundError(f"Unknown report format '{fmt}'. Must be one of {REPORT_FORMATS}.")

    loaded = load_run(run_id) or {}
    results = loaded.get("results") or {}
    if not results:
        raise NotFoundError(f"Run '{run_id}' was not found, or has no saved results to report on.")

    context = results.get("context") or {}
    base_name = f"clinova_report_{run_id[:8]}"

    if fmt == "html":
        return to_enterprise_html_report(results, context), f"{base_name}.html", _MEDIA_TYPES[fmt]
    if fmt == "pdf":
        return to_enterprise_pdf_report(results, context), f"{base_name}.pdf", _MEDIA_TYPES[fmt]
    if fmt == "markdown":
        return to_markdown_report(results, context), f"{base_name}.md", _MEDIA_TYPES[fmt]
    return to_json(results), f"{base_name}.json", _MEDIA_TYPES[fmt]
