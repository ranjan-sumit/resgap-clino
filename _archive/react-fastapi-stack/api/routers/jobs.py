import os

from fastapi import APIRouter, File, Form, UploadFile

from apps.api.errors import NotFoundError
from apps.api.models.jobs import NewRunConfig, ProviderOption, RunJobView, TraceRow
from apps.api.services.jobs_service import get_job, list_jobs, start_run
from domain_config import DOMAINS
from pipeline.run_pipeline import MAX_PAPERS, MIN_PAPERS, PipelineInputError, RunOptions
from utils.model_providers import DEFAULT_PROVIDER_KEY, PROVIDER_REGISTRY

router = APIRouter(tags=["jobs"])

_JOBS_NOTE = (
    "Runs execute on a background thread inside this API process (no queue broker -- "
    "ADR-003 defers a workflow engine until there's a real trigger). A finished run is "
    "durable in Postgres like any other run; only this live progress record is lost if "
    "the API restarts mid-run."
)


def _to_view(job) -> RunJobView:
    return RunJobView(
        job_id=job.job_id, name=job.name, project_id=job.project_id, state=job.state,
        percent=job.percent, message=job.message,
        trace=[TraceRow(**t) for t in job.trace], warnings=job.warnings,
        run_id=job.run_id, error=job.error, gate_blocked=job.gate_blocked,
        gate_block_reasons=job.gate_block_reasons, n_gaps=job.n_gaps,
        n_proposals=job.n_proposals, started_at=job.started_at, finished_at=job.finished_at,
    )


@router.get("/runs/new/config", response_model=NewRunConfig)
def new_run_config() -> NewRunConfig:
    providers = [
        ProviderOption(
            key=cfg.key, label=cfg.label, default_model=cfg.default_model,
            models=list(cfg.known_models), api_key_env=cfg.api_key_env,
            # Reported honestly so the UI can disable a provider up front
            # instead of letting a run start and fail minutes in.
            api_key_present=bool(os.getenv(cfg.api_key_env, "").strip()),
        )
        for cfg in PROVIDER_REGISTRY.values()
    ]
    return NewRunConfig(
        providers=providers,
        default_provider=DEFAULT_PROVIDER_KEY,
        domains=list(DOMAINS.keys()),
        default_domain="Healthcare AI" if "Healthcare AI" in DOMAINS else next(iter(DOMAINS)),
        min_papers=MIN_PAPERS, max_papers=MAX_PAPERS,
        jobs_note=_JOBS_NOTE,
    )


@router.post("/runs/new", response_model=RunJobView)
async def create_run(
    files: list[UploadFile] = File(...),
    name: str = Form(""),
    domain: str = Form("Healthcare AI"),
    interest: str = Form(""),
    gap_type: str = Form("Any"),
    provider_key: str = Form(DEFAULT_PROVIDER_KEY),
    model: str = Form(""),
    extract_refs: bool = Form(False),
    enable_quality_engine: bool = Form(False),
    enable_gap_challenger: bool = Form(False),
) -> RunJobView:
    cfg = PROVIDER_REGISTRY.get(provider_key)
    if cfg is None:
        raise NotFoundError(f"Unknown provider '{provider_key}'.")

    api_key = os.getenv(cfg.api_key_env, "").strip()
    if not api_key:
        # A 400 with the exact env var to set, not a generic failure --
        # and raised before any file is read or any thread is started.
        raise PipelineInputError(
            f"No API key configured for {cfg.label}. Set {cfg.api_key_env} in .env "
            "and restart the API."
        )

    papers = [(f.filename or f"paper_{i+1}.pdf", await f.read()) for i, f in enumerate(files)]
    if len(papers) < MIN_PAPERS:
        raise PipelineInputError(
            f"Upload at least {MIN_PAPERS} PDFs (got {len(papers)}) -- gap detection "
            "compares papers against each other."
        )

    from domain_config import get_domain_config

    job = start_run(
        papers=papers,
        context={"domain": domain, "interest": interest or "General research", "gap_type": gap_type},
        options=RunOptions(
            provider_key=provider_key,
            model=model or cfg.default_model,
            extract_refs=extract_refs,
            enable_quality_engine=enable_quality_engine,
            enable_gap_challenger=enable_gap_challenger,
            ss_api_key=os.getenv("SEMANTIC_SCHOLAR_API_KEY", ""),
            domain_config=get_domain_config(domain),
        ),
        api_key=api_key,
        name=name,
    )
    return _to_view(job)


# NOT /runs/jobs: that is a single path segment and would be captured
# by GET /runs/{run_id} (whichever router registers first wins),
# silently serving a run-detail 404 instead of the job listing.
@router.get("/jobs", response_model=list[RunJobView])
def all_jobs() -> list[RunJobView]:
    return [_to_view(j) for j in list_jobs()]


@router.get("/jobs/{job_id}", response_model=RunJobView)
def job_status(job_id: str) -> RunJobView:
    job = get_job(job_id)
    if job is None:
        raise NotFoundError(
            f"No job '{job_id}'. Progress records live in the API process and are lost "
            "on restart -- if the run completed, find it in the run registry instead."
        )
    return _to_view(job)
