import json
import os
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import utils.database as db
from tests.fixtures.make_golden_run import golden_results
from utils import run_storage

TEXT = "Cystic fibrosis lung function outcomes were measured over twelve months. " * 800     # ~57 KB


def _heavy_results(n=3):
    papers, corpus = [], []
    for i in range(n):
        fname = f"paper{i}.pdf"
        sections = {"Methods": TEXT, "Results": TEXT[:20000]}
        papers.append({"filename": fname, "wiki": {"title": f"Paper {i}"}, "sections": sections,
                       "tables": [], "tier": 1})
        corpus.append({"filename": fname, "sections": sections, "full_text": TEXT * 1, "tables": [],
                       "text_segments": [{"page": 1, "text": TEXT[:30000]}], "tier": 1, "tier_label": "Uploaded PDF"})
    r = golden_results()
    r["papers"], r["corpus"] = papers, corpus
    return r


def _stored_size(rid):
    conn = db._get_conn()
    try:
        main = conn.execute("SELECT length(results_json) n FROM runs WHERE id = ?", (rid,)).fetchone()["n"]
        side = conn.execute("SELECT COALESCE(SUM(length(data)),0) n FROM run_blobs WHERE run_id = ?", (rid,)).fetchone()["n"]
    finally:
        conn.close()
    return main, side


def test_new_run_results_row_is_small_and_text_goes_to_the_side_table(isolated_env):
    rid = db.save_run("big", _heavy_results())
    main, side = _stored_size(rid)
    assert main < 300 * 1024 and side > 100 * 1024
    # sanity: stored the old way this run would be several times larger
    assert len(json.dumps(_heavy_results(), default=str)) > 2 * main


def test_a_run_loads_complete_by_default_and_lean_on_request(isolated_env):
    original = _heavy_results()
    rid = db.save_run("big", original)
    full = db.load_run(rid)["results"]
    assert [p["sections"] for p in full["papers"]] == [p["sections"] for p in original["papers"]]
    lean = db.load_run(rid, sections=False)["results"]
    assert all("sections" not in p for p in lean["papers"])
    assert [p["wiki"]["title"] for p in lean["papers"]] == ["Paper 0", "Paper 1", "Paper 2"]
    assert db.with_sections(rid, lean)["papers"][1]["sections"] == original["papers"][1]["sections"]


def test_deleting_a_run_removes_its_side_data(isolated_env):
    rid = db.save_run("big", _heavy_results())
    db.delete_run(rid)
    assert _stored_size_exists(rid) == 0


def _stored_size_exists(rid):
    conn = db._get_conn()
    try:
        return conn.execute("SELECT COUNT(*) c FROM run_blobs WHERE run_id = ?", (rid,)).fetchone()["c"]
    finally:
        conn.close()


def test_runs_without_sections_save_and_load_unchanged(isolated_env):
    rid = db.save_run("plain", golden_results())
    assert db.load_run(rid)["results"]["gaps"] == golden_results()["gaps"]


# ── old layout and migration ─────────────────────────────────────────────────
def _insert_old_run(created_at="2026-03-05T09:30:00"):
    db.init_db()
    blob = json.dumps({"results": _heavy_results(), "comp_results": None})
    conn = db._get_conn()
    try:
        conn.execute("INSERT INTO runs (id, name, created_at, domain, interest, n_papers, n_gaps, n_proposals, has_comp,"
                     " results_json, project_id) VALUES ('old1','old',?,'d','i',3,2,1,0,?, 'default')", (created_at, blob))
        conn.commit()
    finally:
        conn.close()
    return len(blob)


def _remigrate():
    conn = db._get_conn()
    try:
        conn.execute("DELETE FROM schema_migrations WHERE version = ?", (db._STORAGE_MIGRATION,))
        conn.commit()
    finally:
        conn.close()
    db._INITIALIZED.clear()
    db.init_db()


def test_old_runs_are_slimmed_and_still_load_identically(isolated_env):
    old_size = _insert_old_run()
    _remigrate()
    main, side = _stored_size("old1")
    assert main < old_size / 3 and side > 0
    full = db.load_run("old1")["results"]
    assert full["papers"][0]["sections"]["Methods"] == TEXT
    assert "full_text" not in full["corpus"][0] and "text_segments" not in full["corpus"][0]


def test_migration_makes_a_backup_and_runs_only_once(isolated_env):
    _insert_old_run()
    _remigrate()
    backups = list(isolated_env.glob("t.db.bak-*"))
    assert len(backups) == 1
    before = _stored_size("old1")
    db._INITIALIZED.clear()
    db.init_db()                                                          # second start: nothing to do
    assert _stored_size("old1") == before and len(list(isolated_env.glob("t.db.bak-*"))) == 1


def test_migration_on_an_empty_database_makes_no_backup(isolated_env):
    db.init_db()
    assert list(isolated_env.glob("t.db.bak-*")) == []


def test_an_already_converted_run_is_untouched_by_a_rerun(isolated_env):
    _insert_old_run()
    _remigrate()
    first = _stored_size("old1")
    _remigrate()
    assert _stored_size("old1") == first


# ── time zones ───────────────────────────────────────────────────────────────
def test_new_runs_are_stamped_in_utc(isolated_env):
    rid = db.save_run("t", golden_results())
    ts = db.get_run_row(rid)["created_at"]
    assert ts.endswith("Z")
    stamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 60


@pytest.mark.parametrize("tz", ["UTC", "Asia/Kolkata", "America/Los_Angeles"])
def test_legacy_local_timestamps_convert_to_utc_in_any_machine_zone(tz, monkeypatch):
    if not hasattr(__import__("time"), "tzset"):
        pytest.skip("tzset is not available on this platform")
    monkeypatch.setenv("TZ", tz)
    __import__("time").tzset()
    utc = run_storage.to_utc_iso("2026-03-05T09:30:00")
    back = datetime.fromisoformat(utc.replace("Z", "+00:00")).astimezone()
    assert back.strftime("%Y-%m-%d %H:%M") == "2026-03-05 09:30"


def test_utc_values_pass_through_and_display_in_the_viewers_zone():
    assert run_storage.to_utc_iso("2026-03-05T04:00:00Z") == "2026-03-05T04:00:00Z"
    assert run_storage.to_local_display("2026-03-05T04:00:00Z", "Asia/Kolkata") == "2026-03-05 09:30"
    assert run_storage.to_local_display("2026-03-05T04:00:00Z", "America/Los_Angeles") == "2026-03-04 20:00"
    assert run_storage.to_local_display("2026-03-05T09:30:00", "Asia/Kolkata") == "2026-03-05 09:30"   # legacy naive
    assert run_storage.to_local_display("", None) == ""


def test_run_ordering_survives_the_conversion(isolated_env):
    _insert_old_run("2026-03-05T09:30:00")
    _remigrate()
    new = db.save_run("new", golden_results())
    assert [r["id"] for r in db.list_runs()][0] == new
