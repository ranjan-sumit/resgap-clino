from typing import Literal

from pydantic import BaseModel

from apps.api.models.common import RunRef, StatusChip


class MetricComparison(BaseModel):
    key: str
    label: str
    baseline: float | None
    candidate: float | None
    baseline_display: str
    candidate_display: str
    delta_pct: float | None
    direction: Literal["higher", "lower"]
    better: Literal["baseline", "candidate", "equal", "unknown"]
    verdict: str
    tolerance: float | None


class DiffSection(BaseModel):
    key: str
    label: str
    added: list[str] = []
    removed: list[str] = []
    common_count: int
    summary: str


class EvidenceDiff(BaseModel):
    count_baseline: int
    count_candidate: int
    delta: int


class GraphDiff(BaseModel):
    entities_added: list[str]
    entities_removed: list[str]
    entities_common_count: int
    relationships_added: list[list[str]]
    relationships_removed: list[list[str]]
    relationships_common_count: int


class ConfidenceChange(BaseModel):
    title: str
    confidence_baseline: str | None
    confidence_candidate: str | None
    explanation: str


class GapDiff(BaseModel):
    added: list[str]
    removed: list[str]
    common_count: int
    confidence_changes: list[ConfidenceChange]


class ManifestFieldDiff(BaseModel):
    key: str
    label: str
    baseline: str | None
    candidate: str | None
    changed: bool


class PromotionGateView(BaseModel):
    eligible: bool
    can_evaluate: bool
    hard_gate_failures: list[str]
    soft_regressions: list[str]
    warnings: list[str]
    blocking_reasons: list[str]
    status: StatusChip
    promotion_gate_version: int | None
    candidate_artifact_id: str | None


class RunComparison(BaseModel):
    baseline: RunRef
    candidate: RunRef
    metrics: list[MetricComparison]
    metrics_note: str | None
    papers: DiffSection
    evidence: EvidenceDiff
    graph: GraphDiff
    gaps: GapDiff
    proposals: DiffSection
    manifest_diff: list[ManifestFieldDiff]
    promotion: PromotionGateView
