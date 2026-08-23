# Migrations

Forward-only SQL migrations for the Postgres database (Clinova Phase 4,
Epic 4.1, ADR-005/FR-21: "nothing scientifically load-bearing is
overwritten in place"). No Alembic/SQLAlchemy -- hand-rolled, matching
`utils/database.py`'s existing raw-SQL style rather than pulling in an ORM
this codebase doesn't otherwise use.

## How it works

`utils/database.py`'s `init_db()` calls `_apply_migrations()` on every
connection setup. It tracks applied migrations in a `schema_migrations`
table and applies any `*.sql` file in this directory, in filename order,
that isn't already recorded there. Idempotent -- safe to call on every
request, safe to re-run after adding a new migration file.

## Adding a new migration

Create a new file named `NNNN_description.sql` (four-digit, zero-padded,
strictly increasing) with `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE`
statements. Never edit an already-applied migration file in place -- a
correction is a new migration, same principle as this project's own
`stage_logic_version` cache-busting convention and the Research Artifact
Registry's own immutable-versions rule.

## Current migrations

- `0001_initial_schema.sql` -- the 8 tables ported from the pre-Phase-4
  SQLite backend (`runs`, `papers`, and 6 LLM-output cache tables).
- `0002_artifact_registry.sql` -- `research_artifacts` (FR-22).
- `0003_run_manifest.sql` -- `run_manifests` (FR-23).
