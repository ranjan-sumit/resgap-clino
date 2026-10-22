"""View-models for the Gaps and Proposals screens: rows, sorting, filtering, links, comparison."""
from __future__ import annotations

from pipeline.coverage import _is_paper
from ui.evidence_view import _as_list

STATUS_ORDER = {"open": 0, "partial": 1, "unverified": 2, "contested": 3, "likely_closed": 4, "solved": 5,
                "closed": 5, "pending": 6, "": 7}
LENS_LABELS = {
    "limitation_miner": "Limitation miner", "cross_paper_synthesizer": "Cross-paper synthesis",
    "methodology_auditor": "Methodology audit", "semantic": "Model-written", "deterministic": "Rule-based check",
    "graph_structural": "Graph signal",
}
SORTS = {
    "Rank": lambda r: (r["rank"] is None, r["rank"] or 0),
    "Score (high first)": lambda r: -(r["score"] or 0),
    "Status (open first)": lambda r: (STATUS_ORDER.get(r["status"], 7), r["rank"] or 999),
    "Most papers": lambda r: -r["n_papers"],
}


def finder_of(gap: dict) -> str:
    key = gap.get("lens") or str(gap.get("source") or "").replace("agent:", "") or "semantic"
    return LENS_LABELS.get(key, key.replace("_", " ").capitalize())


def gap_rows(results: dict) -> list[dict]:
    rows = []
    for i, g in enumerate(results.get("gaps") or []):
        links = []
        for p in g.get("existing_papers") or []:
            if isinstance(p, dict):
                url = p.get("url") or (f"https://doi.org/{p['doi']}" if p.get("doi") else None)
                links.append({"title": p.get("title", ""), "year": p.get("year"), "url": url})
        rows.append({
            "index": i, "gap": g, "gap_id": g.get("gap_id", ""), "rank": g.get("rank"),
            "title": g.get("title", ""), "status": (g.get("validation_status") or "").lower(),
            "confidence": g.get("confidence", ""), "finder": finder_of(g), "gap_type": g.get("gap_type", ""),
            "papers": list(g.get("supporting_papers") or []), "n_papers": len(g.get("supporting_papers") or []),
            "score": g.get("composite_score"), "n_evidence": len(_as_list(g.get("motivating_evidence_ids"))),
            "links": links,
        })
    return rows


def filter_gaps(rows: list[dict], *, statuses=(), finders=(), paper: str | None = None, query: str = "") -> list[dict]:
    q = (query or "").strip().lower()
    out = []
    for r in rows:
        if statuses and r["status"] not in statuses:
            continue
        if finders and r["finder"] not in finders:
            continue
        if paper and not any(_is_paper(ref, paper, paper) for ref in r["papers"]):
            continue
        if q and q not in r["title"].lower() and q not in str(r["gap"].get("description", "")).lower():
            continue
        out.append(r)
    return out


def sort_gaps(rows: list[dict], how: str = "Rank") -> list[dict]:
    return sorted(rows, key=SORTS.get(how, SORTS["Rank"]))


# ── proposals ────────────────────────────────────────────────────────────────────────────────
def proposal_rows(results: dict) -> list[dict]:
    gaps = {g.get("gap_id"): g for g in results.get("gaps") or [] if g.get("gap_id")}
    rows = []
    for i, p in enumerate(results.get("proposals") or []):
        gap = gaps.get(p.get("addresses_gap_id"))
        review = p.get("review") or {}
        scores = review.get("scores") or {}
        rows.append({
            "index": i, "proposal": p, "title": p.get("title", ""), "gap_title": (gap or {}).get("title"),
            "gap_rank": (gap or {}).get("rank"), "gap_id": p.get("addresses_gap_id", ""),
            "verdict": review.get("verdict", ""), "scores": scores,
            "confidence": p.get("confidence", ""), "risk": p.get("risk", ""), "effort": p.get("effort_estimate", ""),
            "key": proposal_key(p, i),
        })
    return rows


def proposal_key(p: dict, index: int) -> str:
    """A stable id for feedback: the gap it addresses plus its position."""
    return f"{p.get('addresses_gap_id') or 'x'}:{index}"


_COMPARE_FIELDS = [("Addresses gap", "gap_title"), ("Confidence", "confidence"), ("Risk", "risk"),
                   ("Effort", "effort"), ("Review verdict", "verdict")]
_COMPARE_TEXT = [("Problem", "problem_statement"), ("Methodology", "methodology"), ("Novelty", "novelty"),
                 ("Expected contribution", "expected_contribution")]


def compare_proposals(a: dict, b: dict) -> list[dict]:
    """Side-by-side rows [{field, a, b}] for two proposal rows (from proposal_rows)."""
    out = [{"field": label, "a": str(a.get(k) or "—"), "b": str(b.get(k) or "—")} for label, k in _COMPARE_FIELDS]
    for label, k in _COMPARE_TEXT:
        out.append({"field": label, "a": str(a["proposal"].get(k) or "—"), "b": str(b["proposal"].get(k) or "—")})
    return out
