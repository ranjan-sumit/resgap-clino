-- Large, rarely-needed parts of a saved run live beside it instead of inside the
-- results JSON, so opening a run reads only the part the screen needs (paper
-- section text is only used by the Computational Lab). SQLite dialect.

BEGIN;

CREATE TABLE IF NOT EXISTS run_blobs (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    name   TEXT NOT NULL,                      -- e.g. 'paper_sections'
    data   TEXT NOT NULL,                      -- JSON
    PRIMARY KEY (run_id, name)
);

COMMIT;
