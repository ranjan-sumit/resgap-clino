-- Background analysis jobs: a run executes in a worker thread and its progress is
-- kept here, so a refreshed or closed browser tab does not lose it and a restart
-- can tell which runs were cut off. SQLite dialect; see migrations/README.md.

BEGIN;

CREATE TABLE IF NOT EXISTS run_jobs (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id),
    name          TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
    progress_pct  INTEGER NOT NULL DEFAULT 0,
    message       TEXT NOT NULL DEFAULT '',
    stage_idx     INTEGER NOT NULL DEFAULT -1,
    stage_times   TEXT NOT NULL DEFAULT '{}',     -- JSON: {"<idx>": {"start": epoch, "end": epoch|null}}
    trace_json    TEXT NOT NULL DEFAULT '[]',     -- JSON list of trace rows
    warnings_json TEXT NOT NULL DEFAULT '[]',     -- JSON list of warning strings
    run_id        TEXT,                           -- the saved run, once done
    summary_json  TEXT,                           -- JSON: counts shown in the completion note
    error         TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    started_at    TEXT,
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at   TEXT,
    dismissed     INTEGER NOT NULL DEFAULT 0      -- the user has acknowledged the outcome
);
CREATE INDEX IF NOT EXISTS idx_run_jobs_project ON run_jobs(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_jobs_status ON run_jobs(status);

COMMIT;
