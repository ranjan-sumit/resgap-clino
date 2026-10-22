-- Clinova Phase 4, Epic 4.2: Run Manifest (FR-23). Exact field list from
-- 06-versioning-lineage-architecture.md §3. `token_usage` is nullable and
-- expected to be NULL today -- no call site in this pipeline counts tokens
-- yet (see pipeline/agent_config.py's Epic 3.6 docstring for the same
-- honest-gap treatment already applied to AgentConfig's schema fields).
-- Not a foreign key to research_artifacts on purpose: a RunManifest is
-- itself recorded as one research_artifacts row (artifact_type='pipeline'),
-- but the manifest's own detail record needs to exist even if that
-- artifact-registry write fails for some reason -- the manifest is the
-- more load-bearing of the two records for run history/debugging.
-- SQLite dialect: the *_versions/_artifacts/_metrics/_results/warnings/
-- token_usage/parser_versions/search_providers columns are JSON TEXT;
-- academic_search_date is ISO-8601 TEXT.

CREATE TABLE IF NOT EXISTS run_manifests (
    run_id                    TEXT PRIMARY KEY,
    project_id                TEXT NOT NULL,
    input_corpus_version      TEXT,
    pipeline_version          TEXT,
    git_commit                TEXT,
    parser_versions           TEXT,
    reference_resolver_version TEXT,
    embedding_model_version   TEXT,
    reranker_version          TEXT,
    graph_builder_version     TEXT,
    graph_version             TEXT,
    prompt_bundle_version     TEXT,
    model_bundle_version      TEXT,
    search_strategy_version   TEXT,
    academic_search_date      TEXT,
    search_providers          TEXT,
    output_artifacts          TEXT,
    evaluation_metrics        TEXT,
    warnings                  TEXT,
    quality_gate_results      TEXT,
    run_duration_seconds      REAL,
    token_usage               TEXT,
    created_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_manifests_project ON run_manifests(project_id);
