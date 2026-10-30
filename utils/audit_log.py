"""Audit log: a tamper-evident record of who did what to which run or project.

Each event stores the time, the actor, an action name, the thing acted on (a type and an id) and a few short non-secret details.
Rows are chained: `hash = sha256(prev_hash + the row's fields)`, and the database refuses to update or delete a row, so an edit
made behind the app's back (or a removed row) shows up in `verify()`.

It never holds paper text, model output or keys: details are cut to short strings and any field whose name looks like a secret
is dropped. A failure to write is logged and returns False; it never stops the action that was being recorded.

The actor is `RESGAP_ACTOR` when set (a reverse proxy or sign-in layer can set it per user), otherwise "local".
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
from datetime import datetime, timezone

from utils import database as db

log = logging.getLogger(__name__)

GENESIS = "0" * 64
_SECRET_NAME = re.compile(r"(?i)key|secret|token|password|passwd|authorization|credential")
_MAX_VALUE = 200
_MAX_FIELDS = 12

# The actions the app records. A new action should be added here so the viewer can describe it.
ACTIONS = {
    "run.started": "Run started", "run.finished": "Run finished", "run.failed": "Run failed",
    "run.deleted": "Run deleted", "run.archived": "Run archived", "run.restored": "Run restored from archive",
    "project.created": "Project created", "project.deleted": "Project deleted", "project.erased": "Deleted files erased",
    "export.project_zip": "Project zip prepared", "export.report": "Report downloaded",
    "backup.created": "Backup created", "backup.restored": "Backup restored",
    "settings.provider": "Model assignment changed", "audit.exported": "Audit log exported",
}


def current_actor() -> str:
    return (os.getenv("RESGAP_ACTOR") or "local").strip()[:80] or "local"


def _clean_detail(detail: dict | None) -> dict:
    out = {}
    for k, v in list((detail or {}).items())[:_MAX_FIELDS]:
        if _SECRET_NAME.search(str(k)):
            continue
        if isinstance(v, (int, float, bool)) or v is None:
            out[str(k)] = v
        else:
            out[str(k)] = str(v)[:_MAX_VALUE]
    return out


def _digest(prev_hash: str, at: str, actor: str, action: str, target_type: str, target_id: str, detail: str) -> str:
    payload = json.dumps([prev_hash, at, actor, action, target_type, target_id, detail], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record(action: str, target_type: str = "", target_id: str = "", detail: dict | None = None, actor: str | None = None) -> bool:
    """Append one event. Returns False (and logs) if it could not be written."""
    try:
        db.init_db()
        at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        who = (actor or current_actor())[:80]
        det = json.dumps(_clean_detail(detail), ensure_ascii=False, sort_keys=True)
        conn = db._get_conn()
        try:
            conn.isolation_level = None                      # explicit transaction: the read of the last hash and the insert are one step
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
                prev = row["hash"] if row else GENESIS
                h = _digest(prev, at, who, action, str(target_type), str(target_id), det)
                conn.execute("INSERT INTO audit_log (at, actor, action, target_type, target_id, detail, prev_hash, hash) "
                             "VALUES (?,?,?,?,?,?,?,?)", (at, who, action, str(target_type), str(target_id), det, prev, h))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return True
    except Exception as exc:                                   # an audit failure must not break the action being audited
        log.warning("audit log write failed (%s): %s", action, exc)
        return False


def list_events(limit: int = 200, action: str | None = None, target_id: str | None = None, offset: int = 0) -> list[dict]:
    """Newest first."""
    db.init_db()
    sql, args = "SELECT * FROM audit_log", []
    where = []
    if action:
        where.append("action = ?"); args.append(action)
    if target_id:
        where.append("target_id = ?"); args.append(target_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY seq DESC LIMIT ? OFFSET ?"
    args += [int(limit), int(offset)]
    conn = db._get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def verify() -> dict:
    """Walk the whole chain. {"ok": bool, "count": n, "first_bad_seq": int | None, "problem": str}."""
    db.init_db()
    conn = db._get_conn()
    try:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY seq").fetchall()
    finally:
        conn.close()
    prev, prev_seq = GENESIS, None
    for r in rows:
        if prev_seq is not None and r["seq"] != prev_seq + 1:
            return {"ok": False, "count": len(rows), "first_bad_seq": prev_seq + 1,
                    "problem": f"Event {prev_seq + 1} is missing (a row was removed)."}
        if r["prev_hash"] != prev:
            return {"ok": False, "count": len(rows), "first_bad_seq": r["seq"], "problem": f"Event {r['seq']} does not follow the one before it."}
        if _digest(r["prev_hash"], r["at"], r["actor"], r["action"], r["target_type"], r["target_id"], r["detail"]) != r["hash"]:
            return {"ok": False, "count": len(rows), "first_bad_seq": r["seq"], "problem": f"Event {r['seq']} was changed after it was written."}
        prev, prev_seq = r["hash"], r["seq"]
    return {"ok": True, "count": len(rows), "first_bad_seq": None, "problem": ""}


def to_csv(events: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["seq", "at", "actor", "action", "target_type", "target_id", "detail", "hash"])
    for e in events:
        w.writerow([_csv_safe(e[c]) for c in ("seq", "at", "actor", "action", "target_type", "target_id", "detail", "hash")])
    return buf.getvalue()


def _csv_safe(value) -> str:
    """A spreadsheet runs a cell that starts with = + - @ as a formula; prefix such text so it opens as text."""
    s = str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def describe(action: str) -> str:
    return ACTIONS.get(action, action)
