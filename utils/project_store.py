"""
Project folders (the filesystem half of Projects; the database half is in
utils/database.py, schema in migrations/0005_projects.sql).

Creating a project creates a folder, and everything an analysis produces is
kept in it, so a project is a self-contained, inspectable unit:

    <projects root>/<name-slug>-<id>/
        project.json                       name, description, id, created
        papers/<hash8>_<filename>.pdf      uploaded papers, de-duplicated by content
        runs/<run_id>/results.json         the full results
                      report.html          the enterprise report (deterministic narrative)
                      report.pdf
                      manifest.json        what produced the run, plus a file list

The projects root sits next to the database file (data/projects by default),
so a test that points the database at a temp file automatically gets a temp
projects root too. Override with $RESGAP_PROJECTS_DIR.

Every path built from user input (project names, uploaded filenames, run ids)
is sanitized and checked to stay inside the project folder.
"""
import hashlib
import io
import json
import os
import re
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from utils import audit_log
from utils import database as db

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def projects_root() -> Path:
    override = os.environ.get("RESGAP_PROJECTS_DIR")
    root = Path(override) if override else Path(db._db_path()).resolve().parent / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:40].strip("-") or "project"


def safe_filename(name: str, default: str = "paper.pdf") -> str:
    """The base name only (no directories), with anything that is not a letter,
    digit, dot, dash, underscore or space replaced, never empty or dot-only."""
    base = Path(str(name or "").replace("\\", "/")).name
    base = re.sub(r"[^\w.\- ]+", "_", base, flags=re.UNICODE).strip(" .")
    return base[:120] or default


def _inside(root: Path, candidate: Path) -> Path:
    """Resolves `candidate` and refuses it if it is not within `root`."""
    root_r, cand_r = root.resolve(), candidate.resolve()
    if cand_r != root_r and root_r not in cand_r.parents:
        raise ValueError(f"Path escapes the project folder: {candidate}")
    return cand_r


def _make_subdirs(folder: Path) -> None:
    (folder / "papers").mkdir(parents=True, exist_ok=True)
    (folder / "runs").mkdir(parents=True, exist_ok=True)


def project_dir(project_id: str) -> Path:
    """The project's folder (created if it is missing, e.g. after the disk was
    wiped but the database survived)."""
    project = db.get_project(project_id)
    if not project:
        raise ValueError(f"Unknown project: {project_id}")
    folder = _inside(projects_root(), projects_root() / project["folder"])
    _make_subdirs(folder)
    return folder


def create_project(name: str, description: str = "", domain: str = "", interest: str = "") -> dict:
    """Creates the project's folder and database row; returns the project row
    plus its absolute `path`."""
    name = (name or "").strip()
    if not name:
        raise ValueError("A project needs a name.")
    project_id = uuid.uuid4().hex[:8]
    folder_name = f"{_slug(name)}-{project_id}"
    folder = _inside(projects_root(), projects_root() / folder_name)
    _make_subdirs(folder)
    try:
        project = db.insert_project(project_id, name, description, folder_name, domain, interest)
        (folder / "project.json").write_text(json.dumps({
            "id": project_id, "name": project["name"], "description": project["description"],
            "domain": project["domain"], "interest": project["interest"],
            "created_at": project["created_at"],
        }, indent=2), encoding="utf-8")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)   # never leave a folder with no project behind
        raise
    audit_log.record("project.created", "project", project_id, {"domain": domain})
    return {**project, "path": str(folder)}


