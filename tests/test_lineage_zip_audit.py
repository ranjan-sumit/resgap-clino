"""PR-22g: lineage hashes cover the real content and can be checked; the project zip carries checksums."""
import copy
import io
import json
import os
import zipfile
from pathlib import Path

import pytest

import utils.database as db
from pipeline import lineage as ln
from tests.fixtures.make_golden_run import golden_results, seed_run
from utils import project_store

ROOT = Path(__file__).resolve().parent.parent


def _record(run_id, res, source_hashes=None, project_id=None):
    return ln.record_run_lineage(
        run_id, project_id or db.DEFAULT_PROJECT_ID,
        papers=res["papers"], wiki=res.get("wiki") or {"pages": []}, ref_papers=res.get("ref_papers") or [],
        evidence_objects=res.get("evidence_objects") or {}, graph=res.get("graph"), gaps=res.get("gaps"),
        proposals=res.get("proposals"), source_hashes=source_hashes)


def _hashes(run_id):
    return {r["artifact_type"] + (":" + r["metadata"].get("filename", "") if r["artifact_type"] == "paper_extraction" else ""):
            r["content_hash"] for r in db.list_artifacts(run_id=run_id)}


def test_artifacts_can_be_listed_for_one_run(isolated_env):
    a, b = seed_run(golden_results(), name="a"), seed_run(golden_results(), name="b")
    _record(a, golden_results())
    _record(b, golden_results())
    mine = db.list_artifacts(run_id=a)
    assert mine and all(r["run_id"] == a for r in mine) and len(db.list_artifacts()) > len(mine)


# ── the hashes change when the content does ───────────────────────────────────────────────────
def test_two_different_pdfs_with_the_same_name_and_length_get_different_hashes(isolated_env):
    res = golden_results()
    a, b = seed_run(res, name="a"), seed_run(res, name="b")
    name = res["papers"][0]["filename"]
    _record(a, res, source_hashes={name: "aa" * 32})
    _record(b, res, source_hashes={name: "bb" * 32})
    ha, hb = _hashes(a), _hashes(b)
    assert ha["paper_extraction:" + name] != hb["paper_extraction:" + name] and ha["corpus"] != hb["corpus"]


@pytest.mark.parametrize("edit,artifact", [
    (lambda r: r["graph"]["relationships"][0].__setitem__("relation", "changed_relation"), "graph"),
    (lambda r: r["gaps"][0].__setitem__("description", "a different description"), "gap_set"),
    (lambda r: r["gaps"][0].__setitem__("validation_status", "solved"), "gap_set"),
    (lambda r: r["proposals"][0].__setitem__("methodology", "a different method"), "proposal_set"),
])
def test_a_change_to_the_saved_content_changes_that_artifacts_hash(isolated_env, edit, artifact):
    res = golden_results()
    changed = copy.deepcopy(res)
    edit(changed)
    a, b = seed_run(res, name="a"), seed_run(changed, name="b")
    _record(a, res)
    _record(b, changed)
    assert _hashes(a)[artifact] != _hashes(b)[artifact]


def test_the_same_content_gives_the_same_hash(isolated_env):
    res = golden_results()
    a, b = seed_run(res, name="a"), seed_run(res, name="b")
    _record(a, res, source_hashes={res["papers"][0]["filename"]: "cc" * 32})
    _record(b, res, source_hashes={res["papers"][0]["filename"]: "cc" * 32})
    ha, hb = _hashes(a), _hashes(b)
    assert {k: ha[k] for k in ("graph", "gap_set", "proposal_set")} == {k: hb[k] for k in ("graph", "gap_set", "proposal_set")}


# ── checking a run against its lineage ────────────────────────────────────────────────────────
def test_a_run_whose_results_are_unchanged_verifies(isolated_env):
    res = golden_results()
    rid = seed_run(res, name="ok")
    _record(rid, res)
    out = ln.verify_lineage(rid)
    assert out["mismatches"] == [] and {"graph", "gap_set", "proposal_set"} <= set(out["checked"])


def test_results_that_differ_from_what_the_lineage_recorded_are_reported(isolated_env):
    res = golden_results()
    tampered = copy.deepcopy(res)
    tampered["gaps"][0]["title"] = "A gap that was edited after the run"
    rid = seed_run(tampered, name="edited")            # what is saved
    _record(rid, res)                                  # what the run recorded
    out = ln.verify_lineage(rid)
    assert [m["artifact_type"] for m in out["mismatches"]] == ["gap_set"]


def test_a_replaced_pdf_is_reported(isolated_env):
    project = project_store.create_project("P", "d", "healthcare", "")
    ids = project_store.save_papers(project["id"], [("a.pdf", b"%PDF-1.4 original")])
    res = golden_results()
    res["papers"] = [res["papers"][0]]
    rid = seed_run(res, name="x", project_id=project["id"])
    conn = db._get_conn()
    conn.execute("INSERT OR IGNORE INTO run_files (run_id, file_id) VALUES (?, ?)", (rid, ids[0]))
    conn.commit()
    conn.close()
    res["papers"][0]["filename"] = "a.pdf"
    _record(rid, res, source_hashes={"a.pdf": "00" * 32}, project_id=project["id"])      # the run read a different PDF
    out = ln.verify_lineage(rid)
    assert any("a.pdf" in m["detail"] for m in out["mismatches"])


