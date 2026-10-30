"""PR-23: the audit log is append-only, chained, free of secrets, and filled by the actions that matter."""
import sqlite3

import pytest

from utils import audit_log
from utils import database as db


def _raw(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_events_are_recorded_newest_first_with_actor_and_time(isolated_env, monkeypatch):
    monkeypatch.setenv("RESGAP_ACTOR", "alice")
    assert audit_log.record("run.started", "project", "p1", {"papers": 3})
    assert audit_log.record("run.finished", "run", "r1")
    ev = audit_log.list_events()
    assert [e["action"] for e in ev] == ["run.finished", "run.started"]
    assert ev[1]["actor"] == "alice" and ev[1]["target_id"] == "p1" and '"papers": 3' in ev[1]["detail"]
    assert ev[0]["at"].endswith("Z")


def test_the_actor_defaults_to_local(isolated_env, monkeypatch):
    monkeypatch.delenv("RESGAP_ACTOR", raising=False)
    audit_log.record("project.created", "project", "p")
    assert audit_log.list_events()[0]["actor"] == "local"


def test_an_untouched_log_verifies_and_an_empty_one_too(isolated_env):
    assert audit_log.verify()["ok"] and audit_log.verify()["count"] == 0
    for i in range(5):
        audit_log.record("run.started", "project", f"p{i}")
    out = audit_log.verify()
    assert out["ok"] and out["count"] == 5


def test_the_database_refuses_to_edit_or_delete_an_entry(isolated_env):
    audit_log.record("run.deleted", "run", "r1")
    conn = _raw(db._db_path())
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE audit_log SET actor = 'mallory'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM audit_log")
    conn.close()
    assert audit_log.verify()["ok"]


def test_tampering_behind_the_apps_back_is_detected(isolated_env):
    for i in range(4):
        audit_log.record("run.started", "project", f"p{i}")
    conn = _raw(db._db_path())
    conn.execute("DROP TRIGGER audit_log_no_update")                 # someone with file access removes the guard...
    conn.execute("UPDATE audit_log SET actor = 'mallory' WHERE seq = 2")  # ...and rewrites history
    conn.commit()
    conn.close()
    out = audit_log.verify()
    assert not out["ok"] and out["first_bad_seq"] == 2 and "changed" in out["problem"]


def test_removing_an_entry_is_detected(isolated_env):
    for i in range(4):
        audit_log.record("run.started", "project", f"p{i}")
    conn = _raw(db._db_path())
    conn.execute("DROP TRIGGER audit_log_no_delete")
    conn.execute("DELETE FROM audit_log WHERE seq = 2")
    conn.commit()
    conn.close()
    out = audit_log.verify()
    assert not out["ok"] and out["first_bad_seq"] == 2 and "missing" in out["problem"]


def test_secret_looking_fields_are_dropped_and_long_values_cut(isolated_env):
    audit_log.record("settings.provider", "model_settings", "",
                     {"api_key": "sk-secret", "Authorization": "Bearer x", "note": "x" * 5000, "ok": 1, "token_count": 5})
    d = audit_log.list_events()[0]["detail"]
    assert "sk-secret" not in d and "Bearer" not in d and "api_key" not in d and "token_count" not in d
    assert '"ok": 1' in d and len(d) < 400


def test_a_failure_to_write_is_reported_not_raised(isolated_env, monkeypatch):
    monkeypatch.setattr(audit_log.db, "_get_conn", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("disk full")))
    assert audit_log.record("run.started") is False


def test_filters_and_paging(isolated_env):
    for i in range(6):
        audit_log.record("run.started" if i % 2 else "run.deleted", "run", f"r{i}")
    assert {e["action"] for e in audit_log.list_events(action="run.deleted")} == {"run.deleted"}
    assert [e["target_id"] for e in audit_log.list_events(target_id="r3")] == ["r3"]
    assert len(audit_log.list_events(limit=2)) == 2 and len(audit_log.list_events(limit=2, offset=4)) == 2


def test_csv_export_defuses_spreadsheet_formulas(isolated_env):
    audit_log.record("run.started", "project", "=HYPERLINK(\"http://evil\")", {"x": "+1"})
    text = audit_log.to_csv(audit_log.list_events())
    assert "'=HYPERLINK" in text and text.splitlines()[0].startswith("seq,at,actor")


# ── the app fills it ─────────────────────────────────────────────────────────────────────────
def test_creating_and_deleting_a_project_and_a_run_are_recorded(isolated_env):
    from utils import project_store, run_management
    p = project_store.create_project("Audit me")
    run_management.delete_project(p["id"], erase=True)
    actions = [e["action"] for e in audit_log.list_events()]
    assert "project.created" in actions and "project.deleted" in actions
    assert audit_log.list_events(action="project.deleted")[0]["detail"].count("true") == 1


def test_deleting_a_run_is_recorded_with_the_erase_policy(isolated_env, monkeypatch):
    from tests.fixtures.make_golden_run import golden_comp, golden_results, seed_run
    from utils import run_management
    run_id = seed_run(golden_results(), name="r", comp_results=golden_comp())
    monkeypatch.setenv("RESGAP_ERASE_ON_DELETE", "1")
    run_management.delete_run(db.DEFAULT_PROJECT_ID, run_id)
    e = audit_log.list_events(action="run.deleted")[0]
    assert e["target_id"] == run_id and '"erase_policy": true' in e["detail"]


def test_a_backup_and_a_restore_are_recorded(isolated_env):
    from utils import backup
    db.init_db()
    zip_path = backup.create_backup(isolated_env / "bk", keep=None)
    assert audit_log.list_events(action="backup.created")[0]["target_id"] == zip_path.name


def test_changing_the_model_assignment_is_recorded_without_keys(isolated_env):
    from utils.model_router import ModelConfig, ModelSpec
    from utils.model_settings import save_config
    cfg = ModelConfig({"analysis": ModelSpec("custom", "m1", "https://llm.corp.example/v1")}, None)
    save_config(cfg)
    d = audit_log.list_events(action="settings.provider")[0]["detail"]
    assert "analysis=custom@llm.corp.example/m1" in d


def test_a_run_start_records_the_policy_it_ran_under(isolated_env, monkeypatch):
    monkeypatch.setenv("RESGAP_EGRESS", "models")
    monkeypatch.setenv("RESGAP_ALLOWED_PROVIDERS", "gemini")
    from pipeline import run_pipeline as rp
    monkeypatch.setattr(rp, "_run_full_pipeline", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop here")))
    opts = rp.RunOptions(provider_key="gemini", model="m")
    with pytest.raises(RuntimeError):
        rp.run_full_pipeline([("a.pdf", b"")], {}, object(), opts)
    started = audit_log.list_events(action="run.started")[0]["detail"]
    assert '"egress": "models"' in started and '"allowed_providers": "gemini"' in started
    assert audit_log.list_events(action="run.failed")[0]["detail"].count("RuntimeError") == 1


def test_the_settings_audit_tab_shows_the_log_and_policy(app_test):
    audit_log.record("run.started", "project", "pX")
    at = app_test(timeout=120)
    at.session_state["view"] = "settings"
    at.run()
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert not at.exception
    assert "Policy in effect" in text and "Network:" in text
    assert any("Intact" in s.value for s in at.success)