def project_path(project_id: str) -> str:
    return str(project_dir(project_id))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_file(project_id: str, folder: Path, rel_path: str, data: bytes, kind: str,
                filename: str | None = None) -> dict:
    target = _inside(folder, folder / rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    sha = _sha256(data)
    file_id = db.add_project_file(project_id, kind, filename or target.name,
                                  target.relative_to(folder.resolve()).as_posix(), sha, len(data))
    return {"id": file_id, "kind": kind, "filename": filename or target.name,
            "rel_path": target.relative_to(folder.resolve()).as_posix(), "sha256": sha, "size_bytes": len(data)}


def save_papers(project_id: str, papers: list[tuple[str, bytes]]) -> list[int]:
    """Keeps the uploaded PDFs in the project's papers/ folder, named by a
    content-hash prefix so uploading the same paper again does not duplicate
    it. Returns the project_files ids, in input order."""
    folder = project_dir(project_id)
    ids = []
    for filename, content in papers:
        sha = _sha256(content)
        safe = safe_filename(filename)
        rel = f"papers/{sha[:8]}_{safe}"
        # Same bytes under another name: reuse the file already stored (the
        # hash prefix identifies content), so a paper is only kept once.
        existing = next((p for p in sorted((folder / "papers").glob(f"{sha[:8]}_*")) if p.is_file()
                        and _sha256(p.read_bytes()) == sha), None)
        if existing is not None:
            rel, safe = f"papers/{existing.name}", existing.name.split("_", 1)[1]
        target = _inside(folder, folder / rel)
        if not target.exists():
            target.write_bytes(content)
        ids.append(db.add_project_file(project_id, "paper", safe, rel, sha, len(content)))
    return ids


def write_run_artifacts(project_id: str, run_id: str, results: dict, context: dict, *,
                        paper_file_ids: list[int] = (), manifest: dict | None = None,
                        make_reports: bool = True, call_log_jsonl: str | None = None) -> list[dict]:
    """Writes a finished run's artifacts into runs/<run_id>/ and records each
    one (linking the run to them and to the papers it used). The reports are
    best-effort: a report failure is noted in the manifest and never loses the
    results. Returns the artifact file rows."""
    if not _RUN_ID_RE.match(run_id or ""):
        raise ValueError(f"Unsafe run id: {run_id!r}")
    folder = project_dir(project_id)
    base = f"runs/{run_id}"
    written, report_status = [], {}

    written.append(_write_file(project_id, folder, f"{base}/results.json",
                               json.dumps(results, default=str, indent=1).encode("utf-8"), "results"))

    if make_reports:
        try:
            from utils.export import (generate_report_narrative, to_enterprise_html_report,
                                      to_enterprise_pdf_report)
            narrative = generate_report_narrative(results, context, client=None)   # deterministic, no LLM call
            written.append(_write_file(project_id, folder, f"{base}/report.html",
                                       to_enterprise_html_report(results, context, narrative=narrative).encode("utf-8"),
                                       "report_html"))
            report_status["html"] = "ok"
            try:
                written.append(_write_file(project_id, folder, f"{base}/report.pdf",
                                           to_enterprise_pdf_report(results, context, narrative=narrative), "report_pdf"))
                report_status["pdf"] = "ok"
            except Exception as e:
                report_status["pdf"] = f"failed: {type(e).__name__}: {e}"
        except Exception as e:
            report_status["html"] = f"failed: {type(e).__name__}: {e}"

    if call_log_jsonl:
        written.append(_write_file(project_id, folder, f"{base}/llm_calls.jsonl",
                                   call_log_jsonl.encode("utf-8"), "other"))

    manifest_doc = {
        "run_id": run_id, "project_id": project_id,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "context": {k: context.get(k) for k in ("domain", "interest", "gap_type")},
        "reports": report_status,
        "files": [{k: f[k] for k in ("rel_path", "kind", "sha256", "size_bytes")} for f in written],
        **(manifest or {}),
    }
    written.append(_write_file(project_id, folder, f"{base}/manifest.json",
                               json.dumps(manifest_doc, default=str, indent=2).encode("utf-8"), "manifest"))

    for f in written:
        db.link_run_file(run_id, f["id"])
    for file_id in paper_file_ids:
        db.link_run_file(run_id, file_id)
    return written


def save_report(project_id: str, run_id: str, html: str, pdf: bytes | None = None) -> list[dict]:
    """Saves a run's final report into runs/<run_id>/ as report.html (and
    report.pdf), replacing the automatic one written when the run finished.
    One report per run. Returns the file rows."""
    if not _RUN_ID_RE.match(run_id or ""):
        raise ValueError(f"Unsafe run id: {run_id!r}")
    folder = project_dir(project_id)
    base = f"runs/{run_id}"
    written = [_write_file(project_id, folder, f"{base}/report.html", html.encode("utf-8"), "report_html")]
    if pdf:
        written.append(_write_file(project_id, folder, f"{base}/report.pdf", pdf, "report_pdf"))
    for f in written:
        db.link_run_file(run_id, f["id"])
    return written


def refresh_run_results(project_id: str, run_id: str, results: dict, context: dict,
                        comp_results: dict | None = None) -> list[dict]:
    """Re-writes a run's results.json (now including Computational Lab output)
    and its deterministic report. Best-effort on the reports, like
    write_run_artifacts; the manifest is left as it was."""
    if not _RUN_ID_RE.match(run_id or ""):
        raise ValueError(f"Unsafe run id: {run_id!r}")
    folder = project_dir(project_id)
    base = f"runs/{run_id}"
    payload = {**results, "computational_lab": comp_results} if comp_results else results
    written = [_write_file(project_id, folder, f"{base}/results.json",
                           json.dumps(payload, default=str, indent=1).encode("utf-8"), "results")]
    try:
        from utils.export import (generate_report_narrative, to_enterprise_html_report,
                                  to_enterprise_pdf_report)
        narrative = generate_report_narrative(results, context, client=None)
        written.append(_write_file(project_id, folder, f"{base}/report.html",
                                   to_enterprise_html_report(results, context, narrative=narrative,
                                                             comp_results=comp_results).encode("utf-8"),
                                   "report_html"))
        try:
            written.append(_write_file(project_id, folder, f"{base}/report.pdf",
                                       to_enterprise_pdf_report(results, context, narrative=narrative,
                                                                comp_results=comp_results), "report_pdf"))
        except Exception:
            pass
    except Exception:
        pass
    for f in written:
        db.link_run_file(run_id, f["id"])
    return written


def list_papers(project_id: str) -> list[dict]:
    """The papers kept in a project, oldest first, each with the number of runs
    that used it. Files whose PDF is no longer on disk are left out."""
    folder = project_dir(project_id)
    out = []
    for f in db.list_project_files(project_id, kind="paper"):
        try:
            if not _inside(folder, folder / f["rel_path"]).is_file():
                continue
        except ValueError:
            continue
        out.append({**f, "kb": max(1, f["size_bytes"] // 1024)})
    return out


def read_papers(project_id: str, file_ids: list[int]) -> list[tuple[str, bytes]]:
    """(filename, bytes) for the chosen stored papers, in the order given."""
    by_id = {p["id"]: p for p in list_papers(project_id)}
    result = []
    for fid in file_ids:
        p = by_id.get(fid)
        if p is None:
            raise ValueError(f"Paper {fid} is not stored in this project.")
        result.append((p["filename"], read_project_file(project_id, p["rel_path"])))
    return result


def combine_papers(uploaded: list[tuple[str, bytes]], stored: list[tuple[str, bytes]],
                   limit: int = 5) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Uploads plus chosen stored papers as one list: the same file chosen twice
    (or uploaded again) counts once, and anything beyond `limit` is named in a notice."""
    notices, seen, out = [], {}, []
    for name, data in [*stored, *uploaded]:
        sha = _sha256(data)
        if sha in seen:
            notices.append(f"'{name}' is the same file as '{seen[sha]}' and is counted once.")
            continue
        seen[sha] = name
        out.append((name, data))
    if len(out) > limit:
        notices.append(f"At most {limit} papers per run; not included: "
                       + ", ".join(f"'{n}'" for n, _ in out[limit:]) + ".")
        out = out[:limit]
    return out, notices


def read_project_file(project_id: str, rel_path: str) -> bytes:
    folder = project_dir(project_id)
    return _inside(folder, folder / rel_path).read_bytes()


CHECKSUMS_NAME = "CHECKSUMS.sha256"


def build_project_zip(project_id: str) -> bytes:
    """The whole project as one zip: its folder plus database_export.json (the project row, its runs' metadata, file list
    and all feedback), so the details held in the database travel with the files, and CHECKSUMS.sha256 (one line per
    file, in the format `sha256sum -c` reads) so a copy can be checked later. Links inside the folder are not followed:
    only real files go in."""
    folder = project_dir(project_id)
    export = {
        "format": 1,
        "exported_at": db.utc_now_iso(),
        "project": db.get_project(project_id),
        "runs": db.list_runs(limit=100000, project_id=project_id),
        "files": db.list_project_files(project_id),
        "feedback": db.list_feedback(project_id=project_id),
    }
    members: list[tuple[str, bytes]] = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        members.append((path.relative_to(folder).as_posix(), path.read_bytes()))
    members.append(("database_export.json", json.dumps(export, default=str, indent=2).encode("utf-8")))
    checksums = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in members)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members:
            z.writestr(name, data)
        z.writestr(CHECKSUMS_NAME, checksums)
    return buf.getvalue()


def verify_project_zip(data: bytes) -> list[str]:
    """Problems found in a project zip made by build_project_zip: a missing or changed file, a file the checksums do not
    list, or no checksum file at all. An empty list means the zip is as it was exported."""
    problems = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return ["not a readable zip file"]
    with z:
        if (bad := z.testzip()) is not None:
            problems.append(f"damaged file inside the zip: {bad}")
        if CHECKSUMS_NAME not in z.namelist():
            return problems + [f"{CHECKSUMS_NAME} is missing"]
        listed = {}
        for line in z.read(CHECKSUMS_NAME).decode("utf-8").splitlines():
            digest, _, name = line.partition("  ")
            if digest and name:
                listed[name] = digest
        for name, digest in listed.items():
            if name not in z.namelist():
                problems.append(f"missing: {name}")
            elif hashlib.sha256(z.read(name)).hexdigest() != digest:
                problems.append(f"changed: {name}")
        for name in z.namelist():
            if name != CHECKSUMS_NAME and name not in listed:
                problems.append(f"not listed in the checksums: {name}")
    return problems
