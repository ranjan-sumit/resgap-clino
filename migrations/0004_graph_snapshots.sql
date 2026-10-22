-- Cross-run knowledge-graph snapshots (formerly ArcadeDB, Clinova Phase 3
-- Epic 3.1). One row per run holds the whole graph as JSON TEXT in the
-- {entities, relationships} shape pipeline/graph_builder.py produces. The
-- graph is only ever saved, loaded, listed and diffed -- never queried
-- natively -- so a graph database bought nothing here. Saving is a single
-- upsert, so a failed save can never leave a half-written snapshot.

CREATE TABLE IF NOT EXISTS graph_snapshots (
    run_id             TEXT PRIMARY KEY,
    name               TEXT,
    saved_at           TEXT NOT NULL,
    entity_count       INTEGER,
    relationship_count INTEGER,
    version            INTEGER,
    build_status       TEXT,
    quality_score      REAL,
    graph_json         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_graph_snapshots_saved ON graph_snapshots(saved_at DESC);
