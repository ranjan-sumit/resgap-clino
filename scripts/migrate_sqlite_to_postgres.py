"""
One-time data migration: data/run_history.db (SQLite, pre-Phase-4) ->
Postgres (utils/database.py, Phase 4 Epic 4.1). Forward-only, per
ADR-005/FR-21 -- the SQLite file is never deleted or modified by this
script, only read from. Safe to re-run: every write below uses the same
ON CONFLICT DO UPDATE upsert semantics as utils/database.py itself, so a
second run just re-applies the same rows rather than duplicating them.

Migrates all 8 tables, not just `runs` -- the 6 LLM-output cache tables
hold real, API-cost-derived data (wiki pages, evidence objects, Docling
extractions, etc.), not disposable scratch state; losing them would mean
re-paying real NVIDIA API calls to regenerate.

Run by hand (not part of the pytest suite, matching this project's
evals/benchmarks/ and scripts/ convention of hand-run, real-data scripts):
    python scripts/migrate_sqlite_to_postgres.py
"""
import sys
import sqlite3
import gzip
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

import utils.database as db

SQLITE_PATH = REPO_ROOT / "data" / "run_history.db"


def _sqlite_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def migrate_runs_and_papers(sconn) -> int:
    rows = sconn.execute("SELECT * FROM runs").fetchall()
    conn = db._get_conn()
    cur = conn.cursor()
    n = 0
    for r in rows:
        blob = gzip.decompress(r["results_gz"])
        blob_data = json.loads(blob)
        from psycopg.types.json import Jsonb
        cur.execute(
            """INSERT INTO runs
               (id, name, created_at, domain, interest, n_papers, n_gaps,
                n_proposals, has_comp, results_json)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                   name = EXCLUDED.name, created_at = EXCLUDED.created_at,
                   domain = EXCLUDED.domain, interest = EXCLUDED.interest,
                   n_papers = EXCLUDED.n_papers, n_gaps = EXCLUDED.n_gaps,
                   n_proposals = EXCLUDED.n_proposals, has_comp = EXCLUDED.has_comp,
                   results_json = EXCLUDED.results_json""",
            (r["id"], r["name"], r["created_at"], r["domain"], r["interest"],
             r["n_papers"], r["n_gaps"], r["n_proposals"], r["has_comp"], Jsonb(blob_data)),
        )
        n += 1
    conn.commit()

    prows = sconn.execute("SELECT * FROM papers").fetchall()
    cur.execute("DELETE FROM papers")  # re-derive fresh from source of truth each run
    for p in prows:
        cur.execute(
            "INSERT INTO papers (run_id, filename, title, tier) VALUES (%s,%s,%s,%s)",
            (p["run_id"], p["filename"], p["title"], p["tier"]),
        )
    conn.commit()
    conn.close()
    return n


def migrate_cache_table(sconn, table: str, columns: list[str]) -> int:
    rows = sconn.execute(f'SELECT * FROM "{table}"').fetchall()
    conn = db._get_conn()
    cur = conn.cursor()
    placeholders = ", ".join(["%s"] * len(columns))
    update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "cache_key")
    for r in rows:
        values = [r[c] for c in columns]
        cur.execute(
            f'INSERT INTO "{table}" ({", ".join(columns)}) VALUES ({placeholders}) '
            f'ON CONFLICT (cache_key) DO UPDATE SET {update_clause}',
            values,
        )
    conn.commit()
    conn.close()
    return len(rows)


def main():
    if not SQLITE_PATH.exists():
        print(f"No SQLite database found at {SQLITE_PATH} -- nothing to migrate.")
        return

    db.init_db()  # ensure Postgres schema exists first
    sconn = _sqlite_conn()

    n_runs = migrate_runs_and_papers(sconn)
    print(f"Migrated {n_runs} run(s) + their papers.")

    cache_tables = {
        "wiki_pages": ["cache_key", "content_hash", "domain_hash", "stage_logic_version", "wiki_json"],
        "parameters": ["cache_key", "content_hash", "stage_logic_version", "params_json"],
        "docling_extractions": ["cache_key", "content_hash", "stage_logic_version", "extraction_json"],
        "evidence_objects": ["cache_key", "content_hash", "stage_logic_version", "evidence_json"],
        "references": ["cache_key", "doi_or_title_hash", "stage_logic_version", "enriched_json"],
        "gap_validations": ["cache_key", "gap_hash", "domain_hash", "stage_logic_version", "validation_json"],
    }
    for table, columns in cache_tables.items():
        n = migrate_cache_table(sconn, table, columns)
        print(f"Migrated {n} row(s) from {table}.")

    sconn.close()
    print("\nMigration complete. data/run_history.db was NOT modified or deleted.")


if __name__ == "__main__":
    main()
