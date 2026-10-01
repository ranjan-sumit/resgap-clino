from pydantic import BaseModel

from apps.api.models.common import Measure, RunRef


class EvidenceItemView(BaseModel):
    evidence_id: str
    evidence_type: str
    paper_filename: str
    text: str
    page: int | None
    section: str | None
    confidence: str


class EvidenceView(BaseModel):
    # Named basis_run, not run, to match CorpusView/QualityView/
    # ProjectDashboard/WorkspaceHeader. Four models called the same concept
    # "run" and four called it "basis_run", so no caller could rely on either
    # -- found when one test tried to assert the field across all of them.
    basis_run: RunRef | None
    basis_note: str
    items: list[EvidenceItemView]
    by_type_counts: dict[str, int]
    confidence: Measure
    empty_reason: str | None = None
