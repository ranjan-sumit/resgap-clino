"""Pure view-models for the Overview, Evidence and Wiki screens (no Streamlit)."""
from __future__ import annotations

import re

from pipeline.coverage import paper_coverage

_WORD = re.compile(r"[a-z0-9]+")
_MATCH_THRESHOLD = 0.3


def _words(text: str) -> set:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 2}


def _as_list(value) -> list:
    """Older runs stored some id lists as their repr string; read both."""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.startswith("["):
        import ast
        try:
            parsed = ast.literal_eval(value)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, SyntaxError):
            return []
    return []


def reverse_index(results: dict) -> dict:
    """{evidence_id: [gap, ...]} - which gaps cite each piece of evidence."""
    index: dict = {}
    for gap in results.get("gaps") or []:
        for eid in _as_list(gap.get("motivating_evidence_ids")):
            index.setdefault(eid, []).append(gap)
    return index


def paper_titles(results: dict) -> dict:
    """{filename: title} from the wiki pages."""
    return {p.get("filename", ""): (p.get("wiki") or {}).get("title") or p.get("title") or p.get("filename", "")
            for p in results.get("papers") or []}


def evidence_rows(results: dict) -> list[dict]:
    """One flat row per evidence item, with where it came from and which gaps cite it."""
    titles = paper_titles(results)
    cited = reverse_index(results)
    rows = []
    for filename, items in (results.get("evidence_objects") or {}).items():
        for e in items:
            prov = e.get("provenance") or {}
            gaps = cited.get(e.get("evidence_id"), [])
            rows.append({
                "id": e.get("evidence_id", ""), "paper": filename, "paper_title": titles.get(filename, filename),
                "type": e.get("evidence_type", ""), "text": e.get("text", ""), "quote": prov.get("quote"),
                "page": prov.get("page"), "section": prov.get("section"), "confidence": e.get("confidence", ""),
                "cited_by": [{"title": g.get("title", ""), "rank": g.get("rank")} for g in gaps],
            })
    return rows


def filter_evidence(rows: list[dict], *, paper: str | None = None, types=(), has_page: bool | None = None,
                    has_quote: bool | None = None, cited_only: bool = False, query: str = "") -> list[dict]:
    q = (query or "").strip().lower()
    out = []
    for r in rows:
        if paper and r["paper"] != paper:
            continue
        if types and r["type"] not in types:
            continue
        if has_page is not None and (r["page"] is not None) != has_page:
            continue
        if has_quote is not None and bool(r["quote"]) != has_quote:
            continue
        if cited_only and not r["cited_by"]:
            continue
        if q and q not in r["text"].lower() and q not in (r["quote"] or "").lower():
            continue
        out.append(r)
    return out


def match_evidence(fact: str, items: list[dict]) -> dict | None:
    """The evidence row (from `evidence_rows`, one paper's) that best states a wiki fact, or None."""
    fw = _words(fact)
    if not fw:
        return None
    best, best_score = None, 0.0
    for r in items:
        rw = _words(r["text"]) | _words(r["quote"] or "")
        score = len(fw & rw) / len(fw)
        if score > best_score:
            best, best_score = r, score
    return best if best_score >= _MATCH_THRESHOLD else None


def citation(row: dict) -> str:
    """'p.4 · 2.2 Collecting respondents' - where in the paper (omitting what is unknown)."""
    parts = []
    if row.get("page") is not None:
        parts.append(f"p.{row['page']}")
    if row.get("section"):
        parts.append(str(row["section"])[:60])
    return " · ".join(parts)


def study_type_label(study_type: str | None) -> str:
    return (study_type or "unknown").replace("_", " ")


def top_gaps(results: dict, n: int = 3) -> list[dict]:
    gaps = list(results.get("gaps") or [])
    gaps.sort(key=lambda g: (g.get("rank") is None, g.get("rank") or 0))
    return [{"title": g.get("title", ""), "rank": g.get("rank"), "status": g.get("validation_status") or "",
             "confidence": g.get("confidence", ""), "papers": len(g.get("supporting_papers") or [])}
            for g in gaps[:n]]


def top_proposal(results: dict) -> dict | None:
    props = results.get("proposals") or []
    if not props:
        return None
    reviewed = [p for p in props if (p.get("review") or {}).get("verdict") not in ("reject",)]
    p = (reviewed or props)[0]
    return {"title": p.get("title", ""), "problem": p.get("problem_statement", ""),
            "confidence": p.get("confidence", ""), "risk": p.get("risk", "")}


def warnings_summary(results: dict) -> list[str]:
    """Everything a reader should know went less than perfectly, in plain sentences."""
    out = []
    if results.get("gate_blocked"):
        out.append("The quality gate failed, so gap analysis was skipped.")
    for row in results.get("pipeline_trace") or []:
        if row.get("status") == "❌":
            out.append(f"{row.get('stage', 'A step')} failed: {row.get('outputs', '')}".strip())
        elif row.get("status") == "⚠️":
            out.append(f"{row.get('stage', 'A step')}: {row.get('outputs', '')}".strip())
    for r in paper_coverage(results):
        if r["status"] != "ok":
            out.append(f"{r['title'][:50]}: " + "; ".join(r["problems"]) + ".")
    flagged = [c for c in [*(results.get("gaps") or []), *(results.get("proposals") or [])]
               if c.get("unsupported_numbers")]
    if flagged:
        out.append(f"{len(flagged)} gap or proposal statement(s) contain numbers not found in the papers.")
    n_fb = len(results.get("model_fallbacks") or [])
    if n_fb:
        out.append(f"{n_fb} model call(s) used the fallback model because the chosen one failed.")
    out += (results.get("calibration") or {}).get("warnings", [])
    q = results.get("run_quality") or {}
    if q.get("quote_rate") is not None and q["quote_rate"] < 0.9:
        out.append(f"Only {q['quote_rate']:.0%} of evidence items have a verified quote.")
    return out


def quality_chips(results: dict) -> list[str]:
    q = results.get("run_quality") or {}
    chips = []
    if q.get("quote_rate") is not None:
        chips.append(f"{q['quote_rate']:.0%} of evidence quoted")
    if q.get("paper_coverage") is not None:
        chips.append(f"{q['paper_coverage']:.0%} of papers fully processed")
    if q.get("duplicate_gap_rate"):
        chips.append(f"{q['duplicate_gap_rate']:.0%} duplicate gaps")
    rep = results.get("repeatability") or {}
    if rep.get("overlap") is not None:
        chips.append(f"{rep['overlap']:.0%} agreement with the previous run")
    return chips
