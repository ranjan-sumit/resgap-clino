"""
Knowledge Graph screen (Clinova Phase 5, Epic 5.3). Reads results["graph"]
directly -- pipeline/graph_builder.py::build_knowledge_graph()'s own real
output shape (entities/relationships/communities/stats), the same structure
graph_confidence() and pipeline/graph_structural_gaps.py already consume.
"""
from apps.api.models.common import CountStat, RunRef
from apps.api.models.graph import GraphCommunityView, GraphEntityView, GraphRelationshipView, GraphView
from apps.api.services.measures import graph_confidence
from apps.api.services.project_runs import get_basis_run


def get_project_graph(project_id: str) -> GraphView:
    basis_row, results = get_basis_run(project_id)
    if basis_row is None:
        return GraphView(
            run=None, basis_note="No runs exist for this project yet.", entities=[], relationships=[],
            communities=[], counts=[], confidence=graph_confidence({}),
            empty_reason="No runs in this project yet. Runs created in the Streamlit "
                          "workspace appear here automatically.",
        )

    run = RunRef(run_id=basis_row["id"], name=basis_row["name"], created_at=str(basis_row["created_at"]))
    basis_note = f"Graph reflects run \"{basis_row['name']}\" ({basis_row['id'][:8]}) — the most recent run in this project."

    graph = results.get("graph") or {}
    entities = [
        GraphEntityView(id=e.get("id", ""), name=e.get("name", ""), type=e.get("type", "concept"),
                          papers=e.get("papers") or [], importance=e.get("importance", "medium"))
        for e in graph.get("entities") or []
    ]
    relationships = [
        GraphRelationshipView(source=r.get("source", ""), target=r.get("target", ""),
                                relation=r.get("relation", ""), paper=r.get("paper"), evidence=r.get("evidence"))
        for r in graph.get("relationships") or []
    ]
    communities = [
        GraphCommunityView(id=c.get("id", ""), theme=c.get("theme", ""), entities=c.get("entities") or [],
                             summary=c.get("summary", ""), gap_signal=c.get("gap_signal"))
        for c in graph.get("communities") or []
    ]
    stats = graph.get("stats") or {}
    counts = [
        CountStat(key="entities", label="Entities", value=stats.get("entity_count", 0),
                   display=f"{stats.get('entity_count', 0):,}", recorded=True, source="results.graph.stats"),
        CountStat(key="relationships", label="Relationships", value=stats.get("relationship_count", 0),
                   display=f"{stats.get('relationship_count', 0):,}", recorded=True, source="results.graph.stats"),
        CountStat(key="communities", label="Communities", value=stats.get("community_count", 0),
                   display=f"{stats.get('community_count', 0):,}", recorded=True, source="results.graph.stats"),
        CountStat(key="orphans", label="Orphan Concepts", value=stats.get("orphan_count", 0),
                   display=f"{stats.get('orphan_count', 0):,}", recorded=True, source="results.graph.stats"),
        CountStat(key="bridges", label="Missing Bridges", value=stats.get("bridge_count", 0),
                   display=f"{stats.get('bridge_count', 0):,}", recorded=True, source="results.graph.stats"),
    ]

    empty_reason = None
    if not entities:
        empty_reason = "No knowledge graph was built for this run."

    return GraphView(
        run=run, basis_note=basis_note, entities=entities, relationships=relationships,
        communities=communities, counts=counts, confidence=graph_confidence(results), empty_reason=empty_reason,
    )
