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


def relation_table_rows(rows: list[dict], limit: int = 300, quote_limit: int = 140, paper_limit: int = 40) -> list[dict]:
    """The relations as table rows. Every cell is text: a column that mixes numbers and text (a page number
    or a dash) cannot be converted for the table and makes Streamlit log an error on every rerun."""
    out = []
    for r in rows[:limit]:
        quote = r.get("quote") or ""
        out.append({
            "From": r["source"], "Relation": r["relation"], "To": r["target"],
            "Paper": (r.get("paper") or "")[:paper_limit],
            "Page": str(r["page"]) if r.get("page") is not None else "n/a",
            "Quote": quote[:quote_limit] + ("…" if len(quote) > quote_limit else ""),
        })
    return out


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


def _label(value) -> str:
    return str(value or "concept").replace("_", " ")


def connection_counts(graph: dict) -> dict:
    """{entity key: number of relationships touching it}. Relationships may name an entity by id or by name."""
    entities = graph.get("entities") or []
    keys = {e.get("id") or e.get("name") for e in entities}
    by_name = {str(e.get("name", "")).strip().lower(): (e.get("id") or e.get("name")) for e in entities}
    counts: dict = {}
    for r in graph.get("relationships") or []:
        for ref in (r.get("source"), r.get("target")):
            key = ref if ref in keys else by_name.get(str(ref or "").strip().lower())
            if key is not None:
                counts[key] = counts.get(key, 0) + 1
    return counts


def type_counts(graph: dict) -> list[tuple[str, int]]:
    """[(entity type, how many)], largest first."""
    counts: dict = {}
    for e in graph.get("entities") or []:
        t = _label(e.get("type"))
        counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def relation_counts(graph: dict, limit: int = 8) -> list[tuple[str, int]]:
    """[(relationship kind, how many)], most common first."""
    counts: dict = {}
    for r in graph.get("relationships") or []:
        k = _label(r.get("relation"))
        counts[k] = counts.get(k, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def top_connected(graph: dict, limit: int = 8) -> list[dict]:
    """The best-connected entities: [{"name", "type", "connections"}], most links first."""
    counts = connection_counts(graph)
    rows = [{"name": e.get("name", ""), "type": _label(e.get("type")),
             "connections": counts.get(e.get("id") or e.get("name"), 0)} for e in graph.get("entities") or []]
    rows = [r for r in rows if r["connections"] > 0]
    return sorted(rows, key=lambda r: (-r["connections"], r["name"]))[:limit]


_IMPORTANCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def entity_rows(graph: dict) -> list[dict]:
    """Every entity with its type, importance, link count and papers; most important first."""
    counts = connection_counts(graph)
    rows = [{"name": e.get("name", ""), "type": _label(e.get("type")), "importance": e.get("importance", ""),
             "connections": counts.get(e.get("id") or e.get("name"), 0), "papers": list(e.get("papers") or [])}
            for e in graph.get("entities") or []]
    return sorted(rows, key=lambda r: (_IMPORTANCE_ORDER.get(r["importance"], 3), -r["connections"], r["name"]))


def orphan_rows(graph: dict) -> list[dict]:
    """Concepts that appear in a single paper with few links: name, type, importance, papers."""
    rows = []
    for o in graph.get("orphan_concepts") or []:
        ent = o.get("entity") or {}
        rows.append({"name": ent.get("name", ""), "type": _label(ent.get("type")),
                     "importance": ent.get("importance", ""), "papers": list(ent.get("papers") or []),
                     "connections": o.get("connections", 0)})
    return rows


def bridge_rows(graph: dict) -> list[dict]:
    """Possible links between papers: a limitation in one that another paper may answer, split into its parts.
    Runs saved before the parts were stored carry only the joined sentence, so it is taken apart again."""
    rows = []
    for b in graph.get("missing_bridges") or []:
        src, dst, text = b.get("source_paper") or "", b.get("target_paper") or "", b.get("description") or ""
        limitation, solution = b.get("limitation") or "", b.get("solution") or ""
        if not (limitation and solution):
            head, mid, tail = f"'", f"' in {src} could be addressed by ", f" from {dst}"
            if text.startswith(head) and mid in text and text.endswith(tail):
                body = text[len(head):-len(tail)]
                limitation, _, solution = body.partition(mid)
        rows.append({"limitation": limitation.strip().strip("'"), "solution": solution.strip(),
                     "from_paper": src, "to_paper": dst, "description": text})
    return rows


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
