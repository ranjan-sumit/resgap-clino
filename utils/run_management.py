"""Managing saved runs: rename, archive, delete, merge duplicates, delete a project.

Every operation keeps the database and the project folder consistent, and nothing is destroyed without
a way back: archiving only hides a run, merging archives the duplicates, and deleting a project moves
its folder to `<projects>/_deleted/` instead of erasing it. A deployment that must really delete sets
RESGAP_ERASE_ON_DELETE=1: deletes then erase the folder, remove a run's files and empty the caches of derived results.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import stat
from datetime import datetime
from pathlib import Path

from utils import database as db
from utils import project_store


# ── rename ────────────────────────────────────────────────────────────────────────────────────
def rename_run(project_id: str, run_id: str, name: str) -> bool:
    """Renames the run in the database and in its manifest.json on disk (so the two agree)."""
    if not db.rename_run(run_id, name):
        return False
    try:
        path = project_store.project_dir(project_id) / "runs" / run_id / "manifest.json"
        if path.is_file():
            doc = json.loads(path.read_text(encoding="utf-8"))
            doc["run_name"] = name.strip()[:200]
            path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    except (OSError, ValueError):
        pass                      # the database is the source of truth; a stale file name is cosmetic
    return True


# ── what deleting would remove ────────────────────────────────────────────────────────────────
def run_footprint(project_id: str, run_id: str) -> dict:
    """Files saved for the run and feedback attached to it: what the user is told before a delete."""
    files = [f for f in db.list_project_files(project_id, run_id=run_id) if f["kind"] != "paper"]
    feedback = [f for f in db.list_feedback(run_id=run_id)]
    return {"files": [f["filename"] for f in files], "feedback": len(feedback)}


def erase_on_delete() -> bool:
    """A deployment policy (RESGAP_ERASE_ON_DELETE=1): deleting is permanent. A deleted project's folder is erased instead of
    kept in `_deleted`, a deleted run's files always go, and the caches of derived results are emptied."""
    return os.getenv("RESGAP_ERASE_ON_DELETE", "").strip().lower() in ("1", "true", "yes")


def _rmtree(path: Path) -> None:
    """Erase a folder, including read-only files (Windows refuses to delete those otherwise)."""
    def _writable(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=_writable)


def delete_run(project_id: str, run_id: str, remove_files: bool = False) -> None:
    """Deletes a run's database rows. Its files stay on disk unless `remove_files` (papers are never removed);
    with the erase policy the files always go and the derived-result caches are emptied too."""
    erase = erase_on_delete()
    remove_files = remove_files or erase
    if remove_files:
        folder = project_store.project_dir(project_id) / "runs" / run_id
        for f in db.list_project_files(project_id, run_id=run_id):
            if f["kind"] != "paper":
                _drop_file_row(project_id, f["id"])
        shutil.rmtree(folder, ignore_errors=True)
    db.delete_run(run_id)
    if erase:
        db.purge_derived_caches()


def _drop_file_row(project_id: str, file_id: int) -> None:
    conn = db._get_conn()
    try:
        conn.execute("DELETE FROM run_files WHERE file_id = ?", (file_id,))
        conn.execute("DELETE FROM project_files WHERE id = ? AND project_id = ?", (file_id, project_id))
        conn.commit()
    finally:
        conn.close()


# ── duplicates ────────────────────────────────────────────────────────────────────────────────
def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def signature(results: dict) -> tuple:
    """What makes two runs 'the same analysis': the papers and the set of gap titles."""
    papers = tuple(sorted(p.get("filename", "") for p in results.get("papers") or []))
    gaps = tuple(sorted(_norm_title(g.get("title", "")) for g in results.get("gaps") or []))
    return papers, gaps


def find_duplicate_groups(project_id: str) -> list[list[dict]]:
    """Groups of runs (metadata rows, newest first) with identical papers and gap titles. Runs with no
    gaps are never grouped: identical emptiness is not a duplicate."""
    groups: dict = {}
    for row in db.list_runs(limit=100000, project_id=project_id):
        results = db.load_run(row["id"], sections=False).get("results") or {}
        sig = signature(results)
        if sig[1]:
            groups.setdefault(sig, []).append(row)
    return [g for g in groups.values() if len(g) > 1]


