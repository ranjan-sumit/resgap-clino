"""
Tests for utils/database.py's core run-history functions (save_run,
load_run, list_runs, delete_run, get_run_papers) -- genuinely untested
before the Phase 4 Postgres migration (no test file exercised them against
the old SQLite backend either; this closes a pre-existing gap, not just a
migration-era one). Runs against a real, isolated Postgres schema per test
class (see tests/pg_test_utils.py).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from tests.pg_test_utils import new_test_schema, drop_test_schema


def _results(domain="Healthcare AI", interest="test", papers=None, gaps=None, proposals=None):
    return {
        "context": {"domain": domain, "interest": interest},
        "papers": papers or [{"filename": "a.pdf", "wiki": {"title": "Paper A"}, "tier": 1}],
        "gaps": gaps if gaps is not None else [{"title": "gap 1"}],
        "proposals": proposals if proposals is not None else [{"title": "prop 1"}],
    }


class _IsolatedSchemaTestCase(unittest.TestCase):
    def setUp(self):
        self.schema = new_test_schema()
        self.patcher = patch.object(db, "_SCHEMA", self.schema)
        self.patcher.start()
        db.init_db()

    def tearDown(self):
        self.patcher.stop()
        drop_test_schema(self.schema)


class SaveLoadRunTests(_IsolatedSchemaTestCase):
    def test_save_then_load_round_trips(self):
        results = _results()
        rid = db.save_run("Test Run", results)
        loaded = db.load_run(rid)
        self.assertEqual(loaded["results"], results)
        self.assertIsNone(loaded.get("comp_results"))

    def test_save_with_comp_results_round_trips_both(self):
        results = _results()
        comp = {"simulation": "output"}
        rid = db.save_run("Test Run", results, comp_results=comp)
        loaded = db.load_run(rid)
        self.assertEqual(loaded["results"], results)
        self.assertEqual(loaded["comp_results"], comp)

    def test_load_unknown_run_returns_empty_dict_not_none_or_error(self):
        self.assertEqual(db.load_run("does-not-exist"), {})

    def test_run_id_is_deterministic_from_name_and_timestamp(self):
        rid1 = db._run_id("Same Name", "2026-01-01T00:00:00")
        rid2 = db._run_id("Same Name", "2026-01-01T00:00:00")
        self.assertEqual(rid1, rid2)

    def test_nested_unicode_and_special_characters_survive_round_trip(self):
        results = _results(interest="unicode: café, 日本語, emoji 🔬")
        rid = db.save_run("Unicode Test", results)
        loaded = db.load_run(rid)
        self.assertEqual(loaded["results"]["context"]["interest"], results["context"]["interest"])


class ListRunsTests(_IsolatedSchemaTestCase):
    def test_empty_history_returns_empty_list(self):
        self.assertEqual(db.list_runs(), [])

    def test_saved_run_appears_in_list_with_correct_metadata(self):
        rid = db.save_run("My Run", _results(gaps=[{"t": 1}, {"t": 2}]))
        runs = db.list_runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["id"], rid)
        self.assertEqual(runs[0]["name"], "My Run")
        self.assertEqual(runs[0]["n_gaps"], 2)
        self.assertEqual(runs[0]["n_papers"], 1)

    def test_ordered_newest_first(self):
        import time
        rid1 = db.save_run("First", _results())
        time.sleep(1.1)  # created_at has second-resolution timestamps
        rid2 = db.save_run("Second", _results())
        runs = db.list_runs()
        self.assertEqual(runs[0]["id"], rid2)
        self.assertEqual(runs[1]["id"], rid1)

    def test_limit_is_respected(self):
        for i in range(3):
            db.save_run(f"Run {i}", _results())
        self.assertEqual(len(db.list_runs(limit=2)), 2)

    def test_list_does_not_include_the_full_blob(self):
        db.save_run("My Run", _results())
        runs = db.list_runs()
        self.assertNotIn("results_json", runs[0])


class DeleteRunTests(_IsolatedSchemaTestCase):
    def test_delete_removes_run_and_its_papers(self):
        rid = db.save_run("To Delete", _results())
        self.assertNotEqual(db.load_run(rid), {})
        db.delete_run(rid)
        self.assertEqual(db.load_run(rid), {})
        self.assertEqual(db.get_run_papers(rid), [])

    def test_delete_unknown_run_does_not_raise(self):
        db.delete_run("does-not-exist")  # should be a silent no-op

    def test_deleting_one_run_does_not_affect_another(self):
        rid1 = db.save_run("Keep Me", _results())
        rid2 = db.save_run("Delete Me", _results())
        db.delete_run(rid2)
        self.assertNotEqual(db.load_run(rid1), {})
        self.assertEqual(db.load_run(rid2), {})


class GetRunPapersTests(_IsolatedSchemaTestCase):
    def test_returns_papers_for_the_run(self):
        papers = [
            {"filename": "a.pdf", "wiki": {"title": "Paper A"}, "tier": 1},
            {"filename": "b.pdf", "wiki": {"title": "Paper B"}, "tier": 2},
        ]
        rid = db.save_run("Multi Paper Run", _results(papers=papers))
        result = db.get_run_papers(rid)
        self.assertEqual(len(result), 2)
        self.assertEqual({p["filename"] for p in result}, {"a.pdf", "b.pdf"})

    def test_falls_back_to_filename_when_wiki_title_missing(self):
        papers = [{"filename": "untitled.pdf", "wiki": {}, "tier": 1}]
        rid = db.save_run("No Title Run", _results(papers=papers))
        result = db.get_run_papers(rid)
        self.assertEqual(result[0]["title"], "untitled.pdf")

    def test_unknown_run_returns_empty_list(self):
        self.assertEqual(db.get_run_papers("does-not-exist"), [])

    def test_resaving_same_run_id_does_not_duplicate_papers(self):
        # save_run() clears prior papers rows before re-inserting (idempotent
        # re-save semantics, matching the old SQLite INSERT OR REPLACE intent).
        ts = "2026-01-01T00:00:00"
        with patch.object(db, "_run_id", return_value="fixed_id"):
            db.save_run("Run A", _results(papers=[{"filename": "a.pdf", "wiki": {}, "tier": 1}]))
            db.save_run("Run A", _results(papers=[{"filename": "b.pdf", "wiki": {}, "tier": 1}]))
        result = db.get_run_papers("fixed_id")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["filename"], "b.pdf")


class SameSecondSaveRunTests(_IsolatedSchemaTestCase):
    def test_two_same_name_runs_started_in_the_same_second_both_survive(self):
        # Regression: run_id was md5(name + second-resolution timestamp),
        # so two runs with the same name started in the same second (API
        # double-submit, two tabs) collided -- the second save's ON CONFLICT
        # DO UPDATE silently overwrote the first run's row AND deleted its
        # papers while both jobs reported success.
        import datetime as datetime_module

        papers_a = [{"filename": "a.pdf", "wiki": {"title": "Paper A"}, "tier": 1}]
        papers_b = [{"filename": "b.pdf", "wiki": {"title": "Paper B"}, "tier": 1}]
        frozen_now = datetime_module.datetime(2026, 1, 1, 12, 0, 0)
        with patch.object(db, "datetime") as mock_datetime:
            mock_datetime.now.return_value = frozen_now
            rid_a = db.save_run("Double Submit", _results(papers=papers_a))
            rid_b = db.save_run("Double Submit", _results(papers=papers_b))

        # Distinct 12-hex-char ids, and the FIRST run's row + papers were
        # not overwritten by the second save.
        self.assertNotEqual(rid_a, rid_b)
        self.assertRegex(rid_a, r"^[0-9a-f]{12}$")
        self.assertRegex(rid_b, r"^[0-9a-f]{12}$")
        self.assertEqual(db.load_run(rid_a)["results"]["papers"], papers_a)
        self.assertEqual(db.load_run(rid_b)["results"]["papers"], papers_b)
        self.assertEqual({p["filename"] for p in db.get_run_papers(rid_a)}, {"a.pdf"})
        self.assertEqual({p["filename"] for p in db.get_run_papers(rid_b)}, {"b.pdf"})
        self.assertEqual(len(db.list_runs()), 2)


if __name__ == "__main__":
    unittest.main()
