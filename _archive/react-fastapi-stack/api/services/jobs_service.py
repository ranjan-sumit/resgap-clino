"""
In-process run-job registry (Clinova Phase 5, Epic 5.6).

A pipeline run takes minutes and makes real, paid LLM calls, so it cannot be
served from a request handler. This keeps a small in-memory registry of jobs
executed on a background thread, which the web app polls for live progress.

Deliberately NOT a queue/broker (Celery, RQ, Temporal): ADR-003 defers a
workflow engine until there is a real trigger for one, and this is a
single-user local workspace. The honest consequence -- jobs live in this
process and are lost on API restart -- is surfaced to callers rather than
hidden: a finished run is durable (it is saved to Postgres like any other
run), only the *progress record* is ephemeral.
"""
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pipeline.run_pipeline import PipelineInputError, RunOptions, run_full_pipeline
from utils.model_providers import build_client
from utils.token_meter import TokenMeter
from utils.database import load_run, save_run

# Terminal states a caller can stop polling on.
TERMINAL_STATES = ("succeeded", "failed")


@dataclass
class RunJob:
    job_id: str
    name: str
    project_id: str
    state: str = "queued"           # queued | running | succeeded | failed
    percent: int = 0
    message: str = "Queued"
    trace: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    run_id: str | None = None
    error: str | None = None
    gate_blocked: bool = False
    gate_block_reasons: list[str] = field(default_factory=list)
    n_gaps: int = 0
    n_proposals: int = 0
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None


_JOBS: dict[str, RunJob] = {}
_LOCK = threading.Lock()


def get_job(job_id: str) -> RunJob | None:
    with _LOCK:
        return _JOBS.get(job_id)


def list_jobs() -> list[RunJob]:
    with _LOCK:
        return sorted(_JOBS.values(), key=lambda j: j.started_at, reverse=True)


def _run(job: RunJob, papers, context, options, api_key):
    def progress(msg: str, pct: int) -> None:
        with _LOCK:
            job.message = msg
            job.percent = max(job.percent, pct)

    def trace(stage: str, inputs: str, outputs: str) -> None:
        with _LOCK:
            job.trace.append({"stage": stage, "inputs": inputs, "outputs": outputs})

    def warn(msg: str) -> None:
        with _LOCK:
            job.warnings.append(msg)

    try:
        with _LOCK:
            job.state = "running"
            job.message = "Starting pipeline…"

        token_meter = TokenMeter()
        client = build_client(options.provider_key, api_key, model=options.model,
                              token_meter=token_meter)

        outcome = run_full_pipeline(
            papers=papers, context=context, client=client, options=options,
            name=job.name, progress=progress, trace=trace, warn=warn,
            token_meter=token_meter,
        )

        with _LOCK:
            job.state = "succeeded"
            job.percent = 100
            job.message = "Done"
            job.run_id = outcome.run_id
            job.name = outcome.name
            job.gate_blocked = outcome.gate_blocked
            job.gate_block_reasons = outcome.gate_block_reasons
            job.n_gaps = outcome.n_gaps
            job.n_proposals = outcome.n_proposals
            job.finished_at = datetime.now(timezone.utc).isoformat()

    except PipelineInputError as e:
        with _LOCK:
            job.state = "failed"
            job.error = str(e)
            job.message = "Invalid input"
            job.finished_at = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        with _LOCK:
            job.state = "failed"
            # The real exception text, not a generic "something went wrong" --
            # same honesty rule the rest of this API follows.
            job.error = f"{type(e).__name__}: {e}"
            job.message = "Pipeline failed"
            job.finished_at = datetime.now(timezone.utc).isoformat()
            job.warnings.append(traceback.format_exc().strip().splitlines()[-1])


def start_run(
    papers: list[tuple[str, bytes]],
    context: dict,
    options: RunOptions,
    api_key: str,
    name: str = "",
) -> RunJob:
    """Registers and starts a background pipeline run, returning immediately."""
    job = RunJob(
        job_id=uuid.uuid4().hex[:12],
        name=name or "",
        project_id=context.get("domain") or "default",
    )
    with _LOCK:
        _JOBS[job.job_id] = job

    # daemon=True: a run in flight must never block API shutdown. The run's
    # own save_run() is what makes a completed run durable, not this thread.
    threading.Thread(
        target=_run, args=(job, papers, context, options, api_key), daemon=True,
    ).start()
    return job


