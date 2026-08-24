"""
Lineage Views (Clinova Phase 4, Epic 4.4, FR-24). Two distinct views, per
06-versioning-lineage-architecture.md §4:

- Technical lineage: PDF -> parser -> evidence -> graph -> gap -> proposal.
  A real query over research_artifacts.parent_artifact -- this module
  WRITES that chain (record_run_lineage(), called once per pipeline run)
  and READS it back (get_technical_lineage()).
- Scientific lineage: paper -> evidence -> relationship -> gap -> challenge
  -> proposal. A pure in-memory join over one run's already-saved
  results (load_run()) -- no new table, since the scientific chain is
  already fully persisted in runs.results_json. Depends on the id fields
  (relationship_id, gap_id, motivating_evidence_ids) added to
  graph_builder.py/gap_detector.py/deterministic_gap_patterns.py/
  graph_structural_gaps.py/proposal_generator.py.

Fan-in design: research_artifacts.parent_artifact is a single-valued,
DB-enforced foreign key -- not a multi-parent DAG edge table. N per-paper
paper_extraction artifacts cannot each be "the" parent of one graph
artifact. Resolved with one corpus-level join spine per run: every
paper_extraction's parent is the run's single corpus artifact (fan-out,
no problem), and the true N->1 fan-in point (evidence_set, matching Stage
2's wiki + Stage 2C's evidence_objects, both already corpus-wide) records
its real contributing parents in metadata[PARENTS_METADATA_KEY] --
additive, never replacing the strict single-parent chain the FK requires.
"""
import hashlib
import json

from utils.database import get_artifact, list_artifacts, load_run, record_artifact

LINEAGE_SCHEMA_VERSION = 1
PARENTS_METADATA_KEY = "contributing_parents"

# The technical spine, in dependency order -- each entry's parent is the
# previous entry (except paper_extraction, which fans out from corpus,
# and reference_set, which is optional and also parents from corpus).
_SPINE_ORDER = ["corpus", "evidence_set", "graph", "gap_set", "proposal_set"]


def _content_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _spine_id(artifact_type: str, run_id: str, obj) -> str:
    return f"{artifact_type}:{run_id}:{_content_hash(obj)[:8]}"


