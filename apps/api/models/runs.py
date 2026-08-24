from datetime import date, datetime

from pydantic import BaseModel

from apps.api.models.common import CountStat, Measure, StatusChip, VersionField


class RunSummary(BaseModel):
    run_id: str
    name: str
    created_at: str
    project_id: str
    n_papers: int
    n_gaps: int
    n_proposals: int
    status: StatusChip
    versions: list[VersionField]
    duration_seconds: float | None
    token_usage_total: int | None
    quality_gates: list[StatusChip]


class RunListResponse(BaseModel):
    runs: list[RunSummary]
    empty_reason: str | None = None


class PaperRef(BaseModel):
    filename: str
    title: str | None
    char_count: int


class TraceStep(BaseModel):
    index: int
    stage: str
    inputs: str
    outputs: str
    status: StatusChip


class GapSummary(BaseModel):
    gap_id: str | None
    title: str
    source: str | None
    evidence_basis: str | None
    validation: StatusChip
    challenge: StatusChip
    confidence: Measure


class ProposalSummary(BaseModel):
    title: str
    addresses_gap_id: str | None
    addresses_gap_id_resolution: str | None


class TokenUsageView(BaseModel):
    recorded: bool
    total: int | None = None
    n_calls_recorded: int | None = None
    by_stage: dict[str, int] | None = None
    by_agent: dict[str, int] | None = None
    by_model: dict[str, int] | None = None
    note: str | None = None


class RunManifestView(BaseModel):
    run_id: str
    project_id: str
    versions: list[VersionField]
    quality_gates: list[StatusChip]
    token_usage: TokenUsageView
    output_artifacts: list[str]
    search_providers: list[str]
    academic_search_date: date | None
    parser_versions: dict[str, str | None]
    run_duration_seconds: float | None
    warnings: list[str]
    created_at: datetime | None


class RunDetail(BaseModel):
    run_id: str
    name: str
    created_at: str
    project_id: str
    status: StatusChip
    counts: list[CountStat]
    confidence: list[Measure]
    versions: list[VersionField]
    manifest: RunManifestView | None
    trace: list[TraceStep]
    papers: list[PaperRef]
    gaps: list[GapSummary]
    proposals: list[ProposalSummary]
    warnings: list[str]
    gate_blocked: bool
    gate_block_reasons: list[str]
