-- Clinova Phase 4, Epic 4.1: Research Artifact Registry (FR-22, ADR-005).
-- Exact schema from 06-versioning-lineage-architecture.md §2 -- one table
-- covering every artifact_type via a discriminator column, per-type detail
-- living in `metadata` (JSON TEXT; the doc does not define a separate table
-- per artifact type; only the Run Manifest gets its own dedicated detail
-- table, see 0003_run_manifest.sql). SQLite dialect.

CREATE TABLE IF NOT EXISTS research_artifacts (
    artifact_id      TEXT PRIMARY KEY,
    artifact_type    TEXT NOT NULL CHECK (artifact_type IN (
        'corpus', 'paper_extraction', 'reference_set', 'evidence_set',
        'embedding_model', 'vector_index', 'graph', 'graph_builder',
        'search_strategy', 'search_snapshot', 'prompt_bundle', 'model_bundle',
        'agent_definitions', 'pipeline', 'gap_set', 'proposal_set', 'report',
        'evaluation_benchmark'
    )),
    artifact_version TEXT NOT NULL,
    schema_version   TEXT,
    parent_artifact  TEXT REFERENCES research_artifacts(artifact_id),
    project_id       TEXT NOT NULL,
    run_id           TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    content_hash     TEXT NOT NULL,
    storage_uri      TEXT,
    -- Lifecycle per 06-versioning-lineage-architecture.md §2:
    -- EXPERIMENTAL -> CANDIDATE -> CHAMPION, either -> ARCHIVED.
    status           TEXT NOT NULL DEFAULT 'EXPERIMENTAL' CHECK (status IN (
        'EXPERIMENTAL', 'CANDIDATE', 'CHAMPION', 'ARCHIVED'
    )),
    metadata         TEXT
);

CREATE INDEX IF NOT EXISTS idx_artifacts_type    ON research_artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS idx_artifacts_project ON research_artifacts(project_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_run     ON research_artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_status  ON research_artifacts(status);
