"""
One analysis = one run: the Computational Lab output is attached to the run it
came from (not saved as a second run), and the final report includes it and can
be saved into the project.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from utils import project_store
from utils.export import (_lab_html, _lab_summary, to_enterprise_html_report, to_enterprise_pdf_report)
from tests.pg_test_utils import new_test_schema, drop_test_schema


def _results():
    return {"context": {"domain": "Healthcare AI", "interest": "x", "gap_type": "Any"},
            "gaps": [{"gap_id": "g0", "title": "Gap 0", "description": "d", "validation_status": "open"}],
            "proposals": [], "papers": [{"filename": "a.pdf", "wiki": {"title": "A"}}]}


def _comp():
    return {
        "params": [{"name": "survey_response_rate", "value": 6.76, "unit": "percent", "category": "rate",
                    "source_paper": "Survey", "confidence": "high"}],
        "sufficiency": {"coverage_score": 1, "recommendation": "insufficient",
                        "why_score_is_low": "only survey rates", "missing_critical": ["progression rates"]},
        "discovery": {"hypotheses": [{"hypothesis_id": "H1", "title": "LNP delivery", "claim": "claim text"}]},
        "model_council": {"final_decision": {"selected_model": "bayesian_network", "rationale": "because"}},
        "sim_results": {"headline_numbers": {"base_case_posterior_prob": 0.15, "top_driver": "survey_response_rate"},
                        "sensitivity_ranking": [{"parameter": "survey_response_rate", "importance": 1.0}]},
        "insight_council": {"final_decision": {
            "novel_finding": {"title": "Mucus barrier", "claim": "blocks transfection"},
            "clinical_insights": ["clinical one"], "research_insights": [{"representative": "research one"}],
            "actionable_next_steps": ["step one"], "limitations": ["limit one"],
            "simulation_interpretation": "interp"}},
    }


class _Base(unittest.TestCase):
    def setUp(self):
        self.db_path = new_test_schema()
        self.root = tempfile.mkdtemp(prefix="resgap_labrun_")
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


class AttachCompResultsTests(_Base):
    def test_lab_results_attach_to_the_same_run_without_creating_another(self):
        rid = db.save_run("Run 1", _results())
        self.assertFalse(db.list_runs()[0]["has_comp"])
        self.assertTrue(db.attach_comp_results(rid, _comp()))
        runs = db.list_runs()
        self.assertEqual(len(runs), 1)                      # still one run
        self.assertEqual(runs[0]["name"], "Run 1")          # name untouched
        self.assertTrue(runs[0]["has_comp"])

    def test_loading_the_run_returns_both_parts(self):
        rid = db.save_run("Run 1", _results())
        db.attach_comp_results(rid, _comp())
        loaded = db.load_run(rid)
        self.assertEqual(loaded["results"]["gaps"][0]["gap_id"], "g0")
        self.assertEqual(loaded["comp_results"]["params"][0]["name"], "survey_response_rate")

    def test_attaching_again_replaces_the_earlier_lab_output(self):
        rid = db.save_run("Run 1", _results())
        db.attach_comp_results(rid, _comp())
        second = _comp(); second["params"] = []
        db.attach_comp_results(rid, second)
        self.assertEqual(db.load_run(rid)["comp_results"]["params"], [])

    def test_unknown_run_returns_false(self):
        self.assertFalse(db.attach_comp_results("does-not-exist", _comp()))

    def test_run_counts_are_unchanged_by_attaching(self):
        rid = db.save_run("Run 1", _results())
        db.attach_comp_results(rid, _comp())
        row = db.get_run_row(rid)
        self.assertEqual((row["n_papers"], row["n_gaps"]), (1, 1))


class UpdateRunProposalsTests(_Base):
    def test_fills_in_proposals_for_a_run_that_had_none(self):
        rid = db.save_run("Run 3", _results())
        self.assertEqual(db.get_run_row(rid)["n_proposals"], 0)
        self.assertTrue(db.update_run_proposals(rid, [{"title": "P1"}, {"title": "P2"}]))
        self.assertEqual(db.get_run_row(rid)["n_proposals"], 2)
        self.assertEqual([p["title"] for p in db.load_run(rid)["results"]["proposals"]], ["P1", "P2"])

    def test_leaves_the_rest_of_the_run_alone(self):
        rid = db.save_run("Run 3", _results())
        db.attach_comp_results(rid, _comp())
        db.update_run_proposals(rid, [{"title": "P1"}])
        loaded = db.load_run(rid)
        self.assertEqual(loaded["results"]["gaps"][0]["gap_id"], "g0")
        self.assertEqual(loaded["comp_results"]["params"][0]["name"], "survey_response_rate")
        self.assertEqual(db.get_run_row(rid)["name"], "Run 3")

    def test_unknown_run_returns_false(self):
        self.assertFalse(db.update_run_proposals("nope", [{"title": "P"}]))


class LabReportTests(unittest.TestCase):
    def test_html_has_a_lab_section_with_the_findings(self):
        html = to_enterprise_html_report(_results(), {"domain": "x"}, comp_results=_comp())
        for needle in ("Computational Lab", "survey_response_rate", "H1", "bayesian_network", "Mucus barrier",
                       "clinical one", "research one", "step one", "limit one", "progression rates"):
            self.assertIn(needle, html)

    def test_html_without_lab_output_has_no_lab_section(self):
        html = to_enterprise_html_report(_results(), {"domain": "x"})
        self.assertNotIn("Computational Lab", html)

    def test_pdf_builds_with_and_without_lab_output(self):
        self.assertTrue(to_enterprise_pdf_report(_results(), {"domain": "x"}, comp_results=_comp()).startswith(b"%PDF"))
        self.assertTrue(to_enterprise_pdf_report(_results(), {"domain": "x"}).startswith(b"%PDF"))

    def test_lab_text_is_escaped(self):
        comp = _comp(); comp["params"][0]["name"] = "<script>alert(1)</script>"
        self.assertNotIn("<script>alert(1)</script>", _lab_html(comp))

    def test_summary_tolerates_missing_and_odd_parts(self):
        s = _lab_summary({"insight_council": {"final_decision": {"novel_finding": "plain string"}}})
        self.assertEqual(s["novel"], "plain string")
        self.assertEqual(s["params"], [])
        self.assertEqual(_lab_html({}), "")


class SaveReportTests(_Base):
    def _run(self):
        proj = project_store.create_project("Alpha")
        rid = db.save_run("Run 1", _results(), project_id=proj["id"])
        return proj["id"], rid

    def test_saves_report_files_and_records_them_on_the_run(self):
        pid, rid = self._run()
        project_store.save_report(pid, rid, "<html>FINAL</html>", b"%PDF-final")
        files = db.list_project_files(pid, run_id=rid)
        self.assertEqual({f["kind"] for f in files}, {"report_html", "report_pdf"})
        self.assertEqual(project_store.read_project_file(pid, f"runs/{rid}/report.html"), b"<html>FINAL</html>")

    def test_saving_again_replaces_the_report_and_updates_its_recorded_hash(self):
        pid, rid = self._run()
        project_store.save_report(pid, rid, "<html>v1</html>", None)
        project_store.save_report(pid, rid, "<html>version two</html>", None)
        files = [f for f in db.list_project_files(pid, run_id=rid) if f["kind"] == "report_html"]
        self.assertEqual(len(files), 1)                                  # one report per run
        self.assertEqual(files[0]["size_bytes"], len(b"<html>version two</html>"))

    def test_unsafe_run_id_is_refused(self):
        pid, _ = self._run()
        with self.assertRaises(ValueError):
            project_store.save_report(pid, "../evil", "x", None)

    def test_refresh_run_results_adds_the_lab_to_results_and_report(self):
        pid, rid = self._run()
        project_store.refresh_run_results(pid, rid, _results(), {"domain": "x"}, _comp())
        saved = json.loads(project_store.read_project_file(pid, f"runs/{rid}/results.json"))
        self.assertIn("computational_lab", saved)
        self.assertIn(b"Computational Lab", project_store.read_project_file(pid, f"runs/{rid}/report.html"))


if __name__ == "__main__":
    unittest.main()
