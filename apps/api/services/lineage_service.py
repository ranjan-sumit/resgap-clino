"""
Shapes pipeline/lineage.py's real query-time traversals into the
Lineage screen's response models (Clinova Phase 5, Epic 5.1). Mirrors
pipeline/lineage.py's own documented spine order for stage_index rather
than re-deriving it -- that ordering is pipeline business logic and must
not leak into React.
"""
from apps.api.models.common import StatusChip
from apps.api.models.lineage import (
    EntityRef, EvidenceRef, GapChain, LineageEdge, LineageNode, ProposalRef,
    RelationshipRef, ScientificLineage, TechnicalLineage, UnresolvedRefs,
)
from apps.api.services.runs_service import _CHALLENGE_CHIPS, _NOT_CHALLENGED_CHIP
from pipeline.lineage import get_scientific_lineage, get_technical_lineage

_STAGE_ORDER = {
    "corpus": 0, "paper_extraction": 1, "reference_set": 1,
    "evidence_set": 2, "graph": 3, "gap_set": 4, "proposal_set": 5,
    "pipeline": 6,
}

_ARTIFACT_STATUS_CHIPS = {
    "EXPERIMENTAL": StatusChip(code="EXPERIMENTAL", label="Experimental", tone="neutral", icon="circle-dashed",
                                reason="Freshly produced by a run, not yet evaluated against the benchmark."),
    "CANDIDATE": StatusChip(code="CANDIDATE", label="Candidate", tone="caution", icon="alert-triangle",
                             reason="Passed the evaluation harness; eligible for champion/challenger comparison."),
    "CHAMPION": StatusChip(code="CHAMPION", label="Champion", tone="positive", icon="shield-check",
                            reason="Currently the promoted, production-default version for its artifact type."),
    "ARCHIVED": StatusChip(code="ARCHIVED", label="Archived", tone="neutral", icon="circle-dashed",
                            reason="Superseded by a later champion; retained for lineage and reproducibility."),
}
_UNKNOWN_ARTIFACT_STATUS = StatusChip(code="UNKNOWN", label="Unknown", tone="unknown", icon="help-circle",
                                       reason="No recognized artifact status.")


def _humanize_type(artifact_type: str) -> str:
    return artifact_type.replace("_", " ").title()


def get_technical_lineage_view(run_id: str) -> TechnicalLineage:
    raw = get_technical_lineage(run_id)
    nodes = [
        LineageNode(
            artifact_id=n["artifact_id"], artifact_type=n["artifact_type"],
            label=f"{_humanize_type(n['artifact_type'])} · {n['artifact_id'].split(':')[-1][:8]}",
            status=_ARTIFACT_STATUS_CHIPS.get(n["status"], _UNKNOWN_ARTIFACT_STATUS),
            stage_index=_STAGE_ORDER.get(n["artifact_type"], 99),
            metadata=n.get("metadata"),
        )
        for n in raw["nodes"]
    ]
    edges = [LineageEdge(parent=e["parent"], child=e["child"], kind="primary") for e in raw["edges"]]
    fan_in_edges = [LineageEdge(parent=e["parent"], child=e["child"], kind="contributing")
                     for e in raw["fan_in_edges"]]
    orphan_note = (f"{len(raw['orphans'])} artifact(s) reference a parent outside this run's "
                   f"artifact set.") if raw["orphans"] else None

    truncated_after = None
    for n in raw["nodes"]:
        reason = (n.get("metadata") or {}).get("chain_truncated_reason")
        if reason:
            truncated_after = f"{n['artifact_id']}: {reason}"
            break

    return TechnicalLineage(
        run_id=run_id, root=raw["root"], nodes=nodes, edges=edges, fan_in_edges=fan_in_edges,
        orphans=raw["orphans"], orphan_note=orphan_note, truncated_after=truncated_after,
    )


def _evidence_ref(e: dict) -> EvidenceRef:
    provenance = e.get("provenance") or {}
    text = e.get("text") or ""
    return EvidenceRef(
        evidence_id=e.get("evidence_id"), text=text[:240] + ("…" if len(text) > 240 else ""),
        paper_id=e.get("paper_id"), page=provenance.get("page"), section=provenance.get("section"),
        confidence=e.get("confidence"),
    )


def _relationship_ref(r: dict) -> RelationshipRef:
    return RelationshipRef(relationship_id=r.get("relationship_id"), source=r.get("source"),
                            target=r.get("target"), relation=r.get("relation"), paper=r.get("paper"))


def _entity_ref(e: dict) -> EntityRef:
    return EntityRef(id=e.get("id"), name=e.get("name"), type=e.get("type"))


def get_scientific_lineage_view(run_id: str, gap_id: str | None = None) -> ScientificLineage:
    raw = get_scientific_lineage(run_id, gap_id=gap_id)
    gaps = []
    for g in raw["gaps"]:
        c = g["chain"]
        u = g["unresolved"]
        n_unresolved = (len(u["evidence_ids_not_found"]) + len(u["relationship_ids_not_found"])
                        + len(u["entity_ids_not_found"]))
        challenge_status = (c.get("challenge") or {}).get("challenger_status")
        gaps.append(GapChain(
            gap_id=g["gap_id"], title=g["title"], source=g["source"], evidence_basis=g["evidence_basis"],
            evidence=[_evidence_ref(e) for e in c["evidence"]],
            relationships=[_relationship_ref(r) for r in c["relationships"]],
            entities=[_entity_ref(e) for e in c["entities"]],
            challenge=_CHALLENGE_CHIPS.get(challenge_status, _NOT_CHALLENGED_CHIP),
            proposals=[ProposalRef(title=p.get("title", "")) for p in c["proposals"]],
            unresolved=UnresolvedRefs(**u),
            unresolved_note=(f"{n_unresolved} motivating id(s) could not be resolved in this "
                              f"run's saved data.") if n_unresolved else None,
        ))

    identity_note = (f"{raw['n_gaps_without_identity']} gap(s) on this run have no real gap_id "
                      f"(predates Epic 4.4's identity fields) and are excluded above."
                      ) if raw["n_gaps_without_identity"] else None

    return ScientificLineage(
        run_id=run_id, gaps=gaps, n_gaps_without_identity=raw["n_gaps_without_identity"],
        identity_note=identity_note,
    )
