"""Backup and restore of everything the app keeps: the run database and the project folders.

A backup is one zip file:
    manifest.json        when it was made, what is inside, and a checksum of the database
    run_history.db       a consistent snapshot of the SQLite database (taken with SQLite's own backup API,
                         so it is safe while the app is running)
    projects/...         every file under the projects folder (uploaded papers, results, reports)

Restore verifies the checksum first, never writes outside the target folders, and moves whatever it replaces
aside (`*.before-restore`) instead of deleting it.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from utils import audit_log
from utils import database as db

BACKUP_FORMAT = 1
DB_MEMBER = "run_history.db"
PROJECTS_PREFIX = "projects/"
_NAME_PREFIX = "resgap-backup-"


class BackupError(Exception):
    """A backup that cannot be made, read or trusted."""


def backup_dir() -> Path:
    override = os.environ.get("RESGAP_BACKUP_DIR")
    path = Path(override) if override else Path(db._db_path()).resolve().parent / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _projects_root() -> Path:
    from utils import project_store
    return project_store.projects_root()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_database(target: Path) -> None:
    """Copy the live database into `target` using SQLite's online backup (consistent, even mid-write)."""
    source_path = db._db_path()
    if not Path(source_path).exists():
        db.init_db()
    src = sqlite3.connect(source_path, timeout=30)
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def create_backup(dest_dir: str | Path | None = None, keep: int | None = 7) -> Path:
    """Write a new backup zip and return its path. With `keep`, older automatic backups beyond that many are deleted."""
    dest = Path(dest_dir) if dest_dir else backup_dir()
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = dest / f"{_NAME_PREFIX}{stamp}.zip"
    n = 1
    while out.exists():
        n += 1
        out = dest / f"{_NAME_PREFIX}{stamp}-{n}.zip"
    root = _projects_root()
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / DB_MEMBER
        _snapshot_database(snap)
        files = [p for p in sorted(root.rglob("*")) if p.is_file()]
        manifest = {
            "format": BACKUP_FORMAT,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "database_sha256": _sha256_file(snap),
            "database_bytes": snap.stat().st_size,
            "project_files": len(files),
            "project_bytes": sum(p.stat().st_size for p in files),
        }
        partial = out.with_suffix(".zip.partial")
        try:
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))
                zf.write(snap, DB_MEMBER)
                for p in files:
                    zf.write(p, PROJECTS_PREFIX + p.relative_to(root).as_posix())
            partial.replace(out)                       # a half-written backup never carries the final name
        finally:
            partial.unlink(missing_ok=True)
    if keep:
        _prune(dest, keep)
    audit_log.record("backup.created", "backup", out.name, {"project_files": manifest["project_files"], "kept": keep or "all"})
    return out


def _prune(dest: Path, keep: int) -> None:
    mine = sorted(dest.glob(f"{_NAME_PREFIX}*.zip"))
    for old in mine[:-keep]:
        old.unlink(missing_ok=True)


def list_backups(dest_dir: str | Path | None = None) -> list[Path]:
    dest = Path(dest_dir) if dest_dir else backup_dir()
    return sorted(dest.glob(f"{_NAME_PREFIX}*.zip"), reverse=True)


def read_manifest(zip_path: str | Path) -> dict:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return json.loads(zf.read("manifest.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
        raise BackupError(f"Not a readable backup: {e}") from e


def verify_backup(zip_path: str | Path) -> dict:
    """Check the backup is whole: readable, with a database whose checksum matches. Returns the manifest."""
    manifest = read_manifest(zip_path)
    if manifest.get("format") != BACKUP_FORMAT:
        raise BackupError(f"Unsupported backup format {manifest.get('format')!r}.")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            if zf.testzip() is not None:
                raise BackupError("The backup file is damaged.")
            h = hashlib.sha256(zf.read(DB_MEMBER)).hexdigest()
    except (KeyError, zipfile.BadZipFile) as e:
        raise BackupError(f"The backup is incomplete: {e}") from e
    if h != manifest.get("database_sha256"):
        raise BackupError("The database inside the backup does not match its checksum.")
    return manifest


def _safe_target(root: Path, member: str) -> Path:
    target = (root / member).resolve()
    if root.resolve() != target and root.resolve() not in target.parents:
        raise BackupError(f"Refusing to write outside the target folder: {member}")
    return target


def restore_backup(zip_path: str | Path, db_path: str | Path | None = None,
                   projects_dir: str | Path | None = None, overwrite: bool = False) -> dict:
    """Put a backup back. Without `overwrite`, refuses when a database or project files already exist at the targets.
    With it, the existing database and projects folder are moved aside (`*.before-restore`), never deleted."""
    verify_backup(zip_path)
    db_target = Path(db_path) if db_path else Path(db._db_path())
    proj_target = Path(projects_dir) if projects_dir else _projects_root()
    has_projects = proj_target.exists() and any(proj_target.rglob("*"))
    if (db_target.exists() or has_projects) and not overwrite:
        raise BackupError("Data already exists at the restore target. Use overwrite to replace it "
                          "(the current data is kept as *.before-restore).")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    moved = []
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_target) + suffix)
        if p.exists():
            aside = Path(str(p) + f".before-restore-{stamp}")
            p.replace(aside)
            moved.append(aside)
    if has_projects:
        aside = proj_target.with_name(proj_target.name + f".before-restore-{stamp}")
        proj_target.replace(aside)
        moved.append(aside)
    db_target.parent.mkdir(parents=True, exist_ok=True)
    proj_target.mkdir(parents=True, exist_ok=True)
    n_files = 0
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(DB_MEMBER) as src, open(db_target, "wb") as out:
            shutil.copyfileobj(src, out)
        for info in zf.infolist():
            if not info.filename.startswith(PROJECTS_PREFIX) or info.is_dir():
                continue
            target = _safe_target(proj_target, info.filename[len(PROJECTS_PREFIX):])
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            n_files += 1
    audit_log.record("backup.restored", "backup", Path(zip_path).name, {"project_files": n_files, "overwrote": bool(moved)})
    return {"database": str(db_target), "projects": str(proj_target), "project_files": n_files,
            "moved_aside": [str(m) for m in moved]}


def backup_bytes() -> tuple[str, bytes]:
    """A fresh backup as (file name, bytes), for a download button. Nothing is kept on disk."""
    with tempfile.TemporaryDirectory() as tmp:
        path = create_backup(tmp, keep=None)
        return path.name, path.read_bytes()
