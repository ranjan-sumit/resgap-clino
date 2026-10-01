from pydantic import BaseModel

from apps.api.models.common import CountStat, Measure, RunRef


class GraphEntityView(BaseModel):
    id: str
    name: str
    type: str
    papers: list[str]
    importance: str


class GraphRelationshipView(BaseModel):
    source: str
    target: str
    relation: str
    paper: str | None
    evidence: str | None


class GraphCommunityView(BaseModel):
    id: str
    theme: str
    entities: list[str]
    summary: str
    gap_signal: str | None


class GraphView(BaseModel):
    # Named basis_run, not run, to match CorpusView/QualityView/
    # ProjectDashboard/WorkspaceHeader. Four models called the same concept
    # "run" and four called it "basis_run", so no caller could rely on either
    # -- found when one test tried to assert the field across all of them.
    basis_run: RunRef | None
    basis_note: str
    entities: list[GraphEntityView]
    relationships: list[GraphRelationshipView]
    communities: list[GraphCommunityView]
    counts: list[CountStat]
    confidence: Measure
    empty_reason: str | None = None
