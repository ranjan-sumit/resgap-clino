"""Quality numbers for a finished run, so a change that makes results worse is visible.

All rates are fractions in [0, 1] or None when there was nothing to measure (never a made-up 0 or 1).
"""
from __future__ import annotations

import re

from pipeline.coverage import paper_coverage

_DUP_THRESHOLD = 0.8


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _duplicate_count(titles: list[str]) -> int:
    """Titles that repeat an earlier title (word-set Jaccard similarity >= 0.8)."""
    seen: list[set] = []
    dups = 0
    for t in titles:
        w = _tokens(t)
        if w and any(len(w & s) / len(w | s) >= _DUP_THRESHOLD for s in seen):
            dups += 1
        elif w:
            seen.append(w)
    return dups


def compute_run_quality(results: dict, *, duration_seconds: float | None = None,
                        call_summary: dict | None = None, tokens_estimated: int | None = None) -> dict:
    evidence = [e for items in (results.get("evidence_objects") or {}).values() for e in items]
    quoted = sum(1 for e in evidence if (e.get("provenance") or {}).get("quote"))

    claims = [*(results.get("gaps") or []), *(results.get("supplementary_gaps") or []),
              *(results.get("proposals") or [])]
    flagged = sum(1 for c in claims if c.get("unsupported_numbers"))

    gap_titles = [g.get("title", "") for g in (results.get("gaps") or [])]
    cov = paper_coverage(results)
    calls = call_summary or {}
    return {
        "quote_rate": _rate(quoted, len(evidence)),
        "unsupported_number_rate": _rate(flagged, len(claims)),
        "duplicate_gap_rate": _rate(_duplicate_count(gap_titles), len(gap_titles)),
        "paper_coverage": _rate(sum(1 for r in cov if r["status"] == "ok"), len(cov)),
        "evidence_items": len(evidence),
        "gaps": len(gap_titles),
        "proposals": len(results.get("proposals") or []),
        "llm_calls": calls.get("calls"),
        "llm_calls_failed": calls.get("failed"),
        "duration_seconds": duration_seconds,
        "tokens_estimated": tokens_estimated,
    }
