from pydantic import BaseModel


class TraceRow(BaseModel):
    stage: str
    inputs: str
    outputs: str


class RunJobView(BaseModel):
    job_id: str
    name: str
    project_id: str
    state: str                       # queued | running | succeeded | failed
    percent: int
    message: str
    trace: list[TraceRow]
    warnings: list[str]
    run_id: str | None = None
    error: str | None = None
    gate_blocked: bool = False
    gate_block_reasons: list[str] = []
    n_gaps: int = 0
    n_proposals: int = 0
    started_at: str
    finished_at: str | None = None


class ProviderOption(BaseModel):
    key: str
    label: str
    default_model: str
    models: list[str]
    api_key_env: str
    api_key_present: bool


class NewRunConfig(BaseModel):
    """Everything the New Run screen needs to render honest, real choices --
    including which providers actually have a key configured, so the UI can
    disable the ones that would fail rather than letting a run start and die
    minutes later."""
    providers: list[ProviderOption]
    default_provider: str
    domains: list[str]
    default_domain: str
    min_papers: int
    max_papers: int
    jobs_are_in_process: bool = True
    jobs_note: str
