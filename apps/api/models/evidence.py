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
    run: RunRef | None
    basis_note: str
    items: list[EvidenceItemView]
    by_type_counts: dict[str, int]
    confidence: Measure
    empty_reason: str | None = None
