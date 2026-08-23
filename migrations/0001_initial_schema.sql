-- Clinova Phase 4, Epic 4.1: Postgres port of the pre-existing SQLite schema
-- (utils/database.py, pre-migration). Forward-only -- see migrations/README.md.
--
-- One real, deliberate change from the SQLite version: `runs.results_gz BLOB`
-- (manually gzip-compressed JSON) becomes `runs.results_json JSONB` (native).
-- Postgres TOAST-compresses large JSONB values internally, so the manual
-- gzip step this code carried under SQLite is no longer doing useful work --
-- dropping it is a real simplification, not just a rename. Every other
-- table is a direct, unchanged port (SQLite TEXT/INTEGER map cleanly to
-- Postgres TEXT/INTEGER; no other column needed a type change).
--
-- Real, deliberate improvement #2: `papers.run_id` now has an ENFORCED
-- foreign key with ON DELETE CASCADE. SQLite declared this FK too, but
-- SQLite does not enforce foreign keys unless `PRAGMA foreign_keys=ON` is
-- set per-connection (it never was here) -- so delete_run() always had to
-- manually delete from `papers` before `runs` as a result. Postgres
-- enforces FKs by default; the cascade now does real work, and the manual
-- pre-delete in delete_run() becomes defensive-but-redundant, not required.

CREATE TABLE IF NOT EXISTS runs (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    domain       TEXT,
    interest     TEXT,
    n_papers     INTEGER,
    n_gaps       INTEGER,
    n_proposals  INTEGER,
    has_comp     INTEGER DEFAULT 0,
    results_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS papers (
    run_id   TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    filename TEXT,
    title    TEXT,
    tier     INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS wiki_pages (
    cache_key           TEXT PRIMARY KEY,
    content_hash        TEXT,
    domain_hash         TEXT,
    stage_logic_version INTEGER,
    wiki_json           TEXT
);

CREATE TABLE IF NOT EXISTS parameters (
    cache_key           TEXT PRIMARY KEY,
    content_hash        TEXT,
    stage_logic_version INTEGER,
    params_json         TEXT
);

CREATE TABLE IF NOT EXISTS docling_extractions (
    cache_key           TEXT PRIMARY KEY,
    content_hash        TEXT,
    stage_logic_version INTEGER,
    extraction_json     TEXT
);

CREATE TABLE IF NOT EXISTS evidence_objects (
    cache_key           TEXT PRIMARY KEY,
    content_hash        TEXT,
    stage_logic_version INTEGER,
    evidence_json       TEXT
);

CREATE TABLE IF NOT EXISTS "references" (
    cache_key           TEXT PRIMARY KEY,
    doi_or_title_hash   TEXT,
    stage_logic_version INTEGER,
    enriched_json       TEXT
);

CREATE TABLE IF NOT EXISTS gap_validations (
    cache_key           TEXT PRIMARY KEY,
    gap_hash            TEXT,
    domain_hash         TEXT,
    stage_logic_version INTEGER,
    validation_json     TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_papers_run   ON papers(run_id);
