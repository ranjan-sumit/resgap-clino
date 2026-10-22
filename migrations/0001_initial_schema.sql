-- Clinova Phase 4, Epic 4.1: run history + LLM-output cache tables.
-- Forward-only -- see migrations/README.md.
--
-- SQLite dialect (the project moved Postgres -> SQLite on 2026-10-09 so it
-- can run on Streamlit Cloud with no database server). `runs.results_json`
-- holds the whole results blob as JSON TEXT; utils/database.py encodes and
-- decodes it (Postgres used native JSONB here).
--
-- `papers.run_id` has an ENFORCED foreign key with ON DELETE CASCADE:
-- utils/database.py's _get_conn() sets PRAGMA foreign_keys = ON per
-- connection, which SQLite requires and does not do by default.

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
    results_json TEXT NOT NULL
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
