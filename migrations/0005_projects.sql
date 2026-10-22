-- Projects: a named workspace that groups multiple analysis runs, owns a folder
-- on disk (data/projects/<folder>/) holding the uploaded papers and every
-- artifact each run produced, and collects user feedback on gaps and runs.
-- SQLite dialect; see migrations/README.md.
-- Wrapped in one transaction: ALTER TABLE ADD COLUMN is not idempotent, so a
-- failure partway must not leave the schema half-applied.

BEGIN;

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    folder      TEXT NOT NULL,            -- directory name under the projects root
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    archived    INTEGER NOT NULL DEFAULT 0
);

-- Runs recorded before projects existed (and any saved without one) belong to
-- the always-present default project.
INSERT OR IGNORE INTO projects (id, name, description, folder)
VALUES ('default', 'Default project', 'Analyses that were not assigned to a project.', 'default');

ALTER TABLE runs ADD COLUMN project_id TEXT REFERENCES projects(id);
UPDATE runs SET project_id = 'default' WHERE project_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id, created_at DESC);

-- Every file kept on disk for a project. rel_path is relative to the project's
-- folder. UNIQUE(project_id, rel_path) makes re-saving the same paper a no-op.
CREATE TABLE IF NOT EXISTS project_files (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('paper', 'results', 'report_html', 'report_pdf', 'manifest', 'other')),
    filename   TEXT NOT NULL,
    rel_path   TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (project_id, rel_path)
);
CREATE INDEX IF NOT EXISTS idx_project_files_project ON project_files(project_id, kind);

-- Which files a run used or produced. Papers are shared by many runs, so this
-- is a link table rather than a run_id column on project_files.
CREATE TABLE IF NOT EXISTS run_files (
    run_id  TEXT    NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    PRIMARY KEY (run_id, file_id)
);

-- User feedback, kept for later use by the Gap Challenger judge and the agents.
-- target_id is the stable gap_id for gaps (so feedback can follow a gap across
-- runs), a proposal's title/id for proposals, and '' for run-level feedback.
-- One row per (run, target): giving feedback again updates it.
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL CHECK (target_type IN ('gap', 'proposal', 'run')),
    target_id   TEXT NOT NULL DEFAULT '',
    target_label TEXT,                    -- gap/proposal title, for readable exports
    rating      INTEGER CHECK (rating IN (-1, 1)),   -- -1 not useful, 1 useful, NULL unrated
    reason      TEXT,
    comment     TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (run_id, target_type, target_id)
);
CREATE INDEX IF NOT EXISTS idx_feedback_project ON feedback(project_id, target_type);

COMMIT;
