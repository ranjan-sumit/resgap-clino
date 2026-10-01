from pydantic import BaseModel

from apps.api.models.common import StatusChip


class LineageNode(BaseModel):
    artifact_id: str
    artifact_type: str
    label: str
    status: StatusChip
    stage_index: int
    metadata: dict | None = None


class LineageEdge(BaseModel):
    parent: str
    child: str
    kind: str  # "primary" | "contributing"


class TechnicalLineage(BaseModel):
    run_id: str
    root: str | None
    nodes: list[LineageNode]
    edges: list[LineageEdge]
    fan_in_edges: list[LineageEdge]
    orphans: list[str]
    orphan_note: str | None
    truncated_after: str | None


class EvidenceRef(BaseModel):
    evidence_id: str | None
    text: str
    paper_id: str | None
    page: int | None
    section: str | None
    confidence: str | None


class RelationshipRef(BaseModel):
    relationship_id: str | None
    source: str | None
    target: str | None
    relation: str | None
    paper: str | None


class EntityRef(BaseModel):
    id: str | None
    name: str | None
    type: str | None


class ProposalRef(BaseModel):
    title: str


class UnresolvedRefs(BaseModel):
    evidence_ids_not_found: list[str]
    relationship_ids_not_found: list[str]
    entity_ids_not_found: list[str]


class GapChain(BaseModel):
    gap_id: str | None
    title: str | None
    source: str | None
    evidence_basis: str | None
    evidence: list[EvidenceRef]
    relationships: list[RelationshipRef]
    entities: list[EntityRef]
    challenge: StatusChip
    proposals: list[ProposalRef]
    unresolved: UnresolvedRefs
    unresolved_note: str | None


class ScientificLineage(BaseModel):
    run_id: str
    gaps: list[GapChain]
    n_gaps_without_identity: int
    identity_note: str | None
