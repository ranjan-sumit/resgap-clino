"""
Graph-Structural Gap Detector (Clinova Phase 3, Epic 3.2 — Hybrid Gap
Engine, signal source 2 of 3, per 04-ai-research-architecture.md §4).

04-ai-research-architecture.md §4 names this source as "queries over the
persisted graph (Neo4j, Phase 3)". Neo4j is not available on this
development machine (no Docker/admin rights, same constraint already
documented for GROBID) -- but the graph itself already exists and is
already persisted-for-the-run without Neo4j: pipeline/graph_builder.py's
`build_knowledge_graph()` builds a real entity/relationship graph (the
existing "LazyGraphRAG style" local graph) for every run today. This
module queries THAT graph structurally -- no LLM call, no new
infrastructure -- deferring only the eventual move to a real persisted
Neo4j instance (cross-run graph queries, not needed for a single run's
gap analysis) to whenever that infra becomes available.

Domain-agnostic by design (unlike deterministic_gap_patterns.py's
healthcare-specific pattern library) -- graph structure signals apply to
any domain's entity/relationship graph.

Three structural signals, each producing gap candidates shaped identically
to gap_detector.py's/deterministic_gap_patterns.py's output so all three
sources merge into one list without special-casing:

1. Orphan concepts -- entities isolated from the rest of the graph
   (pipeline/graph_builder.py's existing find_orphan_concepts(), already
   computed for every run; previously only fed as unstructured text hints
   into the LLM's semantic prompt, never surfaced as its own tagged
   candidate gap).
2. Missing bridges -- a limitation in one paper with a plausible solution
   named in another paper (existing find_missing_bridges(); same
   promotion from "LLM prompt hint" to "tagged candidate").
3. Conflicting relationship claims -- the same entity pair connected by
   two relationships whose `relation` values are recognized opposites
   (e.g. "outperforms" vs "underperforms_on"), drawn from different
   papers. New in this module -- not computed anywhere else.
4. Untested combinations -- two well-connected, differently-typed,
   high-importance entities that never co-occur in a relationship or a
   shared paper. New in this module -- the literal example given in
   04-ai-research-architecture.md §4 ("an intervention studied in
   population A and a dataset studied in population B, never studied
   together").
"""

GRAPH_STRUCTURAL_STAGE_VERSION = 1

# Recognized opposite-meaning relation pairs, pooled across every domain's
# relationship_types in domain_config.py (kept here, not per-domain, since
# the pairing logic itself -- "these two mean opposite things" -- doesn't
# change per domain, only which entities the relations connect does).
_CONTRADICTORY_RELATION_PAIRS = {
    frozenset({"outperforms", "underperforms_on"}),
    frozenset({"extends", "contradicts"}),
    frozenset({"validated_on", "fails_on"}),
    frozenset({"generalizes_to", "fails_on"}),
    frozenset({"approved_for", "fails_on"}),
    frozenset({"enables", "ignores"}),
    frozenset({"robust_to", "sensitive_to"}),
    frozenset({"converges_under", "vulnerable_to"}),
    frozenset({"protects_against", "vulnerable_to"}),
    frozenset({"aligned_with", "biased_toward"}),
}

# Cap how many candidates any one signal can emit -- mirrors the existing
# orphans[:10]/bridges[:10] truncation convention already used when this
# graph data is fed into the LLM prompt (pipeline/gap_detector.py), so this
# module doesn't flood the gap list any more than that path already bounds.
_MAX_PER_SIGNAL = 8


def _entity_key(entity: dict) -> str:
    return entity.get("id") or entity.get("name", "")


def _is_paper_container_entity(entity: dict) -> bool:
    """True if this "entity" actually represents an entire uploaded paper
    rather than a domain concept -- real-data finding (2026-08-21,
    validated against the AuDHD_1/AuDHD_2 corpus, whose run happened to hit
    graph_builder.py's `_fallback_graph_from_wiki` path): the fallback
    graph adds each paper itself as a `type="domain"` entity via
    `add_entity(title, "domain", title, ...)`, which makes the entity's
    OWN `name` equal to its own `papers[0]` -- a self-referential
    signature no genuine domain concept would have. Left unfiltered, the
    untested-combination signal paired whole paper titles against real
    concepts ("Untested combination: <full paper title> x Some Metric"),
    which is meaningless -- a paper is not itself a "domain concept" a
    combination check should reason about. This check is defensive against
    the real LLM-extracted graph too, not just the fallback path: it keys
    on the self-reference, not on `type == "domain"` (a real domain-type
    concept entity's name will essentially never equal one of its own
    listed source papers)."""
    name = str(entity.get("name", "")).strip().lower()
    if not name:
        return False
    return name in {str(p).strip().lower() for p in entity.get("papers", [])}