def test_an_artifact_recorded_before_hashes_covered_the_content_is_unverifiable_not_fine(isolated_env):
    res = golden_results()
    rid = seed_run(res, name="old")
    _record(rid, res)
    conn = db._get_conn()
    for (aid, meta) in conn.execute("SELECT artifact_id, metadata FROM research_artifacts WHERE run_id = ?", (rid,)).fetchall():
        m = json.loads(meta) if meta else {}
        m.pop("lineage_schema", None)
        conn.execute("UPDATE research_artifacts SET metadata = ? WHERE artifact_id = ?", (json.dumps(m), aid))
    conn.commit()
    conn.close()
    out = ln.verify_lineage(rid)
    assert out["checked"] == [] or "graph" not in out["checked"]
    assert {"graph", "gap_set", "proposal_set"} <= set(out["unverifiable"]) and out["mismatches"] == []


def test_verifying_an_unknown_run_is_an_error(isolated_env):
    db.init_db()
    with pytest.raises(ValueError):
        ln.verify_lineage("nope")


def test_the_pipeline_passes_the_hashes_of_the_pdfs_it_read():
    src = (ROOT / "pipeline" / "run_pipeline.py").read_text(encoding="utf-8")
    assert "source_hashes={fn: hashlib.sha256(data).hexdigest() for fn, data in papers}" in src


# ── the project zip ────────────────────────────────────────────────────────────────────────────
def _project(tmp=None):
    project = project_store.create_project("Zip test", "d", "healthcare", "")
    project_store.save_papers(project["id"], [("a.pdf", b"%PDF-1.4 a"), ("b.pdf", b"%PDF-1.4 b")])
    rid = seed_run(golden_results(), name="r", project_id=project["id"])
    project_store.write_run_artifacts(project["id"], rid, golden_results(), {}, make_reports=False)
    return project


def _rewrite(data, change):
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as dst:
        members = {n: src.read(n) for n in src.namelist()}
        for name, content in change(members).items():
            dst.writestr(name, content)
    return out.getvalue()


def test_the_zip_has_a_checksum_list_that_verifies(isolated_env):
    data = project_store.build_project_zip(_project()["id"])
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert project_store.CHECKSUMS_NAME in names and "database_export.json" in names
    assert project_store.verify_project_zip(data) == []


def test_the_export_says_when_it_was_made_and_in_what_format(isolated_env):
    data = project_store.build_project_zip(_project()["id"])
    export = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("database_export.json"))
    assert export["format"] == 1 and export["exported_at"].endswith("Z")


def test_a_changed_missing_or_extra_file_is_found(isolated_env):
    data = project_store.build_project_zip(_project()["id"])
    changed = _rewrite(data, lambda m: {**m, "project.json": b"{}"})
    assert any(p.startswith("changed: project.json") for p in project_store.verify_project_zip(changed))
    removed = _rewrite(data, lambda m: {k: v for k, v in m.items() if k != "database_export.json"})
    assert "missing: database_export.json" in project_store.verify_project_zip(removed)
    extra = _rewrite(data, lambda m: {**m, "extra.txt": b"x"})
    assert "not listed in the checksums: extra.txt" in project_store.verify_project_zip(extra)
    unchecked = _rewrite(data, lambda m: {k: v for k, v in m.items() if k != project_store.CHECKSUMS_NAME})
    assert project_store.CHECKSUMS_NAME in project_store.verify_project_zip(unchecked)[0]
    assert project_store.verify_project_zip(b"not a zip") == ["not a readable zip file"]


def test_a_link_inside_the_project_folder_is_not_followed(isolated_env, tmp_path):
    project = _project()
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("do not export me")
    link = project_store.project_dir(project["id"]) / "link.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not allow creating links")
    data = project_store.build_project_zip(project["id"])
    z = zipfile.ZipFile(io.BytesIO(data))
    assert "link.txt" not in z.namelist() and b"do not export me" not in b"".join(z.read(n) for n in z.namelist())


def test_the_zip_contains_no_key_and_no_local_path(isolated_env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyDUMMYDUMMYDUMMYDUMMYDUMMY12345")
    data = project_store.build_project_zip(_project()["id"])
    z = zipfile.ZipFile(io.BytesIO(data))
    text = " ".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith((".json", ".jsonl", ".md", ".sha256")))
    assert "AIzaSyDUMMY" not in text and str(isolated_env) not in text


def test_the_download_is_built_on_request_and_not_kept_in_the_session():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "data=lambda: project_store.build_project_zip(pid)" in src
    assert "project_zip_" not in src and "prep_zip_" not in src
