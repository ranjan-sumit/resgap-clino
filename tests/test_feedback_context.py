"""
pipeline/feedback_context.py -- the seam the judge/agents will use later.
"""
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
from pipeline.feedback_context import (
    build_feedback_context, get_feedback_items, REASON_USEFUL, REASON_ALREADY_ADDRESSED,
    REASON_NOT_RELEVANT, REASON_WEAK_EVIDENCE, REASON_TOO_VAGUE,
)
from tests.pg_test_utils import new_test_schema, drop_test_schema

_RES = {"context": {"domain": "Healthcare AI"}, "gaps": [], "proposals": [], "papers": []}


class FeedbackContextTests(unittest.TestCase):
    def setUp(self):
        self.db_path = new_test_schema()
        self.root = tempfile.mkdtemp(prefix="resgap_projects_")
        self.patchers = [patch.object(db, "_SCHEMA", self.db_path),
                         patch.dict(os.environ, {"RESGAP_PROJECTS_DIR": self.root})]
        for p in self.patchers:
            p.start()
        db._INITIALIZED.discard(self.db_path)
        self.pid = project_store.create_project("Alpha")["id"]
        self.r1 = db.save_run("r1", _RES, project_id=self.pid)
        self.r2 = db.save_run("r2", _RES, project_id=self.pid)

    def tearDown(self):
        for p in self.patchers:
            p.stop()
        db._INITIALIZED.discard(self.db_path)
        drop_test_schema(self.db_path)
        shutil.rmtree(self.root, ignore_errors=True)

    def _fb(self, run, gap, rating, reason, comment="", label=None):
        db.upsert_feedback(self.pid, run, "gap", gap, rating=rating, reason=reason,
                           comment=comment, target_label=label or f"Title of {gap}")

    def test_empty_project_gives_empty_string(self):
        for role in ("judge", "agent", "all"):
            self.assertEqual(build_feedback_context(self.pid, role), "")

    def test_unknown_role_is_rejected(self):
        with self.assertRaises(ValueError):
            build_feedback_context(self.pid, "chair")

    def test_roles_route_reasons_to_the_right_consumer(self):
        self._fb(self.r1, "g1", -1, REASON_ALREADY_ADDRESSED, "see Smith 2024")
        self._fb(self.r1, "g2", -1, REASON_WEAK_EVIDENCE)
        self._fb(self.r1, "g3", -1, REASON_NOT_RELEVANT)
        self._fb(self.r1, "g4", -1, REASON_TOO_VAGUE)
        self._fb(self.r1, "g5", 1, REASON_USEFUL)
        judge = {i["gap_id"] for i in get_feedback_items(self.pid, "judge")}
        agent = {i["gap_id"] for i in get_feedback_items(self.pid, "agent")}
        self.assertEqual(judge, {"g1", "g2"})
        self.assertEqual(agent, {"g3", "g4", "g5"})
        self.assertEqual({i["gap_id"] for i in get_feedback_items(self.pid, "all")}, {"g1", "g2", "g3", "g4", "g5"})

    def test_same_gap_across_runs_uses_the_newest_verdict_only(self):
        self._fb(self.r1, "g1", 1, REASON_USEFUL)
        self._fb(self.r2, "g1", -1, REASON_ALREADY_ADDRESSED)   # newer: different run, same gap_id
        items = get_feedback_items(self.pid, "all")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["rating"], -1)

    def test_run_notes_go_to_agents_and_all_but_not_the_judge(self):
        db.upsert_feedback(self.pid, self.r1, "run", "", comment="Missed the pediatric angle")
        self.assertEqual(get_feedback_items(self.pid, "judge"), [])
        self.assertEqual(len(get_feedback_items(self.pid, "agent")), 1)
        self.assertIn("pediatric", build_feedback_context(self.pid, "all"))

    def test_text_is_labelled_guidance_flattened_and_trimmed(self):
        self._fb(self.r1, "g1", -1, REASON_ALREADY_ADDRESSED, "line one\nline two\n" + "x" * 1000,
                 label="A gap\nwith newline")
        text = build_feedback_context(self.pid, "judge")
        self.assertIn("not established fact", text)
        self.assertIn("marked not useful (Already addressed in the literature)", text)
        self.assertNotIn("\n\n", text)
        self.assertTrue(all(len(line) < 600 for line in text.splitlines()))
        self.assertIn("A gap with newline", text)

    def test_max_chars_drops_whole_lines(self):
        for i in range(30):
            self._fb(self.r1, f"g{i}", -1, REASON_ALREADY_ADDRESSED, "c" * 200)
        text = build_feedback_context(self.pid, "judge", max_items=30, max_chars=800)
        self.assertLessEqual(len(text), 800)
        self.assertTrue(all(line.startswith(("- ", "Researcher")) for line in text.splitlines()))


if __name__ == "__main__":
    unittest.main()
