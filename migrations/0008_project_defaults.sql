-- A project remembers the research setup it was created with, so "New analysis" can start
-- from it. SQLite dialect; ALTER TABLE ADD COLUMN is not idempotent, hence the transaction.

BEGIN;

ALTER TABLE projects ADD COLUMN domain   TEXT NOT NULL DEFAULT '';
ALTER TABLE projects ADD COLUMN interest TEXT NOT NULL DEFAULT '';

COMMIT;