def record_run_lineage(
    run_id: str, project_id: str, *,
    papers: list, wiki: dict, ref_papers: list, evidence_objects: dict,
    graph: dict | None, gaps: list | None, proposals: list | None,
    tooling: dict | None = None, gate_blocked: bool = False,
) -> dict:
    """Writes the per-run Technical Lineage spine, parent-first (the
    parent_artifact FK is enforced -- an insert referencing a not-yet-
    written parent fails). For gate-blocked runs, graph/gaps/proposals
    are None (Stage 3-6 were skipped, per app.py's own gate_blocked
    branch) -- the spine truncates after evidence_set rather than
    fabricating empty graph/gap_set/proposal_set rows.

    Returns {"artifact_ids": [...], "by_type": {type: artifact_id},
    "skipped": [...]}.
    """
    artifact_ids: list[str] = []
    by_type: dict[str, str] = {}
    skipped: list[str] = []

    corpus_content = {
        "papers": sorted(p.get("filename", "") for p in papers),
        "wiki_pages": len(wiki.get("pages", [])),
    }
    corpus_id = _spine_id("corpus", run_id, corpus_content)
    record_artifact(
        artifact_id=corpus_id, artifact_type="corpus", artifact_version=run_id,
        project_id=project_id, content_hash=_content_hash(corpus_content),
        run_id=run_id, parent_artifact=None,
        metadata={"paper_count": len(papers), "filenames": corpus_content["papers"]},
    )
    artifact_ids.append(corpus_id)
    by_type["corpus"] = corpus_id

    paper_artifact_ids = []
    for p in papers:
        filename = p.get("filename", "")
        paper_content = {"filename": filename, "char_count": p.get("char_count", 0)}
        paper_id = _spine_id("paper_extraction", run_id, paper_content)
        record_artifact(
            artifact_id=paper_id, artifact_type="paper_extraction",
            artifact_version=run_id, project_id=project_id,
            content_hash=_content_hash(paper_content), run_id=run_id,
            parent_artifact=corpus_id,
            metadata={"filename": filename, "char_count": p.get("char_count", 0)},
        )
        artifact_ids.append(paper_id)
        paper_artifact_ids.append(paper_id)
    if papers:
        by_type["paper_extraction"] = paper_artifact_ids[-1]  # representative; full list in evidence_set's metadata

    reference_set_id = None
    if ref_papers:
        ref_content = {"count": len(ref_papers)}
        reference_set_id = _spine_id("reference_set", run_id, ref_content)
        record_artifact(
            artifact_id=reference_set_id, artifact_type="reference_set",
            artifact_version=run_id, project_id=project_id,
            content_hash=_content_hash(ref_content), run_id=run_id,
            parent_artifact=corpus_id, metadata={"reference_count": len(ref_papers)},
        )
        artifact_ids.append(reference_set_id)
        by_type["reference_set"] = reference_set_id

    evidence_content = {
        "wiki_content_hash": _content_hash(wiki),
        "per_paper_evidence_counts": {k: len(v) for k, v in evidence_objects.items()},
    }
    evidence_set_id = _spine_id("evidence_set", run_id, evidence_content)
    evidence_metadata = {
        PARENTS_METADATA_KEY: paper_artifact_ids,
        "per_paper_evidence_counts": evidence_content["per_paper_evidence_counts"],
        "wiki_content_hash": evidence_content["wiki_content_hash"],
        "docling_provenance": any(
            (e.get("provenance") or {}).get("page") is not None
            for objs in evidence_objects.values() for e in objs
        ),
    }
    if tooling:
        evidence_metadata["tooling_artifacts"] = {
            k: v for k, v in tooling.items() if v is not None
        }
    if gate_blocked or graph is None:
        evidence_metadata["chain_truncated_reason"] = (
            "quality gate FAIL -- stages 3-6 skipped" if gate_blocked else "no graph produced"
        )
    record_artifact(
        artifact_id=evidence_set_id, artifact_type="evidence_set",
        artifact_version=run_id, project_id=project_id,
        content_hash=_content_hash(evidence_content), run_id=run_id,
        parent_artifact=corpus_id, metadata=evidence_metadata,
    )
    artifact_ids.append(evidence_set_id)
    by_type["evidence_set"] = evidence_set_id

    if gate_blocked or graph is None:
        skipped = ["graph", "gap_set", "proposal_set"]
        return {"artifact_ids": artifact_ids, "by_type": by_type, "skipped": skipped}

    graph_content = {
        "entity_count": graph.get("stats", {}).get("entity_count", 0),
        "relationship_count": graph.get("stats", {}).get("relationship_count", 0),
        "entities": sorted(e.get("id", "") for e in graph.get("entities", [])),
    }
    graph_id = _spine_id("graph", run_id, graph_content)
    record_artifact(
        artifact_id=graph_id, artifact_type="graph", artifact_version=run_id,
        project_id=project_id, content_hash=_content_hash(graph_content),
        run_id=run_id, parent_artifact=evidence_set_id,
        metadata={
            "entity_count": graph_content["entity_count"],
            "relationship_count": graph_content["relationship_count"],
            "used_fallback": graph.get("diagnostics", {}).get("used_fallback"),
        },
    )
    artifact_ids.append(graph_id)
    by_type["graph"] = graph_id

    gaps = gaps or []
    gap_content = {"gap_ids": sorted(g.get("gap_id", "") for g in gaps if g.get("gap_id"))}
    gap_set_id = _spine_id("gap_set", run_id, gap_content)
    record_artifact(
        artifact_id=gap_set_id, artifact_type="gap_set", artifact_version=run_id,
        project_id=project_id, content_hash=_content_hash(gap_content),
        run_id=run_id, parent_artifact=graph_id,
        metadata={"gap_count": len(gaps), "gap_ids": gap_content["gap_ids"]},
    )
    artifact_ids.append(gap_set_id)
    by_type["gap_set"] = gap_set_id

    proposals = proposals or []
    proposal_content = {"count": len(proposals), "titles": sorted(p.get("title", "") for p in proposals)}
    proposal_set_id = _spine_id("proposal_set", run_id, proposal_content)
    record_artifact(
        artifact_id=proposal_set_id, artifact_type="proposal_set",
        artifact_version=run_id, project_id=project_id,
        content_hash=_content_hash(proposal_content), run_id=run_id,
        parent_artifact=gap_set_id,
        metadata={"proposal_count": len(proposals), "pipeline_artifact": f"pipeline:{run_id}"},
    )
    artifact_ids.append(proposal_set_id)
    by_type["proposal_set"] = proposal_set_id

    return {"artifact_ids": artifact_ids, "by_type": by_type, "skipped": skipped}


def get_technical_lineage(run_id: str) -> dict:
    """Reads research_artifacts for this run and returns the spine as a
    walkable structure: {root, nodes, edges, fan_in_edges, orphans}.
    `orphans` lists any row whose parent_artifact doesn't resolve within
    this run's own artifact set -- reported, never silently dropped."""
    rows = list_artifacts(project_id=None, status=None)
    rows = [r for r in rows if r.get("run_id") == run_id]
    by_id = {r["artifact_id"]: r for r in rows}

    edges = []
    fan_in_edges = []
    orphans = []
    root = None
    for r in rows:
        parent = r.get("parent_artifact")
        if parent is None:
            if r["artifact_type"] == "corpus":
                root = r["artifact_id"]
            continue
        if parent in by_id:
            edges.append({"parent": parent, "child": r["artifact_id"], "type": r["artifact_type"]})
        else:
            orphans.append(r["artifact_id"])
        contributing = (r.get("metadata") or {}).get(PARENTS_METADATA_KEY)
        if contributing:
            for cp in contributing:
                fan_in_edges.append({"parent": cp, "child": r["artifact_id"]})

    return {
        "run_id": run_id, "root": root,
        "nodes": [{"artifact_id": r["artifact_id"], "artifact_type": r["artifact_type"],
                   "status": r["status"], "metadata": r.get("metadata")} for r in rows],
        "edges": edges, "fan_in_edges": fan_in_edges, "orphans": orphans,
    }


