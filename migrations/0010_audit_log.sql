-- Audit log: who did what to which run or project, and when. Append-only (the triggers refuse UPDATE and DELETE) and hash-chained:
-- each row's hash covers the previous row's hash, so removing or editing a row is detected by utils/audit_log.verify().
-- It holds ids, action names and short non-secret details; never paper text, model output or keys.

CREATE TABLE IF NOT EXISTS audit_log (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT '',
    target_id   TEXT NOT NULL DEFAULT '',
    detail      TEXT NOT NULL DEFAULT '{}',
    prev_hash   TEXT NOT NULL,
    hash        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_target ON audit_log(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action, seq);

CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
