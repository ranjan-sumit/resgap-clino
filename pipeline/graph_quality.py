"""
Knowledge-graph build scoring (Clinova Phase 3, Epic 3.1's remaining
scope) per 01-prd.md FR-7: "Every knowledge-graph build is versioned and
scored: build status, quality score, extraction coverage, evidence
coverage, duplicate rate, unresolved-entity rate, fallback indicator."
Success criterion: "a degraded graph provably reduces the confidence of
any gap conclusion derived from it -- not silently treated as
equal-quality to a clean build."

Pure scoring layer over pipeline/graph_builder.py's build_knowledge_graph()
output -- no new extraction, no LLM call. `used_fallback` already existed
there (Story 1.3/B13); this module is what turns it, plus the graph's own
shape, into the full FR-7 metric set and an actual confidence effect.

Honest by construction, same convention as pipeline/corpus_quality.py:
`evidence_coverage` here is a proxy (fraction of relationships carrying a
non-empty free-text `evidence` field) because pipeline/graph_builder.py's
relationships do not yet reference real Evidence Object IDs
(05-data-architecture.md §8's stated target, satisfied for graph EDGES
only once relationships carry an evidence_id, which they do not today) --
a named gap, not hidden.
"""
import re

# Tuning parameter, Phase 3 -- same "not fixed in planning, calibrate
# against real runs" status as pipeline/corpus_quality.py's own thresholds.
DEGRADED_QUALITY_THRESHOLD = 0.5

# A fallback graph (pipeline/graph_builder.py's _fallback_graph_from_wiki)
# has zero real LLM relationship reasoning -- only deterministic
# wiki-field "mentions" edges -- so it is scored on the same arithmetic
# but at a fixed penalty, not just wherever the raw signals land, since
# it is a different KIND of build, not merely a lower-quality one.
_FALLBACK_SCORE_PENALTY = 0.5

_CONFIDENCE_ORDER = ["low", "medium", "high"]


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _resolve_ref(ref: str, entity_by_id: dict, entity_by_name: dict):
    if ref in entity_by_id:
        return entity_by_id[ref]
    return entity_by_name.get(_normalize_name(str(ref)))


def score_graph_quality(graph: dict, wiki: dict | None = None) -> dict:
    """`graph` is build_knowledge_graph()'s return dict. `wiki` is the
    pipeline.wiki_compiler.build_wiki() output the graph was built from
    -- optional; extraction_coverage is honestly 0.0 without it rather
    than guessed."""
    entities = graph.get("entities", []) or []
    relationships = graph.get("relationships", []) or []
    diagnostics = graph.get("diagnostics", {}) or {}
    used_fallback = bool(diagnostics.get("used_fallback"))

    entity_by_id = {e.get("id", ""): e for e in entities if e.get("id")}
    entity_by_name = {_normalize_name(e.get("name", "")): e for e in entities if e.get("name")}

    # duplicate_rate: entities sharing a normalized name with an earlier
    # entity -- the LLM extracted the same real-world concept twice under
    # different ids/casing/whitespace. Entities with no name cannot be
    # duplicates, so the rate is over named entities only.
    seen_names = set()
    duplicate_count = 0
    named_count = 0
    for e in entities:
        norm = _normalize_name(e.get("name", ""))
        if not norm:
            continue
        named_count += 1
        if norm in seen_names:
            duplicate_count += 1
        else:
            seen_names.add(norm)
    duplicate_rate = round(duplicate_count / named_count, 3) if named_count else 0.0

    # unresolved_entity_rate: relationships whose source/target don't
    # resolve to any real entity by id OR normalized name -- the same
    # dual-lookup convention pipeline/graph_builder.py's
    # find_orphan_concepts() and pipeline/graph_persistence.py's
    # save/load already use.
    unresolved_count = 0
    for rel in relationships:
        src_ok = _resolve_ref(rel.get("source", ""), entity_by_id, entity_by_name) is not None
        tgt_ok = _resolve_ref(rel.get("target", ""), entity_by_id, entity_by_name) is not None
        if not (src_ok and tgt_ok):
            unresolved_count += 1
    unresolved_entity_rate = round(unresolved_count / len(relationships), 3) if relationships else 0.0

    # evidence_coverage: proxy, see module docstring.
    with_evidence = sum(1 for r in relationships if str(r.get("evidence", "")).strip())
    evidence_coverage = round(with_evidence / len(relationships), 3) if relationships else 0.0

    # extraction_coverage: fraction of corpus papers that appear in at
    # least one entity's `papers` list -- i.e. the graph actually
    # represents them, not just that wiki_compiler processed them.
    if wiki:
        paper_titles = [
            _normalize_name(p.get("title") or p.get("source_file") or p.get("filename") or "")
            for p in wiki.get("pages", [])
        ]
        paper_titles = [t for t in paper_titles if t]
    else:
        paper_titles = []
    if paper_titles:
        represented = {_normalize_name(p) for e in entities for p in e.get("papers", [])}
        extraction_coverage = round(sum(1 for t in paper_titles if t in represented) / len(paper_titles), 3)
    else:
        extraction_coverage = 0.0

    signals = [extraction_coverage, evidence_coverage, 1 - duplicate_rate, 1 - unresolved_entity_rate]
    raw_score = sum(signals) / len(signals)
    quality_score = round(raw_score * _FALLBACK_SCORE_PENALTY, 3) if used_fallback else round(raw_score, 3)

    if used_fallback:
        build_status = "FALLBACK"
    elif quality_score < DEGRADED_QUALITY_THRESHOLD:
        build_status = "DEGRADED"
    else:
        build_status = "CLEAN"

    return {
        "build_status": build_status,
        "quality_score": quality_score,
        "extraction_coverage": extraction_coverage,
        "evidence_coverage": evidence_coverage,
        "duplicate_rate": duplicate_rate,
        "unresolved_entity_rate": unresolved_entity_rate,
        "fallback_indicator": used_fallback,
        "entity_count": len(entities),
        "relationship_count": len(relationships),
    }


def apply_graph_quality_to_gaps(gaps: list[dict], graph_quality: dict) -> list[dict]:
    """FR-7's success criterion, made real: a DEGRADED or FALLBACK graph
    build downgrades the confidence of gaps whose entire evidentiary
    basis IS that graph -- source == "graph_structural"
    (pipeline/graph_structural_gaps.py). Other sources (the deterministic
    pattern library, semantic LLM reasoning) are untouched here: a
    graph-quality problem isn't their failure mode in the same direct
    way. FALLBACK caps confidence at "low" outright (the graph has zero
    real LLM-reasoned relationships, only deterministic wiki-mention
    edges -- there's no "medium-confidence" version of that). DEGRADED
    downgrades by one level."""
    status = graph_quality.get("build_status")
    if status not in ("DEGRADED", "FALLBACK"):
        return gaps

    result = []
    for g in gaps:
        g = dict(g)
        if g.get("source") == "graph_structural":
            current = g.get("confidence", "medium")
            if status == "FALLBACK":
                new_conf = "low"
            else:
                idx = _CONFIDENCE_ORDER.index(current) if current in _CONFIDENCE_ORDER else 1
                new_conf = _CONFIDENCE_ORDER[max(0, idx - 1)]
            if new_conf != current:
                g["confidence"] = new_conf
                g["confidence_caveat"] = (
                    f"Downgraded from '{current}' to '{new_conf}' -- derived from a "
                    f"{status.lower()} knowledge-graph build "
                    f"(quality_score={graph_quality.get('quality_score')})."
                )
        result.append(g)
    return result
