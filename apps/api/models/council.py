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


class SensitivityDriver(BaseModel):
    parameter: str
    importance: float


class ModelRunView(BaseModel):
    """One algorithm's real output from pipeline/simulation_engine.py's
    run_all_applicable() -- e.g. Monte Carlo, Markov Chain, Bootstrap.
    `metrics_by_scenario` is scenario -> metric label -> value, parsed
    once here (server-side) from the pipeline's `{scenario}_{metric}`
    headline_numbers keys, so the frontend never has to decode an
    encoded key string itself."""
    model_key: str
    model_used: str
    metrics_by_scenario: dict[str, dict[str, float | int | str]]


class ResearchCouncilView(BaseModel):
    # Named basis_run, not run, to match CorpusView/QualityView/
    # ProjectDashboard/WorkspaceHeader. Four models called the same concept
    # "run" and four called it "basis_run", so no caller could rely on either
    # -- found when one test tried to assert the field across all of them.
    basis_run: RunRef | None
    basis_note: str
    params_summary: list[CountStat]
    n_excluded_low_confidence: int
    model_selection: ModelSelectionView | None
    scenarios_run: list[str]
    models_run: list[ModelRunView]
    sensitivity_ranking: list[SensitivityDriver]
    novel_finding: NovelFindingView | None
    clinical_insights: list[str]
    research_insights: list[str]
    key_uncertainties: list[str]
    actionable_next_steps: list[str]
    limitations: list[str]
    overall_confidence: str | None
    insight_agents: list[CouncilAgentResponse]
    empty_reason: str | None = None