def merge_runs(keep_id: str, drop_ids: list[str]) -> dict:
    """Folds duplicate runs into `keep_id`: Lab results move across when the kept run has none, feedback
    moves when it does not clash, and the duplicates are archived (not deleted). Returns what moved."""
    moved = {"lab": 0, "feedback": 0, "archived": 0}
    kept = db.load_run(keep_id, sections=False)
    conn = db._get_conn()
    try:
        for rid in drop_ids:
            if rid == keep_id:
                continue
            other = db.load_run(rid, sections=False)
            if other.get("comp_results") and not kept.get("comp_results"):
                db.attach_comp_results(keep_id, other["comp_results"])
                kept["comp_results"] = other["comp_results"]
                moved["lab"] += 1
            for fb in db.list_feedback(run_id=rid):
                try:
                    conn.execute("UPDATE feedback SET run_id = ? WHERE id = ?", (keep_id, fb["id"]))
                    moved["feedback"] += 1
                except sqlite3.IntegrityError:
                    pass                              # the kept run already has feedback on that target
            conn.execute("UPDATE runs SET archived = 1 WHERE id = ?", (rid,))
            moved["archived"] += 1
        conn.commit()
    finally:
        conn.close()
    return moved


def best_to_keep(group: list[dict]) -> dict:
    """The run to keep from a duplicate group: one with Lab results, else the newest."""
    return max(group, key=lambda r: (bool(r["has_comp"]), r["created_at"]))


# ── projects ──────────────────────────────────────────────────────────────────────────────────
def project_footprint(project_id: str) -> dict:
    """What deleting a project removes, for the confirmation."""
    runs = db.list_runs(limit=100000, project_id=project_id, include_archived=True)
    files = db.list_project_files(project_id)
    return {"runs": [r["name"] for r in runs], "n_papers": sum(1 for f in files if f["kind"] == "paper"),
            "n_files": len(files)}


def update_project(project_id: str, name: str, description: str, domain: str, interest: str) -> dict:
    """Edits a project and keeps its project.json in step."""
    project = db.update_project(project_id, name, description, domain, interest)
    try:
        path = project_store.project_dir(project_id) / "project.json"
        doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        doc.update({"id": project_id, "name": project["name"], "description": project["description"],
                    "domain": project["domain"], "interest": project["interest"]})
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    except (OSError, ValueError):
        pass
    return project


def deleted_folder() -> Path:
    return project_store.projects_root() / "_deleted"


def deleted_folder_footprint() -> dict:
    """What the `_deleted` folder holds: {"projects": n, "bytes": n}."""
    root = deleted_folder()
    if not root.is_dir():
        return {"projects": 0, "bytes": 0}
    return {"projects": sum(1 for p in root.iterdir() if p.is_dir()),
            "bytes": sum(f.stat().st_size for f in root.rglob("*") if f.is_file())}


def empty_deleted_folder() -> int:
    """Erases everything earlier project deletes moved aside. Returns how many project folders went."""
    n = deleted_folder_footprint()["projects"]
    if deleted_folder().is_dir():
        _rmtree(deleted_folder())
    return n


def delete_project(project_id: str, erase: bool | None = None) -> Path | None:
    """Deletes a project from the database. By default its folder moves to `_deleted/` (kept, so a mistake can be undone);
    with `erase` (or the RESGAP_ERASE_ON_DELETE policy) the folder is erased, folders of this project that an earlier delete
    left in `_deleted/` go too, and the caches of derived results are emptied. Returns where the folder went, or None when
    there was no folder or it was erased."""
    project = db.get_project(project_id)
    if project is None:
        raise ValueError(f"Unknown project: {project_id}")
    erase = erase_on_delete() if erase is None else erase
    folder = project_store.projects_root() / project["folder"]
    db.delete_project_rows(project_id)                  # raises for the default project, before anything moves
    if erase:
        if folder.exists():
            _rmtree(folder)
        trash = deleted_folder()
        if trash.is_dir():
            for old in trash.glob(f"{project['folder']}-*"):
                _rmtree(old)
        db.purge_derived_caches()
        return None
    if not folder.exists():
        return None
    target_dir = project_store.projects_root() / "_deleted"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{project['folder']}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.move(str(folder), str(target))
    return target
