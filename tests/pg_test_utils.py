"""
Shared Postgres test-isolation helper (Clinova Phase 4, Epic 4.1). Gives
each test class its own throwaway schema -- the same full isolation the
pre-migration SQLite tests got from a fresh tmpdir *.db file per test
class, just via a Postgres schema instead of a separate file. Requires a
real local Postgres server (see .env's POSTGRES_* / RESUME.md setup notes)
-- utils/database.py has no other backend anymore, so this is the same
hard requirement the app itself now has, not a new one invented for tests.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import psycopg
import utils.database as db


def new_test_schema() -> str:
    """Creates a fresh, empty, randomly-named schema and returns its name.
    Uses a plain connection (default 'public' search_path) since the
    schema doesn't exist yet for db._get_conn() to target."""
    name = f"test_{uuid.uuid4().hex[:12]}"
    c = db._config()
    conn = psycopg.connect(
        f"postgresql://{c['user']}:{c['password']}@{c['host_and_port']}/{c['database']}"
    )
    conn.autocommit = True
    conn.execute(f'CREATE SCHEMA "{name}"')
    conn.close()
    return name


def drop_test_schema(name: str) -> None:
    c = db._config()
    conn = psycopg.connect(
        f"postgresql://{c['user']}:{c['password']}@{c['host_and_port']}/{c['database']}"
    )
    conn.autocommit = True
    conn.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
    conn.close()
