from pydantic import BaseModel

from apps.api.models.common import Measure, RunRef, StatusChip
from apps.api.models.corpus import ReferenceFunnelStage


class TrustStatusCount(BaseModel):
    """One of ADR-007's five reference-resolution trust statuses.

    Carries a full `StatusChip` rather than a bare `tone` string: a raw tone
    would be a bare color crossing the API boundary, which is the thing
    common.py exists to prevent, and it would also force the semantic color
    classes outside status-badge.tsx, the one place the UX spec allows them.
    The chip's `reason` is the status's definition -- "QUARANTINED: 1" means
    nothing to a reader who does not already know the resolution model.

    `recorded=False` distinguishes a status the resolver never emitted for
    this run from one it emitted zero times -- REJECTED, for instance, has
    no code path yet, so reporting it as a flat 0 alongside a genuine
    "QUARANTINED: 0" would claim a screening result that never happened.
    """
    status: StatusChip
    count: int
    recorded: bool


class PaperReferenceDiagnostic(BaseModel):
    filename: str
    raw_entries: int
    structured_entries: int
    combined_entries: int
    dois: int
    note: str | None = None


class FieldStatus(BaseModel):
    field: str
    status: str          # present | empty | not_extracted
    label: str
    confidence: str
    source: str | None = None
    reason: str | None = None


class PaperCompleteness(BaseModel):
    filename: str
    present_count: int
    total_fields: int
    achievable_field_count: int
    completeness_score: float
    achievable_completeness_score: float
    fields: list[FieldStatus]


class QualityView(BaseModel):
    project_id: str
    basis_run: RunRef | None
    basis_note: str
    quality_gate: StatusChip | None
    quality_gate_reasons: list[str]
    measures: list[Measure]
    reference_funnel: list[ReferenceFunnelStage]
    funnel_note: str | None = None
    trust_statuses: list[TrustStatusCount]
    trust_note: str | None = None
    duplicates_removed: int | None = None
    per_paper_references: list[PaperReferenceDiagnostic]
    per_paper_completeness: list[PaperCompleteness]
    completeness_absent_reason: str | None = None
    empty_reason: str | None = None
