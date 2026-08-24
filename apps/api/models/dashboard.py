from pydantic import BaseModel

from apps.api.models.common import CountStat, Measure, RunRef, StatusChip
from apps.api.models.runs import RunSummary


class ProjectSummary(BaseModel):
    project_id: str
    label: str
    n_runs: int


class GapOpportunity(BaseModel):
    gap_id: str | None
    title: str
    source: str | None
    evidence_basis: str | None
    validation: StatusChip
    challenge: StatusChip
    confidence: Measure
    run_id: str


class ActivityEvent(BaseModel):
    timestamp: str
    kind: str  # "run" | "artifact"
    title: str
    detail: str
    href: str


class ProjectDashboard(BaseModel):
    project_id: str
    project_label: str
    basis_run: RunRef | None
    basis_note: str
    counts: list[CountStat]
    confidence: list[Measure]
    recent_runs: list[RunSummary]
    top_opportunities: list[GapOpportunity]
    n_excluded_insufficient_evidence: int
    activity: list[ActivityEvent]
    empty_reason: str | None