def _entity_by_id(graph: dict) -> dict:
    return {e.get("id"): e for e in graph.get("entities", []) if e.get("id")}


def _relationship_by_id(graph: dict) -> dict:
    return {r.get("relationship_id"): r for r in graph.get("relationships", []) if r.get("relationship_id")}


def _evidence_by_id(evidence_objects: dict) -> dict:
    out = {}
    for objs in evidence_objects.values():
        for e in objs:
            eid = e.get("evidence_id")
            if eid:
                out[eid] = e
    return out


def get_scientific_lineage(run_id: str, gap_id: str | None = None) -> dict:
    """Pure in-memory join over one run's already-saved results (no new
    table, no migration -- the scientific chain is already fully
    persisted in runs.results_json). For each gap (or just `gap_id` if
    given), resolves motivating_evidence_ids/motivating_relationship_ids/
    motivating_entity_ids against the run's real id sets and reports any
    that don't resolve in `unresolved` -- a dangling id is reported, never
    silently dropped.

    Gaps with no real gap_id (a run that predates Epic 4.4's identity
    fields) cannot be meaningfully traced -- they are excluded from
    `gaps` and counted in `n_gaps_without_identity` instead of being
    rendered with a fabricated/None identity."""
    loaded = load_run(run_id)
    if not loaded:
        raise ValueError(f"Run '{run_id}' was not found -- cannot trace lineage.")
    results = loaded.get("results", {}) or {}

    graph = results.get("graph", {}) or {}
    evidence_objects = results.get("evidence_objects", {}) or {}
    all_gaps = results.get("gaps", []) or []
    proposals = results.get("proposals", []) or []

    entity_index = _entity_by_id(graph)
    relationship_index = _relationship_by_id(graph)
    evidence_index = _evidence_by_id(evidence_objects)

    n_gaps_without_identity = sum(1 for g in all_gaps if not g.get("gap_id"))
    gaps = [g for g in all_gaps if g.get("gap_id")]

    if gap_id is not None:
        gaps = [g for g in gaps if g.get("gap_id") == gap_id]

    chains = []
    for g in gaps:
        this_gap_id = g.get("gap_id")
        motivating_evidence = g.get("motivating_evidence_ids", []) or []
        motivating_relationships = g.get("motivating_relationship_ids", []) or []
        motivating_entities = g.get("motivating_entity_ids", []) or []

        resolved_evidence = [evidence_index[eid] for eid in motivating_evidence if eid in evidence_index]
        resolved_relationships = [relationship_index[rid] for rid in motivating_relationships if rid in relationship_index]
        resolved_entities = [entity_index[eid] for eid in motivating_entities if eid in entity_index]

        unresolved = {
            "evidence_ids_not_found": [eid for eid in motivating_evidence if eid not in evidence_index],
            "relationship_ids_not_found": [rid for rid in motivating_relationships if rid not in relationship_index],
            "entity_ids_not_found": [eid for eid in motivating_entities if eid not in entity_index],
        }

        matching_proposals = [
            p for p in proposals
            if p.get("addresses_gap_id") == this_gap_id
        ] if this_gap_id else []

        chains.append({
            "gap_id": this_gap_id, "title": g.get("title"), "source": g.get("source"),
            "evidence_basis": g.get("evidence_basis"),
            "chain": {
                "evidence": resolved_evidence, "relationships": resolved_relationships,
                "entities": resolved_entities, "gap": g,
                "challenge": {"challenger_status": g.get("challenger_status"),
                              "challenged_gap_id": g.get("challenged_gap_id")},
                "proposals": matching_proposals,
            },
            "unresolved": unresolved,
        })

    return {"run_id": run_id, "gaps": chains, "n_gaps_without_identity": n_gaps_without_identity}


def trace_artifact_ancestry(artifact_id: str) -> list[dict]:
    """Walks parent_artifact upward from `artifact_id` to the root.
    Returns the chain in root-first order."""
    chain = []
    current = get_artifact(artifact_id)
    seen = set()
    while current and current["artifact_id"] not in seen:
        seen.add(current["artifact_id"])
        chain.append(current)
        parent_id = current.get("parent_artifact")
        current = get_artifact(parent_id) if parent_id else None
    return list(reversed(chain))


def trace_artifact_descendants(artifact_id: str) -> list[dict]:
    """Walks parent_artifact downward from `artifact_id` within the same
    run -- descendants are any artifact (same run_id) whose ancestry
    chain passes through `artifact_id`."""
    root = get_artifact(artifact_id)
    if not root or not root.get("run_id"):
        return []
    all_in_run = [r for r in list_artifacts() if r.get("run_id") == root["run_id"]]
    by_id = {r["artifact_id"]: r for r in all_in_run}

    descendants = []
    for r in all_in_run:
        node = r
        seen = set()
        while node and node.get("parent_artifact") and node["artifact_id"] not in seen:
            seen.add(node["artifact_id"])
            if node["parent_artifact"] == artifact_id:
                descendants.append(r)
                break
            node = by_id.get(node["parent_artifact"])
    return descendants
