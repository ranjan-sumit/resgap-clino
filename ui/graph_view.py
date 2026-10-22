"""View-models for the Graph screen: the relations table with its evidence, filters, and the orphan note."""
from __future__ import annotations


def _entity_names(graph: dict) -> dict:
    return {e.get("id"): e.get("name", e.get("id", "")) for e in graph.get("entities") or []}


def relation_rows(graph: dict, evidence_by_id: dict | None = None) -> list[dict]:
    """One row per relationship: who relates to whom, from which paper, with the quote and page it rests on.
    `evidence_by_id` ({evidence_id: row from evidence_view.evidence_rows}) fills in page and section."""
    names = _entity_names(graph)
    by_id = evidence_by_id or {}
    rows = []
    for r in graph.get("relationships") or []:
        ids = [i for i in (r.get("provenance_evidence_ids") or []) if i]
        ev = by_id.get(ids[0]) if ids else None
        rows.append({
            "source": names.get(r.get("source"), r.get("source", "")),
            "relation": str(r.get("relation", "")).replace("_", " "),
            "target": names.get(r.get("target"), r.get("target", "")),
            "paper": r.get("paper", ""),
            "quote": (r.get("evidence") or "") if (r.get("grounded") or ids) else "",
            "page": r.get("page") if r.get("page") is not None else (ev or {}).get("page"),
            "section": (ev or {}).get("section"),
            "evidence_ids": ids, "grounded": bool(r.get("grounded") or ids),
            "linked_by": r.get("linked_by", ""),
        })
    return rows


def filter_relations(rows: list[dict], *, relations=(), paper: str | None = None, entity: str = "",
                     grounded_only: bool = False) -> list[dict]:
    e = (entity or "").strip().lower()
    out = []
    for r in rows:
        if relations and r["relation"] not in relations:
            continue
        if paper and r["paper"] != paper:
            continue
        if e and e not in r["source"].lower() and e not in r["target"].lower():
            continue
        if grounded_only and not r["grounded"]:
            continue
        out.append(r)
    return out


def grounding_summary(graph: dict) -> dict:
    rels = graph.get("relationships") or []
    grounded = sum(1 for r in rels if r.get("grounded") or r.get("provenance_evidence_ids"))
    return {"relations": len(rels), "grounded": grounded,
            "share": round(grounded / len(rels), 3) if rels else None}


def orphan_explanation(graph: dict) -> str:
    """Plain-language note on entities that connect to nothing (or one paper only)."""
    diag = graph.get("diagnostics") or {}
    n = int((graph.get("stats") or {}).get("orphan_count") or len(graph.get("orphan_concepts") or []))
    if diag.get("grounded"):
        left = diag.get("orphans_remaining", 0)
        text = (f"{diag.get('orphans_after_extraction', 0)} entities had no relationship after the first pass; "
                f"{diag.get('linked_by_comention', 0)} were linked because the same evidence item names both, and "
                f"{diag.get('linked_by_model', 0)} by a second model pass. {left} remain unlinked.")
        return text
    if n:
        return (f"{n} entities appear in only one paper with few links. They are signals of unexplored "
                "areas, not errors; a graph built from quoted evidence connects more of them.")
    return ""
