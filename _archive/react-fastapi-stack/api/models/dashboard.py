from pydantic import BaseModel

from apps.api.models.common import CountStat, Measure, RunRef, StatusChip
from apps.api.models.runs import RunSummary


class ProjectSummary(BaseModel):
    project_id: str
    label: str
    n_runs: int


class LinkedRef(BaseModel):
    """A cross-screen link resolved server-side. `href` is None when the
    referenced thing exists in the data but has no screen of its own to
    point at -- shown as plain text rather than a dead link."""
    label: str
    href: str | None = None


class GapOpportunity(BaseModel):
    gap_id: str | None
    title: str
    source: str | None
    evidence_basis: str | None
    validation: StatusChip
    challenge: StatusChip
    confidence: Measure
    run_id: str
    # Cross-links (Epic 5.7): the papers this gap was derived from, and the
    # proposals that address it -- previously present in the data but never
    # navigable, which is why every screen felt like an island.
    supporting_papers: list[LinkedRef] = []
    proposals: list[LinkedRef] = []


class ActivityEvent(BaseModel):
    timestamp: str
    kind: str  # "run" | "artifact"
    title: str
    detail: str
    href: str


class RunDelta(BaseModel):
    """What changed between the previous run and the current one. Built from
    pipeline/run_compare.py -- the same function the Compare screen uses, so
    the two can never disagree about what changed."""
    previous_run: RunRef
    current_run: RunRef
    gaps_added: list[str] = []
    gaps_removed: list[str] = []
    papers_added: list[str] = []
    papers_removed: list[str] = []
    entities_added_count: int = 0
    entities_removed_count: int = 0
    evidence_delta: int = 0
    proposals_added_count: int = 0
    proposals_removed_count: int = 0
    compare_href: str
    unchanged: bool = False


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
    delta: RunDelta | None = None
    empty_reason: str | None


class WorkspaceHeader(BaseModel):
    """Just what the workspace's header strip shows, above its tab bar.

    The workspace first reused ProjectDashboard, which measures ~14.7s:
    `recent_runs` rebuilds a full RunSummary per run (a load_run plus a
    manifest read each) and `delta` runs a whole compare_runs. The workspace
    renders none of those four fields, so it was paying ~13s for data it
    discarded -- on the app's primary screen, before any tab content.
    """
    project_id: str
    project_label: str
    basis_run: RunRef | None
    basis_note: str
    counts: list[CountStat]
    confidence: list[Measure]
    empty_reason: str | None = None
