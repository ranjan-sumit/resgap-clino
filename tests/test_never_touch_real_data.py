"""TEST-01: a test cannot reach the real database, even if it forgets `isolated_env`."""
import sqlite3
from pathlib import Path

import utils.database as db
from utils import audit_log


def _real_audit_count():
    real = Path(db.DEFAULT_DB_PATH)
    if not real.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{real.resolve().as_posix()}?mode=ro", uri=True)
        try:
            return con.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return None                                   # an older database without the table: nothing to protect


def test_the_default_test_database_is_not_the_real_one():
    path = Path(db._db_path()).resolve()
    assert path != Path(db.DEFAULT_DB_PATH).resolve()
    assert "guard" in path.parts[-2]                  # the temporary folder this fixture makes


def test_writing_an_audit_event_does_not_change_the_real_audit_log():
    before = _real_audit_count()
    assert audit_log.record("run.started", "project", "default", {"model": "test-model"})
    assert _real_audit_count() == before              # this used to add a row to data/run_history.db
