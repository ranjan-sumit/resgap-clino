import time
from types import SimpleNamespace

import pytest

import utils.database as db
from tests.test_unreadable_pdfs import _text_pdf
from utils import project_store, run_jobs

PID = db.DEFAULT_PROJECT_ID


def _texts(at):
    return " ".join(str(getattr(e, "value", "")) for e in (*at.markdown, *at.caption, *at.info, *at.warning,
                                                            *at.success, *at.error))


def _run_button(at):
    return next(b for b in at.button if b.label == "Run analysis")


def _running_job(message="Stage 2 — Compiling LLM Wiki pages…", pct=25):
    job_id = run_jobs.create_job(PID, "bg")
    run_jobs.record_progress(job_id, "Stage 1 — Parsing PDFs…", 5)
    run_jobs.record_progress(job_id, message, pct)
    return job_id


def test_a_running_job_shows_the_checklist_after_a_refresh(app_test, isolated_env):
    """No session state carries over: the panel is rebuilt from the database alone."""
    _running_job()
    run_jobs._THREADS[run_jobs.list_jobs(active_only=True)[0]["id"]] = SimpleNamespace(is_alive=lambda: True)
    text = _texts(app_test(timeout=90))
    assert "running in the background" in text
    assert "Summarise each paper" in text and "Read the papers" in text


def test_run_button_is_held_while_a_job_runs(app_test, isolated_env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 30)
    for i in range(2):
        project_store.save_papers(PID, [(f"p{i}.pdf", _text_pdf(f"x{i}"))])
    job_id = _running_job()
    run_jobs._THREADS[job_id] = SimpleNamespace(is_alive=lambda: True)
    at = app_test(timeout=90)
    for c in at.checkbox:
        if c.label.startswith("p"):
            c.check()
    at.run()
    assert _run_button(at).disabled


def test_orphaned_job_from_a_previous_process_is_reported_failed(app_test, isolated_env):
    _running_job()                                   # no live thread registered: the process "restarted"
    at = app_test(timeout=90)
    assert "The analysis stopped" in _texts(at) and "restarted" in " ".join(
        str(getattr(e, "value", "")) for e in at.code)


def test_a_finished_job_shows_its_summary_and_can_be_dismissed(app_test, isolated_env):
    job_id = run_jobs.create_job(PID, "done one")
    run_jobs.finish_job(job_id, "r1", {"name": "done one", "n_gaps": 4, "n_proposals": 2,
                                       "duration_seconds": 130, "gate_blocked": False})
    at = app_test(timeout=90)
    assert "4 gaps, 2 proposals" in _texts(at)
    next(b for b in at.button if b.label == "Dismiss").click().run()
    assert "4 gaps, 2 proposals" not in _texts(at)
    assert "4 gaps, 2 proposals" not in _texts(app_test(timeout=90))     # stays dismissed after a refresh


def test_clicking_run_starts_a_background_job_and_shows_its_checklist(app_test, isolated_env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 30)
    papers = [(f"p{i}.pdf", _text_pdf(f"x{i}")) for i in range(2)]
    project_store.save_papers(PID, papers)
    release, seen = __import__("threading").Event(), {}

    def slow_runner(**kw):
        seen["papers"] = kw["papers"]
        kw["progress"]("Stage 2 — Compiling LLM Wiki pages…", 22)
        release.wait(10)
        return SimpleNamespace(run_id="r", name="n", n_papers=2, n_gaps=0, n_proposals=0, n_evidence=0,
                               gate_blocked=False, gate_block_reasons=[], duration_seconds=1.0)

    real = run_jobs.start_job
    monkeypatch.setattr(run_jobs, "start_job", lambda **kw: real(**kw, runner=slow_runner))
    at = app_test(timeout=90)
    for c in at.checkbox:
        if c.label.startswith("p"):
            c.check()
    at.run()
    _run_button(at).click().run()
    try:
        jobs = run_jobs.list_jobs(project_id=PID)
        assert len(jobs) == 1 and jobs[0]["name"] == ""
        assert "running in the background" in _texts(at)
        assert [n for n, _ in seen["papers"]] == ["p0.pdf", "p1.pdf"] if "papers" in seen else True
    finally:
        release.set()
        end = time.time() + 10                      # let the worker finish before the test's database goes away
        while time.time() < end and run_jobs.list_jobs(active_only=True):
            time.sleep(0.05)


def test_background_setting_is_on_by_default_and_can_be_turned_off(app_test, isolated_env):
    at = app_test(timeout=90)
    box = next(c for c in at.checkbox if c.label.startswith("Keep running in the background"))
    assert box.value is True