def _run_comp_lab(job: RunJob, source_run_id: str, provider_key: str, model: str,
                   api_key: str, name: str, n_council_runs: int):
    """Computational Lab (app.py's Stages 8-12, ported to the API for the
    first time -- previously only runnable from the Streamlit sidebar).
    Same shape as _run() above: progress/trace on the shared job registry,
    a background daemon thread, a durable save_run() at the end. Faithful
    port of app.py's "Run Computational Lab" handler (search that file for
    "Stage 8A" through "Stage 12") -- same functions, same call order, same
    comp_results dict shape council_service.py already reads, minus
    `zip_bytes` (that key was never JSON-safe for Postgres storage even in
    the Streamlit path -- `json.dumps(..., default=str)` on raw bytes
    produces a garbled, useless string, not real zip data; the API path
    just never puts it in the dict rather than carrying that bug forward.
    No report-download feature reads it from here today)."""
    def progress(msg: str, pct: int) -> None:
        with _LOCK:
            job.message = msg
            job.percent = max(job.percent, pct)

    def trace(stage: str, inputs: str, outputs: str) -> None:
        with _LOCK:
            job.trace.append({"stage": stage, "inputs": inputs, "outputs": outputs})

    try:
        with _LOCK:
            job.state = "running"
            job.message = "Loading source run…"

        loaded = load_run(source_run_id) or {}
        results = loaded.get("results")
        if not results:
            raise PipelineInputError(
                f"Source run '{source_run_id}' has no results to run the Computational Lab against."
            )

        # Local imports -- mirrors app.py's own import placement for these
        # (Computational Lab is a distinct, heavier feature from the main
        # pipeline; not every API process path needs these modules loaded).
        from pipeline.param_extractor import (
            extract_parameters, derive_cross_paper_parameters, check_sufficiency,
        )
        from pipeline.paper_manager import extract_tier2_parameters
        from pipeline.discovery_engine import run_discovery_engine
        from pipeline.llm_council import council_select_model
        from pipeline.simulation_engine import filter_confident_params, resolve_models_to_run, run_simulation
        from pipeline.multi_run import run_multi_council

        client = build_client(provider_key, api_key, model=model)
        wiki = results.get("wiki") or {}
        context = results.get("context") or {}
        gaps = results.get("gaps") or []
        ref_papers = results.get("ref_papers") or []
        papers_raw = [
            {"sections": p.get("sections", {}), "tables": p.get("tables", []), "filename": p.get("filename", "")}
            for p in results.get("papers") or []
        ]

        progress("Stage 8A — Extracting Tier 1 parameters…", 8)
        t1_params = extract_parameters(wiki, papers_raw, client)

        t2_params = []
        tier2_refs = [r for r in ref_papers if r.get("tier") == 2 and r.get("abstract")]
        if tier2_refs:
            progress(f"Stage 8A-T2 — Extracting Tier 2 params from {len(tier2_refs)} ref abstracts…", 14)
            t2_params = extract_tier2_parameters(tier2_refs, client)

        params = t1_params + t2_params

        progress("Stage 8A — Deriving cross-paper values…", 18)
        derived = derive_cross_paper_parameters(params, client)
        params += derived

        sufficiency = check_sufficiency(params, client)
        trace("Stage 8A — Parameters",
              f"{len(papers_raw)} T1 papers + {len(tier2_refs)} T2 abstracts",
              f"{len(t1_params)} T1 + {len(t2_params)} T2 + {len(derived)} derived = {len(params)} total")

        from domain_config import get_domain_config
        domain_cfg = get_domain_config(context.get("domain"))  # falls back to General AI/ML

        progress("Stage 8B — Cross-paper discovery engine…", 27)
        discovery = run_discovery_engine(wiki, params, context, client, domain_cfg)
        trace("Stage 8B — Discovery", f"{len(wiki.get('pages', []))} wiki pages",
              f"{len(discovery.get('hypotheses', []))} novel hypotheses")

        progress(f"Stage 9 — LLM Council selecting model ({len(params)} params)…", 42)
        model_council = council_select_model(params, sufficiency, context, client)

        simulation_params, _ = filter_confident_params(params)
        models_auto = resolve_models_to_run(simulation_params, model_council, sufficiency)
        progress(f"Stage 10 — Running {len(models_auto)} algorithms: {', '.join(models_auto)}…", 57)
        sim_results = run_simulation(params, model_council, sufficiency)
        trace("Stage 10 — Simulation", f"{len(models_auto)} algorithms selected",
              f"Models: {sim_results.get('models_run', [])} run")

        def _cp(run_num, total):
            progress(f"Stage 11 — Council run {run_num}/{total}…", 74 + int((run_num - 1) / total * 12))

        progress(f"Stage 11 — Council synthesising insights ({n_council_runs}× runs)…", 74)
        merged_council = run_multi_council(
            n_runs=n_council_runs, sim_results=sim_results, discovery=discovery,
            params=params, gaps=gaps, context=context, client=client, progress_callback=_cp,
        )

        progress("Stage 12 — Saving Computational Lab results…", 92)
        comp_results = {
            "params": params, "derived_count": len(derived),
            "t1_count": len(t1_params), "t2_count": len(t2_params),
            "sufficiency": sufficiency, "discovery": discovery,
            "model_council": model_council, "sim_results": sim_results,
            "insight_council": merged_council, "n_runs": n_council_runs,
        }
        saved_run_id = save_run(name or loaded.get("name") or "Computational Lab", results, comp_results)

        with _LOCK:
            job.state = "succeeded"
            job.percent = 100
            job.message = "Done"
            job.run_id = saved_run_id
            job.finished_at = datetime.now(timezone.utc).isoformat()

    except PipelineInputError as e:
        with _LOCK:
            job.state = "failed"
            job.error = str(e)
            job.message = "Invalid input"
            job.finished_at = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        with _LOCK:
            job.state = "failed"
            job.error = f"{type(e).__name__}: {e}"
            job.message = "Computational Lab failed"
            job.finished_at = datetime.now(timezone.utc).isoformat()
            job.warnings.append(traceback.format_exc().strip().splitlines()[-1])


def start_comp_lab_run(
    source_run_id: str, provider_key: str, model: str, api_key: str,
    name: str = "", n_council_runs: int = 2,
) -> RunJob:
    """Registers and starts a background Computational Lab run against an
    existing run's already-saved results, returning immediately. Uses the
    same job registry/polling endpoint as start_run() -- the frontend
    already knows how to poll GET /api/jobs/{job_id}."""
    job = RunJob(
        job_id=uuid.uuid4().hex[:12],
        name=name or "Computational Lab",
        project_id=source_run_id,
    )
    with _LOCK:
        _JOBS[job.job_id] = job

    threading.Thread(
        target=_run_comp_lab,
        args=(job, source_run_id, provider_key, model, api_key, name, n_council_runs),
        daemon=True,
    ).start()
    return job
