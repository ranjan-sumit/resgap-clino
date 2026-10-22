import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

import pytest

import utils.database as db
from tests.fixtures.make_golden_run import golden_results, seed_run
from utils import backup, project_store


def _state(db_path, projects_root):
    """Everything a backup must preserve, in comparable form."""
    runs = sorted((r["id"], r["name"]) for r in db.list_runs(limit=1000, include_archived=True))
    results = {rid: json.dumps(db.load_run(rid)["results"], sort_keys=True) for rid, _ in runs}
    files = {p.relative_to(projects_root).as_posix(): p.read_bytes() for p in Path(projects_root).rglob("*") if p.is_file()}
    return runs, results, files


@pytest.fixture
def populated(isolated_env):
    project = project_store.create_project("Backup test", "d", "healthcare", "")
    project_store.save_papers(project["id"], [("a.pdf", b"%PDF-1.4 a"), ("b.pdf", b"%PDF-1.4 b")])
    seed_run(golden_results(), name="Run one", project_id=project["id"])
    seed_run(golden_results(), name="Run two", project_id=project["id"])
    return project


def test_backup_wipe_restore_gives_back_exactly_what_was_there(populated, tmp_path):
    root = project_store.projects_root()
    before = _state(db._db_path(), root)
    assert before[0] and before[2]                                    # there is something to lose
    zip_path = backup.create_backup(tmp_path / "backups")
    manifest = backup.verify_backup(zip_path)
    assert manifest["project_files"] == len(before[2])

    db_file = Path(db._db_path())
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_file) + suffix).unlink(missing_ok=True)           # wipe
    shutil.rmtree(root)
    db._INITIALIZED.clear()

    out = backup.restore_backup(zip_path)
    db._INITIALIZED.clear()
    assert out["project_files"] == len(before[2])
    assert _state(db._db_path(), project_store.projects_root()) == before


def test_a_backup_made_while_the_app_holds_the_database_open_is_consistent(populated, tmp_path):
    conn = db._get_conn()                                             # an open connection, as the running app has
    try:
        zip_path = backup.create_backup(tmp_path)
    finally:
        conn.close()
    assert backup.verify_backup(zip_path)["database_bytes"] > 0


def test_restore_refuses_to_replace_existing_data_unless_told_to(populated, tmp_path):
    zip_path = backup.create_backup(tmp_path)
    with pytest.raises(backup.BackupError, match="already exists"):
        backup.restore_backup(zip_path)
    out = backup.restore_backup(zip_path, overwrite=True)
    assert out["moved_aside"] and all(Path(p).exists() for p in out["moved_aside"])   # kept, not deleted


def test_a_tampered_backup_is_refused_before_anything_is_touched(populated, tmp_path):
    good = backup.create_backup(tmp_path)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(good) as zin, zipfile.ZipFile(bad, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            zout.writestr(item.filename, b"corrupted" if item.filename == backup.DB_MEMBER else data)
    with pytest.raises(backup.BackupError, match="checksum"):
        backup.restore_backup(bad, overwrite=True)
    assert db.list_runs(limit=10)                                     # the live data is untouched
    with pytest.raises(backup.BackupError):
        backup.verify_backup(tmp_path / "missing.zip")


def test_a_backup_cannot_write_outside_the_projects_folder(populated, tmp_path):
    good = backup.create_backup(tmp_path)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(good) as zin, zipfile.ZipFile(evil, "w") as zout:
        for item in zin.infolist():
            zout.writestr(item.filename, zin.read(item.filename))
        zout.writestr("projects/../../escaped.txt", b"x")
    target_db, target_projects = tmp_path / "t" / "r.db", tmp_path / "t" / "projects"
    with pytest.raises(backup.BackupError, match="outside"):
        backup.restore_backup(evil, db_path=target_db, projects_dir=target_projects)
    assert not (tmp_path / "escaped.txt").exists() and not (tmp_path / "t" / "escaped.txt").exists()


def test_old_automatic_backups_are_pruned_and_a_partial_file_never_looks_complete(populated, tmp_path):
    dest = tmp_path / "keep"
    for _ in range(5):
        backup.create_backup(dest, keep=3)
    assert len(backup.list_backups(dest)) == 3
    assert not list(dest.glob("*.partial"))


def test_the_command_line_creates_verifies_and_restores(populated, tmp_path, capsys):
    spec = importlib.util.spec_from_file_location(
        "backup_cli", Path(__file__).resolve().parent.parent / "scripts" / "backup.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    assert cli.main(["create", "--to", str(tmp_path / "cli")]) == 0
    zip_path = backup.list_backups(tmp_path / "cli")[0]
    assert cli.main(["verify", str(zip_path)]) == 0
    assert cli.main(["restore", str(zip_path)]) == 1                  # refuses: data exists
    assert "already exists" in capsys.readouterr().err
    assert cli.main(["restore", str(zip_path), "--overwrite"]) == 0


def test_backup_bytes_for_a_download_leave_nothing_on_disk(populated):
    name, data = backup.backup_bytes()
    assert name.endswith(".zip") and data[:2] == b"PK"
    assert not backup.list_backups()


def test_settings_has_a_backup_tab_that_produces_a_valid_download(app_test, populated):
    at = app_test(timeout=90)
    at.button(key="settings_btn").click().run()
    at.button(key="make_backup").click().run()
    name, data = at.session_state["_backup"]
    assert name.startswith("resgap-backup-") and data[:2] == b"PK"
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert backup.DB_MEMBER in zf.namelist() and "manifest.json" in zf.namelist()
