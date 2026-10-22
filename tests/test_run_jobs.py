import threading
import time
from types import SimpleNamespace

import pytest

import utils.database as db
from pipeline import run_pipeline as rp
from utils import run_jobs

PID = db.DEFAULT_PROJECT_ID


def _outcome(**kw):
    base = dict(run_id="abc123", name="n", n_papers=3, n_gaps=2, n_proposals=1, n_evidence=9,
                gate_blocked=False, gate_block_reasons=[], duration_seconds=12.0)
    return SimpleNamespace(**(base | kw))


def _opts():
    return SimpleNamespace(project_id=PID)


def _wait(job_id, states=("done", "failed"), timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        j = run_jobs.get_job(job_id)
        if j["status"] in states:
            return j
        time.sleep(0.05)
    raise AssertionError(f"job stuck: {run_jobs.get_job(job_id)}")


def test_job_lifecycle_queued_running_done(isolated_env):
    gate = threading.Event()

    def runner(**kw):
        kw["progress"]("Stage 1 — Parsing PDFs…", 5)
        kw["trace"]("Stage 1 — PDF Parse", "3 PDFs", "ok")
        kw["warn"]("something minor")
        gate.wait(5)
        kw["progress"]("Stage 2 — Compiling LLM Wiki pages…", 22)
        return _outcome()

    job_id = run_jobs.start_job(papers=[], context={}, client=None, options=_opts(), name="n", runner=runner)
    end = time.time() + 5
    while time.time() < end and not run_jobs.get_job(job_id)["warnings_json"]:
        time.sleep(0.05)
    j = run_jobs.get_job(job_id)
    assert j["status"] == "running" and j["stage_idx"] == 0 and j["trace_json"][0]["stage"] == "Stage 1 — PDF Parse"
    assert j["warnings_json"] == ["something minor"]
    gate.set()
    j = _wait(job_id)
    assert j["status"] == "done" and j["run_id"] == "abc123" and j["progress_pct"] == 100
    assert j["summary_json"]["n_gaps"] == 2 and j["finished_at"]


def test_a_crashing_runner_leaves_a_failed_job_with_the_error(isolated_env):
    def runner(**kw):
        raise RuntimeError("stage exploded")

    j = _wait(run_jobs.start_job(papers=[], context={}, client=None, options=_opts(), runner=runner))
    assert j["status"] == "failed" and "stage exploded" in j["error"]


def test_input_errors_are_reported_without_a_traceback(isolated_env):
    def runner(**kw):
        raise rp.PipelineInputError("Upload at least 2 papers")

    j = _wait(run_jobs.start_job(papers=[], context={}, client=None, options=_opts(), runner=runner))
    assert j["error"].endswith("Upload at least 2 papers") and "Traceback" not in j["error"]


def test_the_job_outlives_the_caller_that_started_it(isolated_env):
    """The page that started the job can vanish (refresh); the worker finishes regardless."""
    def runner(**kw):
        time.sleep(0.3)
        return _outcome()

    job_id = run_jobs.start_job(papers=[], context={}, client=None, options=_opts(), runner=runner)
    assert run_jobs.list_jobs(active_only=True)                     # a fresh "session" finds it by project
    assert _wait(job_id)["status"] == "done"


def test_orphaned_jobs_are_failed_after_a_restart(isolated_env):
    orphan = run_jobs.create_job(PID, "cut off")
    run_jobs.record_progress(orphan, "Stage 2 — Compiling LLM Wiki pages…", 22)
    assert run_jobs.fail_orphans() == 1
    j = run_jobs.get_job(orphan)
    assert j["status"] == "failed" and "restarted" in j["error"]


def test_a_live_job_is_not_treated_as_an_orphan(isolated_env):
    gate = threading.Event()
    job_id = run_jobs.start_job(papers=[], context={}, client=None, options=_opts(),
                                runner=lambda **kw: (gate.wait(5), _outcome())[1])
    time.sleep(0.2)
    assert run_jobs.fail_orphans() == 0
    gate.set()
    assert _wait(job_id)["status"] == "done"


@pytest.mark.parametrize("msg,idx", [
    ("Stage 1 — Parsing PDFs & building PageIndex trees…", 0),
    ("Stage 1B — Extracting & enriching references", 1),
    ("Stage 2 — Compiling LLM Wiki pages…", 2),
    ("Stage 2C — Extracting evidence objects…", 3),
    ("Stage 3 — Building knowledge graph (LazyGraphRAG)…", 4),
    ("Stage 4 — Finding research gaps", 5),
    ("Stage 5 — Checking gaps against the literature", 6),
    ("Stage 6b — Reviewing proposals…", 7),
    ("Done", 8),
    ("something else", -1),
])
def test_progress_messages_map_to_checklist_stages(msg, idx):
    assert run_jobs.stage_index(msg) == idx


def _job(status="running", cur=2, times=None, pct=30):
    return {"status": status, "stage_idx": cur, "stage_times": times or {}, "progress_pct": pct,
            "message": "m", "error": None, "warnings_json": []}


def test_checklist_marks_done_running_waiting_and_skipped():
    times = {"0": {"start": 0, "end": 40}, "2": {"start": 40, "end": None}}
    cl = run_jobs.checklist(_job(times=times), now=70)
    states = {r["key"]: r["state"] for r in cl["rows"]}
    assert states["parse"] == "done" and states["refs"] == "skipped" and states["wiki"] == "running"
    assert states["gaps"] == "waiting"
    assert [r["elapsed"] for r in cl["rows"] if r["key"] == "wiki"] == [30.0]
    assert cl["notice"] is None


def test_a_stage_over_twice_its_usual_time_gets_a_notice():
    times = {"2": {"start": 0, "end": None}}               # wiki usually ~90 s
    assert run_jobs.checklist(_job(times=times), now=150)["notice"] is None
    assert "more than twice" in run_jobs.checklist(_job(times=times), now=400)["notice"]


def test_a_failed_job_marks_its_stage_failed():
    cl = run_jobs.checklist(_job("failed", cur=3, times={"3": {"start": 0, "end": None}}), now=5)
    assert [r["state"] for r in cl["rows"] if r["key"] == "evidence"] == ["failed"]