def _resolve_ref(ref: str, entity_by_id: dict, entity_by_name: dict) -> dict | None:
    if ref in entity_by_id:
        return entity_by_id[ref]
    return entity_by_name.get(str(ref).lower())


def _make_gap(title: str, description: str, gap_type: str, why: str,
              supporting_papers: list, evidence_lines: list, signal_id: str,
              confidence: str = "medium") -> dict:
    return {
        "title": title,
        "description": description,
        "gap_type": gap_type,
        "confidence": confidence,
        "evidence": evidence_lines,
        "supporting_papers": supporting_papers,
        "missing_connection": title,
        "why_important": why,
        "validation_status": "pending",
        "existing_papers": [],
        "source": "graph_structural",
        "pattern_id": signal_id,
    }


def _orphan_gaps(orphan_concepts: list) -> list[dict]:
    # Same paper-container-entity risk as the two signals below: a paper
    # with very few extracted wiki fields could itself end up with <=1
    # graph connections and get returned by find_orphan_concepts() as an
    # "orphan" -- guarded here too, not just where it was first found,
    # since orphan_concepts is graph_builder.py's own pre-filtered list
    # and was never actually guaranteed to exclude these.
    real_concepts = [o for o in orphan_concepts if not _is_paper_container_entity(o.get("entity", {}))]
    gaps = []
    for o in real_concepts[:_MAX_PER_SIGNAL]:
        entity = o.get("entity", {})
        name = entity.get("name", "unknown concept")
        papers = entity.get("papers", [])
        gaps.append(_make_gap(
            title=f"Unexplored concept: {name}",
            description=(f"'{name}' appears in this corpus's knowledge graph with only "
                          f"{o.get('connections', 0)} connection(s) and is mentioned in "
                          f"{len(papers)} paper(s) -- introduced but not built upon."),
            gap_type="theory",
            why="A concept mentioned once with minimal cross-paper connection is a candidate unexplored area -- nobody in this corpus has followed up on it.",
            supporting_papers=papers,
            evidence_lines=[o.get("signal", "")],
            signal_id="graph_orphan_concept",
            confidence="low",
        ))
    return gaps


def _bridge_gaps(missing_bridges: list) -> list[dict]:
    gaps = []
    for b in missing_bridges[:_MAX_PER_SIGNAL]:
        src = b.get("source_paper", "")
        tgt = b.get("target_paper", "")
        gaps.append(_make_gap(
            title=f"Cross-paper bridge: {src} → {tgt}",
            description=b.get("description", ""),
            gap_type="methodology",
            why="A limitation named in one paper appears directly addressable by an approach from another paper in this corpus, but no paper does both.",
            supporting_papers=[p for p in (src, tgt) if p],
            evidence_lines=[b.get("description", "")],
            signal_id="graph_missing_bridge",
            confidence="medium",
        ))
    return gaps


def _conflicting_relationship_gaps(entities: list, relationships: list) -> list[dict]:
    entity_by_id = {_entity_key(e): e for e in entities}
    entity_by_name = {str(e.get("name", "")).lower(): e for e in entities}

    # (frozenset({src_key, tgt_key})) -> list of (relation, paper) seen
    pair_relations: dict = {}
    for rel in relationships:
        src = _resolve_ref(rel.get("source", ""), entity_by_id, entity_by_name)
        tgt = _resolve_ref(rel.get("target", ""), entity_by_id, entity_by_name)
        if not src or not tgt:
            continue
        relation = (rel.get("relation") or "").strip().lower()
        if not relation:
            continue
        pair_key = frozenset({_entity_key(src), _entity_key(tgt)})
        pair_relations.setdefault(pair_key, []).append(
            (relation, rel.get("paper", ""), src.get("name", ""), tgt.get("name", ""))
        )

    gaps = []
    for pair_key, seen in pair_relations.items():
        relation_set = {s[0] for s in seen}
        if len(relation_set) < 2:
            continue
        conflict_found = None
        for a in relation_set:
            for b in relation_set:
                if a != b and frozenset({a, b}) in _CONTRADICTORY_RELATION_PAIRS:
                    conflict_found = (a, b)
                    break
            if conflict_found:
                break
        if not conflict_found:
            continue
        a, b = conflict_found
        entries_a = [s for s in seen if s[0] == a]
        entries_b = [s for s in seen if s[0] == b]
        name_pair = f"{entries_a[0][2]} ↔ {entries_a[0][3]}"
        papers = sorted({s[1] for s in seen if s[1]})
        gaps.append(_make_gap(
            title=f"Conflicting claims: {name_pair}",
            description=(f"This corpus's knowledge graph records both '{a}' and '{b}' between "
                          f"{name_pair}, from different papers -- these are contradictory claims "
                          f"about the same relationship."),
            gap_type="evaluation",
            why="Two papers making opposite claims about the same relationship is itself a gap: nobody in this corpus has reconciled the disagreement.",
            supporting_papers=papers,
            evidence_lines=[f"{a}: {e[1]}" for e in entries_a[:2]] + [f"{b}: {e[1]}" for e in entries_b[:2]],
            signal_id="graph_conflicting_relationship",
            confidence="medium",
        ))
        if len(gaps) >= _MAX_PER_SIGNAL:
            break
    return gaps


