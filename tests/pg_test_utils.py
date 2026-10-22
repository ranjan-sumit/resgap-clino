"""
Shared test-isolation helper (Clinova Phase 4, Epic 4.1). Gives each test
class its own throwaway SQLite database file. The file keeps its historical
name (and new_test_schema/drop_test_schema keep theirs) because a dozen test
modules import them and patch `utils.database._SCHEMA`; that hook now holds
the path of a temp SQLite file instead of a Postgres schema name.

No server needed -- sqlite3 ships with Python.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def new_test_schema() -> str:
    """Returns the path of a fresh, empty, throwaway SQLite database file."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="resgap_test_")
    os.close(fd)
    os.unlink(path)  # sqlite creates it on first connect
    return path


def drop_test_schema(path: str) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(path + suffix).unlink(missing_ok=True)
