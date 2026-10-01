import os

from fastapi import APIRouter, Form

from apps.api.errors import NotFoundError
from apps.api.models.council import ResearchCouncilView
from apps.api.models.jobs import RunJobView
from apps.api.routers.jobs import _to_view
from apps.api.services.council_service import get_project_council
from pipeline.run_pipeline import PipelineInputError
from utils.model_providers import DEFAULT_PROVIDER_KEY, PROVIDER_REGISTRY
from utils.database import load_run

router = APIRouter(tags=["council"])


@router.get("/projects/{project_id}/council", response_model=ResearchCouncilView)
def project_council(project_id: str, run_id: str | None = None) -> ResearchCouncilView:
    """Optional run_id pins every workspace tab to the same run. Omitted = the
    most recent run that has Computational Lab output, which is not
    necessarily the most recent run overall."""
    return get_project_council(project_id, run_id)


@router.post("/runs/{run_id}/computational-lab", response_model=RunJobView)
def run_computational_lab(
    run_id: str,
    name: str = Form(""),
    provider_key: str = Form(DEFAULT_PROVIDER_KEY),
    model: str = Form(""),
    n_council_runs: int = Form(2),
) -> RunJobView:
    """Starts the Computational Lab (parameter extraction, cross-paper
    discovery, multi-algorithm simulation, multi-run insight council)
    against an existing run's already-saved results. Previously only
    runnable from the Streamlit sidebar (app.py's "Run Computational Lab"
    button) -- this is the first API trigger for it. Reuses the same
    job registry / GET /api/jobs/{job_id} polling path as /runs/new."""
    from apps.api.services.jobs_service import start_comp_lab_run

    if not (load_run(run_id) or {}).get("results"):
        raise NotFoundError(f"No run '{run_id}' with results to run the Computational Lab against.")

    cfg = PROVIDER_REGISTRY.get(provider_key)
    if cfg is None:
        raise NotFoundError(f"Unknown provider '{provider_key}'.")

    api_key = os.getenv(cfg.api_key_env, "").strip()
    if not api_key:
        raise PipelineInputError(
            f"No API key configured for {cfg.label}. Set {cfg.api_key_env} in .env "
            "and restart the API."
        )

    job = start_comp_lab_run(
        source_run_id=run_id, provider_key=provider_key, model=model or cfg.default_model,
        api_key=api_key, name=name, n_council_runs=max(1, min(3, n_council_runs)),
    )
    return _to_view(job)
