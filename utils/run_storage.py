"""What is stored for a run, and in what shape.

A pipeline run's results hold the paper text twice over (`corpus` repeats every
paper's full text, sections and page segments) and the per-paper section text
(~160 KB for three papers) that only the Computational Lab reads. Stored as-is
that is ~1.2 MB per run and every screen loads all of it.

`split_for_storage` returns the lean results plus the section text to keep in a
side table; `restore_sections` puts it back on demand. Both layouts are
accepted on read, so runs saved before this change open unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Heavy text fields that are duplicates of what `papers` already holds.
_CORPUS_DROP = ("full_text", "text_segments", "sections")


def split_for_storage(results: dict) -> tuple[dict, dict]:
    """(lean_results, {"paper_sections": {<filename>: sections}}). The input is not modified."""
    lean = dict(results)
    sections: dict[str, dict] = {}

    if isinstance(lean.get("corpus"), list):
        lean["corpus"] = [{k: v for k, v in item.items() if k not in _CORPUS_DROP}
                          if isinstance(item, dict) else item for item in lean["corpus"]]

    if isinstance(lean.get("papers"), list):
        papers = []
        for i, p in enumerate(lean["papers"]):
            if isinstance(p, dict) and p.get("sections"):
                key = p.get("filename") or f"paper_{i}"
                sections[key] = p["sections"]
                p = {k: v for k, v in p.items() if k not in ("sections", "full_text", "text_segments")}
                p["sections_key"] = key
            papers.append(p)
        lean["papers"] = papers
    return lean, ({"paper_sections": sections} if sections else {})


def restore_sections(results: dict, sections: dict | None) -> dict:
    """Puts stored section text back on each paper that was split. No-op for runs saved inline."""
    if not sections or not isinstance(results.get("papers"), list):
        return results
    out = dict(results)
    out["papers"] = [{**{k: v for k, v in p.items() if k != "sections_key"}, "sections": sections[p["sections_key"]]}
                     if isinstance(p, dict) and p.get("sections_key") in sections and "sections" not in p else p
                     for p in results["papers"]]
    return out


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_utc_iso(naive_local: str) -> str:
    """A timestamp saved as naive local time -> UTC ISO with 'Z'. Already-UTC values pass through."""
    if not naive_local or naive_local.endswith("Z") or "+" in naive_local[10:]:
        return naive_local
    local = datetime.fromisoformat(naive_local).astimezone()           # interprets naive as machine-local time
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_local_display(ts: str, tz_name: str | None = None) -> str:
    """'YYYY-MM-DD HH:MM' for a stored timestamp, in `tz_name` (the browser's zone) or machine-local."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts[:16].replace("T", " ")
    if dt.tzinfo is None:                                   # legacy naive value: already local
        return dt.strftime("%Y-%m-%d %H:%M")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return dt.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")
