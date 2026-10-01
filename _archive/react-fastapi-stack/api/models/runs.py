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


class RunOption(BaseModel):
    """A run as the sidebar's run switcher needs it: enough to tell runs
    apart, nothing more.

    Exists because building a RunSummary costs a full load_run() plus a
    manifest read PER RUN (it carries derived status, version fields and
    quality gates). That is right for the Runs table, which shows all of it,
    but the switcher renders in the layout on EVERY page -- serving
    RunSummary there put ~6s of JSONB loading in front of every screen in the
    app. Every field below already sits in list_runs()' own row, so this
    costs one query and zero run loads.
    """
    run_id: str
    name: str
    created_at: str
    project_id: str
    n_papers: int
    n_gaps: int


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


class LinkedRef(BaseModel):
    """A cross-screen link resolved server-side. `href` is None when the
    referenced thing genuinely exists in the data but has no screen of its
    own -- rendered as plain text instead of a link that would 404."""
    label: str
    href: str | None = None


class GapSummary(BaseModel):
    gap_id: str | None
    title: str
    source: str | None
    evidence_basis: str | None
    validation: StatusChip
    challenge: StatusChip
    confidence: Measure
    # Cross-links (Epic 5.7): the papers this gap came from and the proposals
    # that address it. Both were already in the data, just never navigable --
    # which is what made every screen feel like an island.
    supporting_papers: list[LinkedRef] = []
    proposals: list[LinkedRef] = []


class ProposalSummary(BaseModel):
    title: str
    addresses_gap_id: str | None
    addresses_gap_id_resolution: str | None
    # The gap this proposal addresses, as a navigable link (Epic 5.7). The
    # pipeline records the gap by TITLE, not id, so this is resolved by
    # normalised-title match against the run's own gaps -- href is None when
    # the named gap isn't in this run, which is real and must not 404.
    addresses_gap: LinkedRef | None = None
    problem_statement: str | None = None
    methodology: str | None = None
    novelty: str | None = None
    builds_on: list[str] = []
    expected_contribution: str | None = None
    suggested_experiments: list[str] = []
    potential_datasets: list[str] = []
    confidence: str | None = None
    effort_estimate: str | None = None
    risk: str | None = None


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
