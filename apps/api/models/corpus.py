from pydantic import BaseModel

from apps.api.models.common import Measure, RunRef, StatusChip
from apps.api.models.runs import PaperRef


class ReferenceFunnelStage(BaseModel):
    key: str
    label: str
    count: int


class CorpusView(BaseModel):
    project_id: str
    basis_run: RunRef | None
    basis_note: str
    papers: list[PaperRef]
    corpus_confidence: Measure
    quality_gate: StatusChip | None
    quality_gate_reasons: list[str]
    reference_funnel: list[ReferenceFunnelStage]
    doi_resolution_rate: float | None
    abstract_availability: float | None
    empty_reason: str | None = None
