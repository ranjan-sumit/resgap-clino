"""
Projects: database side (utils/database.py, migrations/0005_projects.sql) and
folder side (utils/project_store.py). Each test class gets its own throwaway
SQLite file and projects root.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from utils import project_store
from tests.pg_test_utils import new_test_schema, drop_test_schema


def _results(domain="Healthcare AI", n_gaps=2):
    return {"context": {"domain": domain, "interest": "test", "gap_type": "Any"},
            "gaps": [{"gap_id": f"g{i}", "title": f"Gap {i}"} for i in range(n_gaps)],
            "proposals": [], "papers": []}


class _Base(unittest.TestCase):
    def setUp(self):
        self.db_path = new_test_schema()
        self.root = tempfile.mkdtemp(prefix="resgap_projects_")
        self.patchers = [patch.object(db, "_SCHEMA", self.db_path),
                         patch.dict(os.environ, {"RESGAP_PROJECTS_DIR": self.root})]
        for p in self.patchers:
            p.start()
        db._INITIALIZED.discard(self.db_path)

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        db._INITIALIZED.discard(self.db_path)
        drop_test_schema(self.db_path)
        shutil.rmtree(self.root, ignore_errors=True)


class ProjectDatabaseTests(_Base):
    def test_default_project_always_exists_and_lists_first(self):
        p = project_store.create_project("Alpha")
        projects = db.list_projects()
        self.assertEqual(projects[0]["id"], db.DEFAULT_PROJECT_ID)
        self.assertIn(p["id"], [x["id"] for x in projects])

    def test_runs_go_to_the_default_project_unless_one_is_given(self):
        rid_default = db.save_run("no project", _results())
        proj = project_store.create_project("Alpha")
        rid_alpha = db.save_run("in alpha", _results(), project_id=proj["id"])
        self.assertEqual(db.get_run_row(rid_default)["project_id"], db.DEFAULT_PROJECT_ID)
        self.assertEqual([r["id"] for r in db.list_runs(project_id=proj["id"])], [rid_alpha])
        self.assertEqual([r["id"] for r in db.list_runs(project_id=db.DEFAULT_PROJECT_ID)], [rid_default])
        self.assertEqual({r["id"] for r in db.list_runs()}, {rid_default, rid_alpha})

    def test_project_counts(self):
        proj = project_store.create_project("Alpha")
        db.save_run("r1", _results(), project_id=proj["id"])
        db.save_run("r2", _results(), project_id=proj["id"])
        project_store.save_papers(proj["id"], [("a.pdf", b"AAA"), ("b.pdf", b"BBB")])
        row = next(p for p in db.list_projects() if p["id"] == proj["id"])
        self.assertEqual((row["run_count"], row["paper_count"]), (2, 2))

    def test_upgrade_from_the_pre_projects_schema_keeps_existing_runs(self):
        # Build a database exactly as it was before this feature (migrations 1-4
        # applied, one saved run), then let init_db() apply migration 5 to it.
        old = new_test_schema()
        try:
            conn = sqlite3.connect(old)
            conn.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, "
                         "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            for path in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
                if path.name < "0005":
                    conn.executescript(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (path.name,))
            conn.execute("INSERT INTO runs (id, name, created_at, results_json) VALUES ('old1','Old run','2026-01-01','{}')")
            conn.commit(); conn.close()

            with patch.object(db, "_SCHEMA", old):
                db._INITIALIZED.discard(old)
                db.init_db()
                self.assertEqual(db.get_run_row("old1")["project_id"], db.DEFAULT_PROJECT_ID)
                self.assertEqual(db.list_projects()[0]["run_count"], 1)
        finally:
            db._INITIALIZED.discard(old)
            drop_test_schema(old)

    def test_add_project_file_is_idempotent_and_links_to_runs(self):
        proj = project_store.create_project("Alpha")
        rid = db.save_run("r", _results(), project_id=proj["id"])
        a = db.add_project_file(proj["id"], "paper", "a.pdf", "papers/x_a.pdf", "sha", 3)
        b = db.add_project_file(proj["id"], "paper", "a.pdf", "papers/x_a.pdf", "sha", 3)
        self.assertEqual(a, b)
        db.link_run_file(rid, a); db.link_run_file(rid, a)
        self.assertEqual(len(db.list_project_files(proj["id"], run_id=rid)), 1)
        self.assertEqual(db.list_project_files(proj["id"], kind="results"), [])

    def test_deleting_a_run_removes_its_feedback_and_file_links(self):
        proj = project_store.create_project("Alpha")
        rid = db.save_run("r", _results(), project_id=proj["id"])
        db.upsert_feedback(proj["id"], rid, "gap", "g0", rating=1)
        fid = db.add_project_file(proj["id"], "results", "results.json", "runs/r/results.json", "s", 1)
        db.link_run_file(rid, fid)
        db.delete_run(rid)
        self.assertEqual(db.list_feedback(run_id=rid), [])
        self.assertEqual(db.list_project_files(proj["id"], run_id=rid), [])
        self.assertEqual(len(db.list_project_files(proj["id"])), 1)   # the file record itself stays


class FeedbackTests(_Base):
    def setUp(self):
        super().setUp()
        self.proj = project_store.create_project("Alpha")["id"]
        self.rid = db.save_run("r", _results(), project_id=self.proj)

    def test_upsert_creates_then_updates_one_row_per_target(self):
        first = db.upsert_feedback(self.proj, self.rid, "gap", "g0", rating=-1,
                                   reason="Already addressed", comment="see Smith 2024", target_label="Gap 0")
        second = db.upsert_feedback(self.proj, self.rid, "gap", "g0", rating=1, reason="Useful")
        self.assertEqual(first["id"], second["id"])
        rows = db.list_feedback(run_id=self.rid, target_type="gap")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["rating"], rows[0]["reason"], rows[0]["comment"]), (1, "Useful", ""))

    def test_empty_feedback_clears_the_row(self):
        db.upsert_feedback(self.proj, self.rid, "gap", "g0", rating=1)
        self.assertIsNone(db.upsert_feedback(self.proj, self.rid, "gap", "g0"))
        self.assertEqual(db.list_feedback(run_id=self.rid), [])

    def test_comment_only_feedback_is_kept(self):
        row = db.upsert_feedback(self.proj, self.rid, "run", "", comment="Good overall")
        self.assertIsNone(row["rating"])
        self.assertEqual(row["comment"], "Good overall")

    def test_validation(self):
        with self.assertRaises(ValueError):
            db.upsert_feedback(self.proj, self.rid, "paper", "x", rating=1)
        with self.assertRaises(ValueError):
            db.upsert_feedback(self.proj, self.rid, "gap", "g0", rating=5)

    def test_list_filters(self):
        r2 = db.save_run("r2", _results(), project_id=self.proj)
        db.upsert_feedback(self.proj, self.rid, "gap", "g0", rating=1)
        db.upsert_feedback(self.proj, self.rid, "run", "", comment="note")
        db.upsert_feedback(self.proj, r2, "gap", "g0", rating=-1)   # same gap_id, different run
        self.assertEqual(len(db.list_feedback(project_id=self.proj)), 3)
        self.assertEqual(len(db.list_feedback(project_id=self.proj, target_type="gap")), 2)
        self.assertEqual(len(db.list_feedback(run_id=r2)), 1)


class ProjectStoreTests(_Base):
    def test_create_project_makes_folder_json_and_row(self):
        p = project_store.create_project("Cystic Fibrosis 2026", "CF survey papers")
        folder = Path(p["path"])
        self.assertTrue((folder / "papers").is_dir() and (folder / "runs").is_dir())
        meta = json.loads((folder / "project.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["id"], meta["name"]), (p["id"], "Cystic Fibrosis 2026"))
        self.assertTrue(folder.name.startswith("cystic-fibrosis-2026-"))
        self.assertEqual(db.get_project(p["id"])["description"], "CF survey papers")

    def test_name_is_required(self):
        for bad in ("", "   ", None):
            with self.assertRaises(ValueError):
                project_store.create_project(bad)

    def test_hostile_project_name_cannot_escape_the_projects_root(self):
        p = project_store.create_project("../../etc/passwd")
        self.assertEqual(Path(p["path"]).resolve().parent, Path(self.root).resolve())

    def test_failed_db_insert_leaves_no_orphan_folder(self):
        with patch.object(db, "insert_project", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                project_store.create_project("Alpha")
        self.assertEqual(list(Path(self.root).iterdir()), [])

    def test_save_papers_deduplicates_by_content(self):
        pid = project_store.create_project("Alpha")["id"]
        a = project_store.save_papers(pid, [("paper.pdf", b"CONTENT")])
        b = project_store.save_papers(pid, [("paper.pdf", b"CONTENT")])
        c = project_store.save_papers(pid, [("paper.pdf", b"OTHER")])
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(list((Path(project_store.project_path(pid)) / "papers").iterdir())), 2)

    def test_same_content_under_a_different_name_is_stored_once(self):
        pid = project_store.create_project("Alpha")["id"]
        a = project_store.save_papers(pid, [("first.pdf", b"SAME BYTES")])
        b = project_store.save_papers(pid, [("renamed copy.pdf", b"SAME BYTES")])
        self.assertEqual(a, b)
        stored = list((Path(project_store.project_path(pid)) / "papers").iterdir())
        self.assertEqual(len(stored), 1)
        self.assertEqual(len(db.list_project_files(pid, kind="paper")), 1)

    def test_hostile_upload_filename_stays_inside_papers(self):
        pid = project_store.create_project("Alpha")["id"]
        project_store.save_papers(pid, [("../../../evil.pdf", b"x"), ("..\\..\\win.pdf", b"y"), ("", b"z")])
        papers = Path(project_store.project_path(pid)) / "papers"
        names = sorted(p.name for p in papers.iterdir())
        self.assertEqual(len(names), 3)
        self.assertTrue(all("/" not in n and "\\" not in n and ".." not in n for n in names), names)
        self.assertEqual(list(Path(self.root).glob("evil*")), [])

    def test_safe_filename(self):
        self.assertEqual(project_store.safe_filename("a/b/c.pdf"), "c.pdf")
        self.assertEqual(project_store.safe_filename("my paper (v2).pdf"), "my paper _v2_.pdf")
        self.assertEqual(project_store.safe_filename(".."), "paper.pdf")
        self.assertEqual(project_store.safe_filename(None), "paper.pdf")

    def test_write_run_artifacts_records_and_links_files(self):
        pid = project_store.create_project("Alpha")["id"]
        paper_ids = project_store.save_papers(pid, [("a.pdf", b"AAA"), ("b.pdf", b"BBB")])
        res = _results()
        rid = db.save_run("r", res, project_id=pid)
        files = project_store.write_run_artifacts(
            pid, rid, res, res["context"], paper_file_ids=paper_ids, make_reports=False,
            manifest={"model": "gemini:x"})
        self.assertEqual({f["kind"] for f in files}, {"results", "manifest"})
        run_dir = Path(project_store.project_path(pid)) / "runs" / rid
        self.assertEqual(json.loads((run_dir / "results.json").read_text(encoding="utf-8"))["gaps"][0]["gap_id"], "g0")
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["run_id"], manifest["model"]), (rid, "gemini:x"))
        linked = db.list_project_files(pid, run_id=rid)
        self.assertEqual({f["kind"] for f in linked}, {"paper", "results", "manifest"})
        self.assertEqual(sum(f["kind"] == "paper" for f in linked), 2)

    def test_report_failure_never_loses_the_results(self):
        pid = project_store.create_project("Alpha")["id"]
        res = _results()
        rid = db.save_run("r", res, project_id=pid)
        with patch("utils.export.to_enterprise_html_report", side_effect=RuntimeError("boom")):
            files = project_store.write_run_artifacts(pid, rid, res, res["context"])
        self.assertIn("results", {f["kind"] for f in files})
        manifest_file = next(f for f in files if f["kind"] == "manifest")
        manifest = json.loads(project_store.read_project_file(pid, manifest_file["rel_path"]))
        self.assertIn("failed", manifest["reports"]["html"])

    def test_real_reports_are_written_for_a_minimal_run(self):
        pid = project_store.create_project("Alpha")["id"]
        res = _results()
        rid = db.save_run("r", res, project_id=pid)
        files = project_store.write_run_artifacts(pid, rid, res, res["context"])
        kinds = {f["kind"] for f in files}
        self.assertTrue({"results", "manifest"} <= kinds)
        manifest = json.loads(project_store.read_project_file(pid, next(
            f for f in files if f["kind"] == "manifest")["rel_path"]))
        self.assertEqual(manifest["reports"].get("html"), "ok", manifest["reports"])

    def test_unsafe_run_id_is_rejected(self):
        pid = project_store.create_project("Alpha")["id"]
        for bad in ("../x", "a/b", "", "x" * 100):
            with self.assertRaises(ValueError):
                project_store.write_run_artifacts(pid, bad, _results(), {}, make_reports=False)

    def test_read_project_file_refuses_paths_outside_the_folder(self):
        pid = project_store.create_project("Alpha")["id"]
        with self.assertRaises(ValueError):
            project_store.read_project_file(pid, "../../outside.txt")

    def test_project_zip_has_files_and_database_export(self):
        pid = project_store.create_project("Alpha")["id"]
        ids = project_store.save_papers(pid, [("a.pdf", b"AAA")])
        res = _results()
        rid = db.save_run("r", res, project_id=pid)
        project_store.write_run_artifacts(pid, rid, res, res["context"], paper_file_ids=ids, make_reports=False)
        db.upsert_feedback(pid, rid, "gap", "g0", rating=1, comment="nice")
        with zipfile.ZipFile(BytesIO(project_store.build_project_zip(pid))) as z:
            names = z.namelist()
            export = json.loads(z.read("database_export.json"))
        self.assertIn("project.json", names)
        self.assertTrue(any(n.startswith("papers/") for n in names))
        self.assertTrue(any(n.endswith("results.json") for n in names))
        self.assertEqual(export["project"]["id"], pid)
        self.assertEqual(export["feedback"][0]["comment"], "nice")
        self.assertEqual(len(export["runs"]), 1)


if __name__ == "__main__":
    unittest.main()
