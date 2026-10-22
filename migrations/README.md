# Migrations

Forward-only SQL migrations for the SQLite database (Clinova Phase 4,
Epic 4.1, ADR-005/FR-21: "nothing scientifically load-bearing is
overwritten in place"). No Alembic/SQLAlchemy -- hand-rolled, matching
`utils/database.py`'s existing raw-SQL style rather than pulling in an ORM
this codebase doesn't otherwise use.

## How it works

`utils/database.py`'s `init_db()` calls `_apply_migrations()` the first time
a database file is used in a process. It tracks applied migrations in a
`schema_migrations` table and applies any `*.sql` file in this directory, in
filename order, that isn't already recorded there (via `executescript`).
Idempotent -- safe to re-run after adding a new migration file.

## Adding a new migration

Create a new file named `NNNN_description.sql` (four-digit, zero-padded,
strictly increasing) with `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE`
statements. Never edit an already-applied migration file in place -- a
correction is a new migration, same principle as this project's own
`stage_logic_version` cache-busting convention and the Research Artifact
Registry's own immutable-versions rule.

SQLite notes: JSON goes in `TEXT` columns (encode/decode in
`utils/database.py`); there is no `now()` -- use
`DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))`.

History: 0001-0003 were Postgres (JSONB/TIMESTAMPTZ) until the 2026-10-09
move to SQLite, when they were rewritten once in the SQLite dialect (the
engine changed, so no existing database carried over).

## Current migrations

- `0001_initial_schema.sql` -- `runs`, `papers`, and 6 LLM-output cache tables.
- `0002_artifact_registry.sql` -- `research_artifacts` (FR-22).
- `0003_run_manifest.sql` -- `run_manifests` (FR-23).
- `0004_graph_snapshots.sql` -- `graph_snapshots` (cross-run knowledge graph;
  replaced ArcadeDB).
- `0005_projects.sql` -- `projects`, `runs.project_id` (existing runs move into
  the "Default project"), `project_files` + `run_files` (every file saved in a
  project folder), and `feedback` (per gap / proposal / run, keyed by the stable
  `gap_id`). Wrapped in one transaction because `ALTER TABLE ADD COLUMN` is
  not idempotent.
