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


class PaperSection(BaseModel):
    heading: str
    text: str


class PaperTable(BaseModel):
    page: int
    content: str
    rows: int
    cols: int


class PaperDetail(BaseModel):
    """The real per-paper LLM "wiki" (pipeline/wiki_compiler.py) plus the
    raw parsed sections/tables -- computed for every paper on every run but,
    until now, never surfaced past a one-line title/char_count row on the
    Corpus list."""
    filename: str
    project_id: str
    basis_run: RunRef | None
    title: str | None
    year: str | None
    domain: str | None
    char_count: int
    contributions: list[str]
    methods: list[str]
    datasets: list[str]
    key_findings: list[str]
    limitations: list[str]
    future_work: list[str]
    key_concepts: list[str]
    evaluated_on: list[str]
    comparison_gap: str | None
    tree_summary: str | None
    sections: list[PaperSection]
    tables: list[PaperTable]
