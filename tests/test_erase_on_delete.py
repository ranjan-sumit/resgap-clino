"""Deleting really deletes where the deployment says so; otherwise it stays recoverable. Derived caches can be purged."""
import os
import stat

import pytest

import utils.database as db
from tests.fixtures.make_golden_run import golden_results, seed_run
from utils import project_store, run_management as rm


def _project_with_a_run(name="P"):
    project = project_store.create_project(name, "d", "healthcare", "")
    project_store.save_papers(project["id"], [("a.pdf", b"%PDF-1.4 a"), ("b.pdf", b"%PDF-1.4 b")])
    rid = seed_run(golden_results(), name="run", project_id=project["id"])
    project_store.write_run_artifacts(project["id"], rid, golden_results(), {}, make_reports=False)
    return project, rid


def _fill_caches():
    db.init_db()
    db.save_cached_reference("k1", "h1", 2, {"title": "A paper", "tier": 2})
    db.save_cached_parameters("k2", "h2", 4, [{"name": "p", "value": 1.0}])


def _cache_rows():
    return {row["table"]: row["rows"] for row in db.cache_stats()}


def test_every_cache_including_the_reference_cache_is_listed_and_counted(isolated_env):
    _fill_caches()
    rows = _cache_rows()
    assert set(rows) == set(db.CACHE_STAGES) and "references" in rows
    assert rows["references"] == 1 and rows["parameters"] == 1


def test_clearing_the_reference_cache_works(isolated_env):
    _fill_caches()
    assert db.clear_cache("references") == 1 and _cache_rows()["references"] == 0


def test_the_derived_caches_can_be_purged_together(isolated_env):
    _fill_caches()
    assert db.purge_derived_caches()["references"] == 1
    assert sum(_cache_rows().values()) == 0


# ── default: recoverable ───────────────────────────────────────────────────────────────────────
def test_by_default_a_deleted_project_is_moved_aside_and_the_caches_are_kept(isolated_env, monkeypatch):
    monkeypatch.delenv("RESGAP_ERASE_ON_DELETE", raising=False)
    project, _ = _project_with_a_run()
    _fill_caches()
    folder = project_store.projects_root() / db.get_project(project["id"])["folder"]
    moved = rm.delete_project(project["id"])
    assert moved is not None and moved.is_dir() and not folder.exists()
    assert sum(_cache_rows().values()) == 2
    assert rm.deleted_folder_footprint()["projects"] == 1


def test_by_default_a_deleted_runs_files_stay_unless_asked_to_go(isolated_env, monkeypatch):
    monkeypatch.delenv("RESGAP_ERASE_ON_DELETE", raising=False)
    project, rid = _project_with_a_run()
    run_dir = project_store.project_dir(project["id"]) / "runs" / rid
    rm.delete_run(project["id"], rid)
    assert run_dir.is_dir()
    assert db.get_run_row(rid) is None


# ── erase ──────────────────────────────────────────────────────────────────────────────────────
def test_erasing_a_project_leaves_nothing_on_disk_and_empties_the_caches(isolated_env):
    project, rid = _project_with_a_run()
    _fill_caches()
    folder = project_store.projects_root() / db.get_project(project["id"])["folder"]
    assert rm.delete_project(project["id"], erase=True) is None
    assert not folder.exists()
    assert not (project_store.projects_root() / "_deleted").exists() or not any((project_store.projects_root() / "_deleted").iterdir())
    assert sum(_cache_rows().values()) == 0
    assert db.get_project(project["id"]) is None and db.get_run_row(rid) is None


def test_erasing_also_removes_an_earlier_soft_deleted_copy_of_the_same_project(isolated_env):
    project, _ = _project_with_a_run()
    folder_name = db.get_project(project["id"])["folder"]
    old = project_store.projects_root() / "_deleted" / f"{folder_name}-20260101-000000"
    old.mkdir(parents=True)
    (old / "papers.txt").write_text("an older copy")
    other = project_store.projects_root() / "_deleted" / "someone-else-20260101-000000"
    other.mkdir(parents=True)
    rm.delete_project(project["id"], erase=True)
    assert not old.exists() and other.exists()                         # only this project's leftovers go


