"""Background analysis jobs.

`start_job` runs the pipeline in a worker thread and records its progress in the
`run_jobs` table, so the page can poll it, survive a browser refresh, and show a
stage checklist. A job still marked queued/running that has no live thread in
this process was cut off by a restart: `fail_orphans` marks it failed.

Honest limit: a job cannot be cancelled from the UI.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid

import utils.database as db

# The checklist the user sees: (key, label, message prefixes that mean "this stage is running",
# typical seconds). The timings are defaults; they only drive the "taking longer than usual" notice.
STAGES = [
    ("parse", "Read the papers", ("Stage 1 —", "Stage 1 complete"), 40),
    ("refs", "Look up cited references", ("Stage 1B", "Stage 1C", "References complete"), 120),
    ("wiki", "Summarise each paper", ("Stage 2 —", "Wiki complete"), 90),
    ("evidence", "Extract quoted evidence", ("Stage 2B", "Stage 2C"), 120),
    ("graph", "Build the knowledge graph", ("Stage 3", "Graph complete"), 60),
    ("gaps", "Find research gaps", ("Stage 4",), 240),
    ("literature", "Check gaps against the literature", ("Stage 5", "Gaps complete"), 150),
    ("proposals", "Write and review proposals", ("Stage 6", "Proposals complete"), 120),
    ("save", "Save the run", ("Quality gate", "Saving", "Done"), 15),
]
STUCK_FACTOR = 2.0
_THREADS: dict[str, threading.Thread] = {}


def stage_index(message: str) -> int:
    """Which checklist stage a progress message belongs to (-1 if unknown)."""
    for i, (_k, _l, prefixes, _s) in enumerate(STAGES):
        if any((message or "").startswith(p) for p in prefixes):
            return i
    return -1


# ── storage ───────────────────────────────────────────────────────────────────
def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def _row(row) -> dict:
    d = dict(row)
    for col, default in (("stage_times", {}), ("trace_json", []), ("warnings_json", []), ("summary_json", None)):
        try:
            d[col] = json.loads(d[col]) if d.get(col) else default
        except json.JSONDecodeError:
            d[col] = default
    return d


def _update(job_id: str, **fields) -> None:
    db.init_db()
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn = db._get_conn()
    try:
        conn.execute(f"UPDATE run_jobs SET {cols} WHERE id = ?", [*fields.values(), job_id])
        conn.commit()
    finally:
        conn.close()


def create_job(project_id: str, name: str = "") -> str:
    db.init_db()
    job_id = uuid.uuid4().hex[:12]
    conn = db._get_conn()
    try:
        conn.execute("INSERT INTO run_jobs (id, project_id, name, status) VALUES (?,?,?, 'queued')",
                     (job_id, project_id, name))
        conn.commit()
    finally:
        conn.close()
    return job_id


def get_job(job_id: str) -> dict | None:
    db.init_db()
    conn = db._get_conn()
    try:
        row = conn.execute("SELECT * FROM run_jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    return _row(row) if row else None


def list_jobs(project_id: str | None = None, active_only: bool = False, limit: int = 20) -> list[dict]:
    db.init_db()
    clauses, params = [], []
    if project_id:
        clauses.append("project_id = ?"); params.append(project_id)
    if active_only:
        clauses.append("status IN ('queued', 'running')")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    conn = db._get_conn()
    try:
        rows = conn.execute(f"SELECT * FROM run_jobs {where} ORDER BY created_at DESC LIMIT ?",
                            [*params, limit]).fetchall()
    finally:
        conn.close()
    return [_row(r) for r in rows]


def dismiss_job(job_id: str) -> None:
    _update(job_id, dismissed=1)


def unacknowledged_job(project_id: str, done_within_s: int = 600, now: float | None = None) -> dict | None:
    """The job to show when a page opens: one still running, else the latest finished one the
    user has not dismissed (a failure stays until dismissed; a success only for a few minutes)."""
    import calendar
    now = now if now is not None else time.time()
    for job in list_jobs(project_id=project_id, limit=5):
        if job["status"] in ("queued", "running"):
            return job
        if job["dismissed"]:
            return None
        if job["status"] == "failed":
            return job
        finished = calendar.timegm(time.strptime(job["finished_at"][:19], "%Y-%m-%dT%H:%M:%S")) \
            if job["finished_at"] else 0
        return job if now - finished < done_within_s else None
    return None


def record_progress(job_id: str, message: str, pct: int) -> None:
    job = get_job(job_id)
    if job is None:
        return
    idx = stage_index(message)
    times, now = job["stage_times"], time.time()
    fields = {"status": "running", "progress_pct": int(pct), "message": message[:300]}
    if job["started_at"] is None:
        fields["started_at"] = _now()
    if idx > job["stage_idx"]:
        for k, v in times.items():                       # close earlier stages
            if v.get("end") is None:
                v["end"] = now
        times[str(idx)] = {"start": now, "end": None}
        fields["stage_idx"] = idx
        fields["stage_times"] = json.dumps(times)
    _update(job_id, **fields)


def record_trace(job_id: str, stage: str, inputs: str, outputs: str, status: str = "✅") -> None:
    job = get_job(job_id)
    if job is not None:
        rows = job["trace_json"] + [{"stage": stage, "inputs": inputs, "outputs": outputs, "status": status}]
        _update(job_id, trace_json=json.dumps(rows, ensure_ascii=False))


def record_warning(job_id: str, message: str) -> None:
    job = get_job(job_id)
    if job is not None:
        _update(job_id, warnings_json=json.dumps(job["warnings_json"] + [message[:500]], ensure_ascii=False))


def finish_job(job_id: str, run_id: str, summary: dict) -> None:
    now = time.time()
    job = get_job(job_id)
    times = job["stage_times"] if job else {}
    for v in times.values():
        if v.get("end") is None:
            v["end"] = now
    _update(job_id, status="done", progress_pct=100, run_id=run_id, finished_at=_now(),
            summary_json=json.dumps(summary), stage_times=json.dumps(times), message="Done")


def fail_job(job_id: str, error: str) -> None:
    _update(job_id, status="failed", error=error[:2000], finished_at=_now())


def fail_orphans() -> int:
    """Jobs still queued/running with no live thread here were cut off by a restart."""
    n = 0
    for job in list_jobs(active_only=True, limit=200):
        t = _THREADS.get(job["id"])
        if t is None or not t.is_alive():
            fail_job(job["id"], "The app restarted while this analysis was running, so it was stopped. "
                                "Start it again; stages already completed are reused from the cache.")
            n += 1
    return n


# ── running ───────────────────────────────────────────────────────────────────
def start_job(*, papers, context, client, options, name: str = "", token_meter=None, runner=None) -> str:
    """Creates the job and starts it in a daemon thread. Returns the job id."""
    if runner is None:
        from pipeline.run_pipeline import run_full_pipeline as runner
    job_id = create_job(options.project_id or db.DEFAULT_PROJECT_ID, name)

    def work():
        try:
            outcome = runner(
                papers=papers, context=context, client=client, options=options, name=name,
                progress=lambda msg, pct: record_progress(job_id, msg, pct),
                trace=lambda s, i, o: record_trace(job_id, s, i, o),
                warn=lambda m: record_warning(job_id, m),
                token_meter=token_meter,
            )
            finish_job(job_id, outcome.run_id, {
                "name": outcome.name, "n_papers": outcome.n_papers, "n_gaps": outcome.n_gaps,
                "n_proposals": outcome.n_proposals, "n_evidence": outcome.n_evidence,
                "gate_blocked": outcome.gate_blocked, "gate_block_reasons": outcome.gate_block_reasons,
                "duration_seconds": outcome.duration_seconds,
            })
        except BaseException as e:        # a worker must always leave a final state behind
            tb = "".join(traceback.format_exception_only(type(e), e)).strip()
            fail_job(job_id, tb if type(e).__name__ in ("PipelineInputError", "BudgetExceededError") else
                     f"{tb}\n\n{traceback.format_exc()[-1500:]}")
        finally:
            _THREADS.pop(job_id, None)

    thread = threading.Thread(target=work, name=f"run-job-{job_id}", daemon=True)
    _THREADS[job_id] = thread
    thread.start()
    return job_id


# ── what the checklist shows ───────────────────────────────────────────────────
def checklist(job: dict, now: float | None = None) -> dict:
    """Pure view of a job: each stage as done/running/waiting with elapsed seconds, plus
    a notice when the running stage has taken more than STUCK_FACTOR times its usual time."""
    now = now if now is not None else time.time()
    status, cur = job["status"], job["stage_idx"]
    times = job["stage_times"]
    rows, notice = [], None
    for i, (key, label, _p, typical) in enumerate(STAGES):
        t = times.get(str(i))
        if status == "done" or i < cur:
            state = "done" if t else "skipped"
        elif i == cur and status == "running":
            state = "running"
        elif i == cur and status == "failed":
            state = "failed"
        else:
            state = "waiting"
        elapsed = None
        if t:
            elapsed = round((t["end"] or now) - t["start"], 1)
        rows.append({"key": key, "label": label, "state": state, "elapsed": elapsed, "typical": typical})
        if state == "running" and elapsed is not None and elapsed > STUCK_FACTOR * typical:
            notice = (f"“{label}” has been running for {int(elapsed // 60)} min {int(elapsed % 60)} s, "
                      f"more than twice its usual {typical // 60 or '<1'} min. Large papers or a busy "
                      "model provider can cause this; it may still finish.")
    return {"rows": rows, "notice": notice, "pct": job["progress_pct"], "message": job["message"],
            "status": status, "error": job["error"], "warnings": job["warnings_json"]}