def _untested_combination_gaps(entities: list, relationships: list) -> list[dict]:
    high_importance = [e for e in entities if e.get("importance") == "high"]
    if len(high_importance) < 2:
        return []

    entity_by_id = {_entity_key(e): e for e in entities}
    entity_by_name = {str(e.get("name", "")).lower(): e for e in entities}

    connected_pairs = set()
    connection_count: dict = {}
    for rel in relationships:
        src = _resolve_ref(rel.get("source", ""), entity_by_id, entity_by_name)
        tgt = _resolve_ref(rel.get("target", ""), entity_by_id, entity_by_name)
        if not src or not tgt:
            continue
        connected_pairs.add(frozenset({_entity_key(src), _entity_key(tgt)}))
        connection_count[_entity_key(src)] = connection_count.get(_entity_key(src), 0) + 1
        connection_count[_entity_key(tgt)] = connection_count.get(_entity_key(tgt), 0) + 1

    gaps = []
    for i, e1 in enumerate(high_importance):
        for e2 in high_importance[i + 1:]:
            if e1.get("type") == e2.get("type"):
                continue  # same-type pairs aren't a "combination", e.g. two datasets
            k1, k2 = _entity_key(e1), _entity_key(e2)
            if frozenset({k1, k2}) in connected_pairs:
                continue  # already studied together
            papers1 = set(e1.get("papers", []))
            papers2 = set(e2.get("papers", []))
            if papers1 & papers2:
                continue  # co-mentioned in a shared paper -- not untested
            # Require each to be non-trivially connected elsewhere -- an
            # isolated entity is the orphan signal's job, not this one's.
            if connection_count.get(k1, 0) < 1 or connection_count.get(k2, 0) < 1:
                continue
            gaps.append(_make_gap(
                title=f"Untested combination: {e1.get('name','')} × {e2.get('name','')}",
                description=(f"'{e1.get('name','')}' ({e1.get('type','')}) and "
                              f"'{e2.get('name','')}' ({e2.get('type','')}) are each studied "
                              f"elsewhere in this corpus but never together."),
                gap_type="application",
                why="Each element has been individually validated in this corpus, but the combination itself has not been studied -- a concrete, feasible next study.",
                supporting_papers=sorted(papers1 | papers2),
                evidence_lines=[
                    f"{e1.get('name','')} studied in: {', '.join(papers1) or 'this corpus'}",
                    f"{e2.get('name','')} studied in: {', '.join(papers2) or 'this corpus'}",
                ],
                signal_id="graph_untested_combination",
                confidence="low",
            ))
            if len(gaps) >= _MAX_PER_SIGNAL:
                return gaps
    return gaps


def detect_graph_structural_gaps(graph: dict) -> list[dict]:
    """Entry point. `graph` is the dict build_knowledge_graph() already
    returns for every run (entities/relationships/orphan_concepts/
    missing_bridges) -- no new computation of the graph itself, only new
    ways of querying it for gap candidates."""
    if not graph:
        return []

    # Excludes paper-container "entities" (see _is_paper_container_entity)
    # from the two NEW signals below -- orphan/bridge promotion below
    # reuses graph_builder.py's own already-computed lists as-is, since
    # those never included paper-container nodes to begin with (they're
    # filtered on `importance`/`connections`/cross_links, not on the raw
    # entity list).
    entities = [e for e in graph.get("entities", []) if not _is_paper_container_entity(e)]
    relationships = graph.get("relationships", [])

    gaps = []
    gaps.extend(_orphan_gaps(graph.get("orphan_concepts", [])))
    gaps.extend(_bridge_gaps(graph.get("missing_bridges", [])))
    gaps.extend(_conflicting_relationship_gaps(entities, relationships))
    gaps.extend(_untested_combination_gaps(entities, relationships))
    return gaps
