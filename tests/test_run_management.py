import json
import re
from pathlib import Path

import pytest

import utils.database as db
from tests.fixtures.make_golden_run import golden_comp, golden_results, seed_run
from ui import run_board as rb
from utils import project_store
from utils import run_management as rm

PID = db.DEFAULT_PROJECT_ID


def _saved_run(name="r1", results=None, comp=None, project=PID):
    """A run saved the way the pipeline saves it: database rows plus files in the project folder."""
    rid = seed_run(results or golden_results(), name=name, project_id=project, comp_results=comp)
    project_store.write_run_artifacts(project, rid, results or golden_results(), {}, make_reports=False,
                                      manifest={"run_name": name})
    return rid


# ── migration ───────────────────────────────────────────────────────────────────────────────
def test_the_migration_adds_archived_to_old_rows_defaulting_to_visible(isolated_env):
    rid = seed_run(golden_results(), name="old")
    conn = db._get_conn()
    conn.execute("DROP INDEX IF EXISTS idx_runs_archived")
    conn.execute("ALTER TABLE runs DROP COLUMN archived")
    conn.execute("DELETE FROM schema_migrations WHERE version = '0009_run_management.sql'")
    conn.commit(); conn.close()
    db._INITIALIZED.clear()
    db.init_db()
    assert [r["id"] for r in db.list_runs()] == [rid] and db.list_runs()[0]["archived"] == 0
    db._INITIALIZED.clear()
    db.init_db()                                                           # a second start is a no-op
    assert len(db.list_runs()) == 1


# ── rename ──────────────────────────────────────────────────────────────────────────────────
def test_rename_updates_the_database_and_the_manifest_file(isolated_env):
    rid = _saved_run("before")
    assert rm.rename_run(PID, rid, "  After  ")
    assert db.get_run_row(rid)["name"] == "After"
    manifest = json.loads((project_store.project_dir(PID) / "runs" / rid / "manifest.json").read_text())
    assert manifest["run_name"] == "After"


def test_rename_rejects_empty_names_and_unknown_runs(isolated_env):
    rid = _saved_run("keep")
    assert not rm.rename_run(PID, rid, "   ") and db.get_run_row(rid)["name"] == "keep"
    assert not rm.rename_run(PID, "nope", "x")


# ── archive ─────────────────────────────────────────────────────────────────────────────────
def test_archived_runs_are_hidden_by_default_and_restorable(isolated_env):
    a, b = _saved_run("a"), _saved_run("b")
    assert db.set_run_archived(a, True)
    assert [r["name"] for r in db.list_runs()] == ["b"]
    assert {r["name"] for r in db.list_runs(include_archived=True)} == {"a", "b"}
    assert db.list_projects()[0]["run_count"] == 1                          # counts exclude archived runs
    db.set_run_archived(a, False)
    assert len(db.list_runs()) == 2


def test_archiving_keeps_files_and_data(isolated_env):
    rid = _saved_run("keepme")
    db.set_run_archived(rid, True)
    assert db.load_run(rid)["results"]["gaps"] and (project_store.project_dir(PID) / "runs" / rid / "results.json").is_file()


# ── delete ──────────────────────────────────────────────────────────────────────────────────
def test_footprint_lists_files_and_feedback_before_a_delete(isolated_env):
    rid = _saved_run("x")
    db.upsert_feedback(PID, rid, "gap", "g1", rating=1, target_label="g")
    fp = rm.run_footprint(PID, rid)
    assert "results.json" in fp["files"] and "manifest.json" in fp["files"] and fp["feedback"] == 1


def test_delete_keeps_the_files_by_default_and_removes_them_on_request(isolated_env):
    keep, drop = _saved_run("keep-files"), _saved_run("drop-files")
    rm.delete_run(PID, keep)
    assert db.get_run_row(keep) is None and (project_store.project_dir(PID) / "runs" / keep / "results.json").is_file()
    rm.delete_run(PID, drop, remove_files=True)
    assert db.get_run_row(drop) is None and not (project_store.project_dir(PID) / "runs" / drop).exists()
    kinds = {f["kind"] for f in db.list_project_files(PID)}
    assert "results" in kinds                                              # the kept run's file record remains


def test_deleting_a_run_never_removes_the_papers(isolated_env):
    from tests.test_unreadable_pdfs import _text_pdf
    project_store.save_papers(PID, [("a.pdf", _text_pdf("a")), ("b.pdf", _text_pdf("b"))])
    rid = _saved_run("x")
    rm.delete_run(PID, rid, remove_files=True)
    assert len(project_store.list_papers(PID)) == 2


# ── duplicates ──────────────────────────────────────────────────────────────────────────────
def test_runs_with_the_same_papers_and_gaps_are_found_as_duplicates(isolated_env):
    a, b = _saved_run("first"), _saved_run("second")
    other = golden_results()
    other["gaps"] = other["gaps"][:1]
    _saved_run("different", other)
    groups = rm.find_duplicate_groups(PID)
    assert len(groups) == 1 and {r["name"] for r in groups[0]} == {"first", "second"}


def test_runs_without_gaps_are_never_called_duplicates(isolated_env):
    empty = golden_results()
    empty["gaps"] = []
    _saved_run("e1", empty); _saved_run("e2", empty)
    assert rm.find_duplicate_groups(PID) == []


