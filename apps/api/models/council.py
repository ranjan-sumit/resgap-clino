from pydantic import BaseModel

from apps.api.models.common import CountStat, RunRef


class NovelFindingView(BaseModel):
    title: str
    claim: str
    what_makes_it_new: str
    evidence_chain: list[str]
    mechanism: str
    validation_study: str
    clinical_opportunity: str
    commercial_opportunity: str
    confidence: str
    confidence_reasoning: str


class CouncilAgentResponse(BaseModel):
    agent: str
    role: str
    model: str
    response: str


class ModelSelectionView(BaseModel):
    selected_model: str | None
    rationale: str | None
    confidence: str | None


class ResearchCouncilView(BaseModel):
    run: RunRef | None
    basis_note: str
    params_summary: list[CountStat]
    model_selection: ModelSelectionView | None
    novel_finding: NovelFindingView | None
    clinical_insights: list[str]
    research_insights: list[str]
    key_uncertainties: list[str]
    actionable_next_steps: list[str]
    limitations: list[str]
    overall_confidence: str | None
    insight_agents: list[CouncilAgentResponse]
    sim_headline_numbers: dict[str, float | int | str]
    empty_reason: str | None = None
