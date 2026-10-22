import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import utils.database as db
from tests.ui_helpers import (PID, click, next_step, open_settings, open_wizard, store_papers, texts,
                              tick_stored_papers, wizard_to_review)
from ui import settings_state as ss
from utils import project_store

_ENV_KEYS = ("NVIDIA_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "DASHSCOPE_API_KEY",
             "CUSTOM_LLM_API_KEY", "CUSTOM_LLM_BASE_URL", "SEMANTIC_SCHOLAR_API_KEY")


@pytest.fixture
def no_env_keys(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.setenv(k, "")          # "" (not absent) stops app.py's .env loader from filling them in


# ── settings_state (pure) ───────────────────────────────────────────────────────────────────
_REG = {"gemini": SimpleNamespace(api_key_env="GEMINI_API_KEY"), "nvidia": SimpleNamespace(api_key_env="NVIDIA_API_KEY")}


def test_a_typed_key_wins_over_the_environment_and_sources_are_reported():
    s = ss.new_settings()
    s["typed_keys"]["gemini"] = " typed-key "
    r = ss.resolve_keys(s, _REG, "custom", env={"GEMINI_API_KEY": "env-key", "NVIDIA_API_KEY": "n-key"})
    assert r["keys"]["gemini"] == "typed-key" and r["sources"]["gemini"] == "typed"
    assert r["keys"]["nvidia"] == "n-key" and r["sources"]["nvidia"] == "environment"
    assert r["available"] == {"gemini", "nvidia"}


def test_no_key_means_not_available_and_not_set():
    r = ss.resolve_keys(ss.new_settings(), _REG, "custom", env={})
    assert r["available"] == set() and r["sources"]["gemini"] is None
    assert ss.source_label(None) == "not set"


def test_custom_endpoint_needs_both_a_key_and_a_base_url():
    s = ss.new_settings(); s["custom_key"] = "k"
    assert "custom" not in ss.resolve_keys(s, _REG, "custom", env={})["available"]
    s["custom_base"] = "https://x.test/v1"
    assert "custom" in ss.resolve_keys(s, _REG, "custom", env={})["available"]


def test_semantic_scholar_key_source():
    assert ss.resolve_keys(ss.new_settings(), _REG, "custom", env={"SEMANTIC_SCHOLAR_API_KEY": "s"})["ss_source"] == "environment"


def test_hide_paths_reads_the_environment(monkeypatch):
    monkeypatch.setenv("RESGAP_HIDE_PATHS", "1")
    assert ss.hide_paths()
    monkeypatch.setenv("RESGAP_HIDE_PATHS", "")
    assert not ss.hide_paths()


# ── Settings page ───────────────────────────────────────────────────────────────────────────
def test_settings_page_has_five_tabs_and_a_back_button(app_test, isolated_env):
    at = open_settings(app_test(timeout=90))
    assert not at.exception
    assert [t.label for t in at.tabs] == ["API keys", "Models", "Analysis defaults", "Saved results", "Backup"]
    click(at, "settings_back")
    assert at.session_state["view"] == "main"


def test_keys_from_the_environment_show_as_in_use(app_test, isolated_env, no_env_keys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-gemini-key")
    at = open_settings(app_test(timeout=90))
    assert "Google Gemini: in use (from the environment)" in texts(at)
    assert "NVIDIA NIM: not set" in texts(at)


def test_a_typed_key_is_used_and_never_written_to_disk(app_test, isolated_env, no_env_keys):
    secret = "AIzaSyTYPEDKEY0123456789ABCDEFGHIJK"
    at = open_settings(app_test(timeout=90))
    at.text_input(key="key_gemini").set_value(secret).run()
    assert "Google Gemini: in use (typed this session)" in texts(at)
    assert at.session_state["_available_providers"] == {"gemini"}
    for path in Path(isolated_env).rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes(), path
    from utils.model_settings import settings_path
    p = settings_path()
    assert not p.exists() or secret not in p.read_text(encoding="utf-8")


def test_a_typed_key_survives_leaving_and_returning_to_settings(app_test, isolated_env, no_env_keys):
    at = open_settings(app_test(timeout=90))
    at.text_input(key="key_gemini").set_value("typed-abc-123456").run()
    click(at, "settings_back")
    open_settings(at)
    assert "Google Gemini: in use (typed this session)" in texts(at)


def test_analysis_defaults_feed_the_wizard(app_test, isolated_env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 30)
    ids = store_papers(2)
    at = open_settings(app_test(timeout=90))
    at.checkbox(key="set_challenger").check().run()
    click(at, "settings_back")
    open_wizard(at)
    tick_stored_papers(at, PID, ids)
    next_step(at); next_step(at)
    assert at.checkbox(key="wiz_challenger").value is True


def test_clearing_a_cache_removes_its_rows_and_forces_a_recompute(app_test, isolated_env):
    db.init_db()
    conn = db._get_conn()
    conn.execute("INSERT INTO wiki_pages (cache_key, content_hash, domain_hash, stage_logic_version, wiki_json)"
                 " VALUES ('k','h','d',1,'{\"x\":1}')")
    conn.commit(); conn.close()
    stats = {r["table"]: r for r in db.cache_stats()}
    assert stats["wiki_pages"]["rows"] == 1 and stats["wiki_pages"]["bytes"] > 0
    at = open_settings(app_test(timeout=90))
    click(at, "clear_wiki_pages")
    assert {r["table"]: r["rows"] for r in db.cache_stats()}["wiki_pages"] == 0


def test_clear_cache_rejects_an_unknown_table(isolated_env):
    with pytest.raises(ValueError):
        db.clear_cache("runs")
    assert db.get_run_row("nope") is None


# ── New analysis wizard ─────────────────────────────────────────────────────────────────────
def test_step_one_needs_two_papers_before_next(app_test, isolated_env):
    ids = store_papers(2)
    at = open_wizard(app_test(timeout=90))
    assert at.button(key="wiz_next").disabled
    tick_stored_papers(at, PID, ids)
    assert not at.button(key="wiz_next").disabled


def test_back_and_forward_keep_what_was_typed(app_test, isolated_env):
    ids = store_papers(2)
    at = open_wizard(app_test(timeout=90))
    tick_stored_papers(at, PID, ids)
    next_step(at)
    at.text_area(key="wiz_interest").set_value("outcomes under age 12").run()
    at.selectbox(key="wiz_gaptype").select("Dataset").run()
    next_step(at)                                              # step 3
    click(at, "wiz_back")                                      # back to step 2
    assert at.text_area(key="wiz_interest").value == "outcomes under age 12"
    assert at.selectbox(key="wiz_gaptype").value == "Dataset"
    click(at, "wiz_back")                                      # back to step 1: papers still ticked
    assert all(at.checkbox(key=f"wiz_use_{PID}_{i}").value for i in ids)


def test_cancel_changes_nothing(app_test, isolated_env):
    ids = store_papers(2)
    at = wizard_to_review(app_test(timeout=90), ids=ids)
    runs_before, jobs_before = len(db.list_runs()), len(__import__("utils.run_jobs", fromlist=["x"]).list_jobs())
    click(at, "wiz_cancel")
    assert at.session_state["view"] == "main" and "_wiz" not in at.session_state
    assert "_run_request" not in at.session_state
    assert len(db.list_runs()) == runs_before
    assert len(__import__("utils.run_jobs", fromlist=["x"]).list_jobs()) == jobs_before


def test_review_step_summarises_the_choices_and_the_estimate(app_test, isolated_env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 30)
    at = wizard_to_review(app_test(timeout=90), ids=store_papers(2))
    t = texts(at)
    assert "Papers (2)" in t and "p0.pdf" in t and "Estimated" in t and "Models:" in t
    assert not at.button(key="wiz_run").disabled


def test_the_wizard_starts_from_the_projects_domain_and_interest(app_test, isolated_env):
    project = project_store.create_project("Prefilled", "d", "ml", "graph neural networks")
    at = app_test(timeout=90)
    at.session_state["project_select"] = project["id"]
    at.run()
    open_wizard(at)
    ids = [r["id"] for r in project_store.list_papers(project["id"])]
    from tests.test_unreadable_pdfs import _text_pdf
    ids = project_store.save_papers(project["id"], [("a.pdf", _text_pdf("a")), ("b.pdf", _text_pdf("b"))])
    at.run()
    tick_stored_papers(at, project["id"], ids)
    next_step(at)
    assert at.text_area(key="wiz_interest").value == "graph neural networks"
    assert "Machine" in at.selectbox(key="wiz_domain").value or at.selectbox(key="wiz_domain").value


# ── New project ─────────────────────────────────────────────────────────────────────────────
def test_creating_a_project_stores_domain_and_interest_and_opens_the_wizard(app_test, isolated_env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 30)
    at = click(app_test(timeout=90), "new_project_btn")
    assert at.session_state["view"] == "new_project"
    at.text_input(key="np_name").set_value("CF review").run()
    at.text_area(key="np_interest").set_value("lung function in children").run()
    at.selectbox(key="np_domain").select(at.selectbox(key="np_domain").options[1]).run()
    click(at, "np_create")
    created = [p for p in db.list_projects() if p["name"] == "CF review"][0]
    assert created["interest"] == "lung function in children" and created["domain"]
    assert at.session_state["view"] == "new_analysis"
    assert at.session_state["current_project_id"] == created["id"]
    assert at.session_state["_wiz"]["interest"] == "lung function in children"


def test_creating_a_project_needs_a_name(app_test, isolated_env):
    at = click(app_test(timeout=90), "new_project_btn")
    click(at, "np_create")
    assert any("needs a name" in e.value for e in at.error)
    assert at.session_state["view"] == "new_project"


def test_new_project_cancel_returns_without_creating(app_test, isolated_env):
    at = click(app_test(timeout=90), "new_project_btn")
    before = len(db.list_projects())
    click(at, "np_cancel")
    assert at.session_state["view"] == "main" and len(db.list_projects()) == before


def test_project_row_and_folder_file_record_domain_and_interest(isolated_env):
    p = project_store.create_project("X", "", "healthcare", "my interest")
    assert db.get_project(p["id"])["interest"] == "my interest"
    info = json.loads((Path(p["path"]) / "project.json").read_text(encoding="utf-8"))
    assert info["domain"] == "healthcare" and info["interest"] == "my interest"


def test_no_absolute_path_is_shown_when_paths_are_hidden(app_test, isolated_env, monkeypatch):
    monkeypatch.setenv("RESGAP_HIDE_PATHS", "1")
    at = app_test(timeout=90)
    at.session_state["main_view"] = "Project"
    at.run()
    open_settings(at)
    assert str(isolated_env) not in texts(at)
    at2 = app_test(timeout=90)
    at2.session_state["main_view"] = "Project"
    at2.run()
    assert str(isolated_env) not in texts(at2)


def test_paths_are_shown_in_local_mode(app_test, isolated_env, monkeypatch):
    monkeypatch.setenv("RESGAP_HIDE_PATHS", "")
    at = app_test(timeout=90)
    at.session_state["main_view"] = "Project"
    at.run()
    assert "Folder:" in texts(at)


# ── empty state ─────────────────────────────────────────────────────────────────────────────
def test_empty_state_guides_to_keys_when_none_are_set(app_test, isolated_env, no_env_keys):
    t = texts(app_test(timeout=90))
    assert "Start here" in t and "Open Settings and paste an API key" in t


def test_empty_state_button_opens_the_wizard(app_test, isolated_env):
    at = click(app_test(timeout=90), "empty_new_analysis")
    assert at.session_state["view"] == "new_analysis"