def test_the_policy_variable_turns_every_project_delete_into_an_erase(isolated_env, monkeypatch):
    monkeypatch.setenv("RESGAP_ERASE_ON_DELETE", "1")
    assert rm.erase_on_delete()
    project, _ = _project_with_a_run()
    _fill_caches()
    assert rm.delete_project(project["id"]) is None
    assert sum(_cache_rows().values()) == 0


def test_read_only_files_are_erased_too(isolated_env):
    project, _ = _project_with_a_run()
    folder = project_store.projects_root() / db.get_project(project["id"])["folder"]
    target = next(p for p in folder.rglob("*") if p.is_file())
    os.chmod(target, stat.S_IREAD)
    rm.delete_project(project["id"], erase=True)
    assert not folder.exists()


def test_under_the_policy_a_run_delete_removes_its_files_and_empties_the_caches(isolated_env, monkeypatch):
    monkeypatch.setenv("RESGAP_ERASE_ON_DELETE", "1")
    project, rid = _project_with_a_run()
    _fill_caches()
    run_dir = project_store.project_dir(project["id"]) / "runs" / rid
    assert run_dir.is_dir()
    rm.delete_run(project["id"], rid)
    assert not run_dir.exists() and sum(_cache_rows().values()) == 0
    assert any(f["kind"] == "paper" for f in db.list_project_files(project["id"]))     # papers are never removed by a run delete


def test_papers_of_other_projects_are_untouched_by_an_erase(isolated_env):
    keep, _ = _project_with_a_run("keep")
    gone, _ = _project_with_a_run("gone")
    rm.delete_project(gone["id"], erase=True)
    assert project_store.project_dir(keep["id"]).is_dir()
    assert len([f for f in db.list_project_files(keep["id"]) if f["kind"] == "paper"]) == 2


def test_the_default_project_still_cannot_be_deleted(isolated_env):
    db.init_db()
    with pytest.raises(ValueError):
        rm.delete_project(db.DEFAULT_PROJECT_ID, erase=True)


# ── the folder of earlier deletes ──────────────────────────────────────────────────────────────
def test_the_deleted_folder_can_be_counted_and_emptied(isolated_env):
    project, _ = _project_with_a_run()
    rm.delete_project(project["id"])
    fp = rm.deleted_folder_footprint()
    assert fp["projects"] == 1 and fp["bytes"] > 0
    assert rm.empty_deleted_folder() == 1
    assert rm.deleted_folder_footprint() == {"projects": 0, "bytes": 0}
    assert rm.empty_deleted_folder() == 0


# ── the screens say what will happen ───────────────────────────────────────────────────────────
def test_settings_offers_to_erase_deleted_projects_when_there_are_some(app_test, isolated_env, monkeypatch):
    monkeypatch.delenv("RESGAP_ERASE_ON_DELETE", raising=False)
    project, _ = _project_with_a_run()
    rm.delete_project(project["id"])
    at = app_test(timeout=90)
    at.button(key="settings_btn").click().run()
    assert any(b.key == "empty_deleted" for b in at.button)
    next(b for b in at.button if b.key == "empty_deleted").click().run()
    assert rm.deleted_folder_footprint()["projects"] == 0


def test_the_project_delete_warning_tells_the_truth_about_what_happens(app_test, isolated_env, monkeypatch):
    project, _ = _project_with_a_run()
    for policy, expected in (("", "moved to a _deleted folder"), ("1", "erased permanently")):
        monkeypatch.setenv("RESGAP_ERASE_ON_DELETE", policy)
        at = app_test(timeout=90)
        at.session_state["current_project_id"] = project["id"]
        at.session_state["main_view"] = "Project"
        at.run()
        warnings = " ".join(w.value for w in at.warning)
        assert expected in warnings, (policy, warnings)
