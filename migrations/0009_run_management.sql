-- Runs can be archived (hidden from lists, kept on disk and in the database) instead of deleted.
-- SQLite dialect; ALTER TABLE ADD COLUMN is not idempotent, hence the transaction.

BEGIN;

ALTER TABLE runs ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_runs_archived ON runs(project_id, archived, created_at DESC);

COMMIT;