def test_merge_moves_lab_results_and_feedback_and_archives_the_duplicates(isolated_env):
    keep = _saved_run("keep")
    dup = _saved_run("dup", comp=golden_comp())
    db.upsert_feedback(PID, dup, "gap", "g1", rating=-1, target_label="No long-term follow-up")
    db.upsert_feedback(PID, dup, "gap", "g2", rating=1, target_label="x")
    db.upsert_feedback(PID, keep, "gap", "g2", rating=1, target_label="x")           # clashes with the duplicate's g2
    moved = rm.merge_runs(keep, [dup])
    assert moved == {"lab": 1, "feedback": 1, "archived": 1}
    assert db.load_run(keep)["comp_results"] is not None
    assert {f["target_id"] for f in db.list_feedback(run_id=keep)} == {"g1", "g2"}
    assert [r["name"] for r in db.list_runs()] == ["keep"] and db.get_run_row(dup)["archived"] == 1


def test_best_to_keep_prefers_lab_results_then_the_newest():
    a = {"has_comp": 0, "created_at": "2026-10-02T00:00:00Z"}
    b = {"has_comp": 1, "created_at": "2026-10-01T00:00:00Z"}
    c = {"has_comp": 0, "created_at": "2026-10-03T00:00:00Z"}
    assert rm.best_to_keep([a, b, c]) is b and rm.best_to_keep([a, c]) is c


# ── projects ────────────────────────────────────────────────────────────────────────────────
def test_project_settings_update_the_row_and_project_json(isolated_env):
    p = project_store.create_project("Old name", "d", "healthcare", "i")
    rm.update_project(p["id"], "New name", "new d", "ml", "graph networks")
    row = db.get_project(p["id"])
    assert (row["name"], row["description"], row["domain"], row["interest"]) == ("New name", "new d", "ml", "graph networks")
    info = json.loads((Path(p["path"]) / "project.json").read_text())
    assert info["name"] == "New name" and info["interest"] == "graph networks"
    with pytest.raises(ValueError):
        rm.update_project(p["id"], "  ", "", "", "")


def test_deleting_a_project_removes_its_rows_and_moves_the_folder_aside(isolated_env):
    p = project_store.create_project("Doomed")
    rid = _saved_run("in-doomed", project=p["id"])
    db.upsert_feedback(p["id"], rid, "run", "", rating=1)
    fp = rm.project_footprint(p["id"])
    assert fp["runs"] == ["in-doomed"] and fp["n_files"] >= 2
    moved = rm.delete_project(p["id"])
    assert db.get_project(p["id"]) is None and db.get_run_row(rid) is None and db.list_feedback(project_id=p["id"]) == []
    assert moved and moved.is_dir() and moved.parent.name == "_deleted" and (moved / "runs" / rid / "results.json").is_file()
    assert not (project_store.projects_root() / Path(p["path"]).name).exists()


def test_the_default_project_cannot_be_deleted_and_nothing_moves(isolated_env):
    _saved_run("safe")
    with pytest.raises(ValueError):
        rm.delete_project(PID)
    assert len(db.list_runs()) == 1 and project_store.project_dir(PID).is_dir()


# ── board ───────────────────────────────────────────────────────────────────────────────────
def test_board_rows_show_status_model_duration_tokens_and_lab_without_ids():
    runs = [{"id": "abcdef123456", "name": "Run A", "created_at": "2026-10-22T04:00:00Z", "n_papers": 3, "n_gaps": 8,
             "n_proposals": 3, "has_comp": 1, "archived": 0},
            {"id": "ffeeddccbbaa", "name": "Run B", "created_at": "2026-10-21T04:00:00Z", "n_papers": 2, "n_gaps": 0,
             "n_proposals": 0, "has_comp": 0, "archived": 1}]
    manifests = {"abcdef123456": {"run_duration_seconds": 389.0, "token_usage": {"total": 170682},
                                  "model_bundle_version": "gemini:gemini-3.5-flash-lite", "warnings": ["w1"]}}
    rows = rb.board_rows(runs, manifests, {"abcdef123456": 2}, {}, "Asia/Kolkata")
    a, b = rows
    assert a["Status"] == "Completed · 1 warning(s)" and a["Duration"] == "6 min 29 s" and a["Tokens"] == "170,682"
    assert a["Model"] == "gemini-3.5-flash-lite" and a["Lab"] == "✓" and a["Feedback"] == 2 and a["Created"] == "2026-10-22 09:30"
    assert b["Status"] == "Archived" and b["Duration"] == "—" and b["Tokens"] == "—" and b["Model"] == "—"
    assert "ID" not in a and not any("abcdef" in str(v) for v in a.values())


def test_gate_failures_and_missing_manifests_are_named():
    run = {"id": "x", "name": "n", "created_at": "", "n_papers": 1, "n_gaps": 0, "n_proposals": 0, "has_comp": 0, "archived": 0}
    assert rb.status_chip(run, {"warnings": []}, gate_blocked=True) == "Quality check failed"
    assert rb.status_chip(run, None) == "No manifest"
    assert rb.status_chip(run, {}) == "Completed"
    assert "x" not in rb.run_label({"name": "My run", "created_at": "2026-10-22T04:00:00Z"}, "UTC").replace("My run", "")


# ── comparison with and without Lab ─────────────────────────────────────────────────────────
def test_comparison_works_with_and_without_lab_results(isolated_env):
    from pipeline.run_compare import compare_runs
    plain = _saved_run("plain")
    lab = _saved_run("with lab", comp=golden_comp())
    for a, b in ((plain, lab), (lab, plain), (plain, plain), (lab, lab)):
        out = compare_runs(a, b)
        assert out["gaps"]["common_count"] == 2 and out["papers"]["common_count"] == 3
