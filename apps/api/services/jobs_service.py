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
