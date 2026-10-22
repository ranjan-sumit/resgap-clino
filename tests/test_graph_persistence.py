"""
Tests for pipeline/graph_persistence.py (Clinova Phase 3, Epic 3.1), now on
SQLite instead of ArcadeDB. Runs against a real throwaway SQLite file per
test class (tests/pg_test_utils.py) -- no mocked HTTP, no server.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from pipeline.graph_persistence import (
    connect_ok, save_graph_snapshot, load_graph_snapshot,
    list_graph_snapshots, diff_graph_snapshots, _normalize_name,
)
from tests.pg_test_utils import new_test_schema, drop_test_schema


def _entity(eid, name, **kw):
    return {"id": eid, "name": name, "type": "concept", "importance": "high",
            "papers": ["P1"], **kw}


class _DbTestCase(unittest.TestCase):
    def setUp(self):
        self.schema = new_test_schema()
        self.patcher = patch.object(db, "_SCHEMA", self.schema)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        drop_test_schema(self.schema)


class ConnectOkTests(_DbTestCase):
    def test_ok_for_a_usable_sqlite_file(self):
        ok, msg = connect_ok()
        self.assertTrue(ok)
        self.assertIn("SQLite", msg)

    def test_returns_false_not_raise_when_db_cannot_open(self):
        with patch.object(db, "init_db", side_effect=OSError("disk full")):
            ok, msg = connect_ok()
        self.assertFalse(ok)
        self.assertIn("disk full", msg)


class NormalizeNameTests(unittest.TestCase):
    def test_case_and_whitespace_insensitive(self):
        self.assertEqual(_normalize_name("  ADHD   Risk "), "adhd risk")

    def test_none_does_not_crash(self):
        self.assertEqual(_normalize_name(None), "")


class SaveLoadTests(_DbTestCase):
    def test_round_trip_in_graph_builder_shape(self):
        graph = {
            "entities": [_entity("adhd", "ADHD"), _entity("int", "Internalising problems")],
            "relationships": [{"source": "adhd", "target": "int", "relation": "predicts",
                               "paper": "P1", "evidence": "..."}],
        }
        summary = save_graph_snapshot("run_1", "Test Run", graph)
        self.assertEqual(summary, {"run_id": "run_1", "entity_count": 2, "relationship_count": 1})

        loaded = load_graph_snapshot("run_1")
        self.assertEqual([e["name"] for e in loaded["entities"]], ["ADHD", "Internalising problems"])
        self.assertEqual(loaded["entities"][0]["papers"], ["P1"])
        self.assertEqual(loaded["relationships"], [
            {"source": "adhd", "target": "int", "relation": "predicts", "paper": "P1", "evidence": "..."}])

    def test_relationship_by_name_resolves_to_entity_id(self):
        graph = {"entities": [_entity("e1", "Alpha"), _entity("e2", "Beta")],
                 "relationships": [{"source": "  alpha ", "target": "BETA", "relation": "r"}]}
        self.assertEqual(save_graph_snapshot("run_1", "R", graph)["relationship_count"], 1)
        rel = load_graph_snapshot("run_1")["relationships"][0]
        self.assertEqual((rel["source"], rel["target"]), ("e1", "e2"))

    def test_relationship_referencing_unknown_entity_is_skipped_not_crashed(self):
        graph = {"entities": [_entity("adhd", "ADHD")],
                 "relationships": [{"source": "adhd", "target": "nonexistent_entity", "relation": "predicts"}]}
        summary = save_graph_snapshot("run_1", "R", graph)
        self.assertEqual(summary["relationship_count"], 0)
        self.assertEqual(load_graph_snapshot("run_1")["relationships"], [])

    def test_never_saved_run_id_returns_empty_graph_not_error(self):
        self.assertEqual(load_graph_snapshot("nonexistent_run"), {"entities": [], "relationships": []})

    def test_successful_resave_replaces_prior_snapshot_completely(self):
        v1 = {"entities": [_entity("a", "Alpha"), _entity("b", "Beta")],
              "relationships": [{"source": "a", "target": "b", "relation": "predicts"}]}
        v2 = {"entities": [_entity("c", "Gamma")], "relationships": []}
        save_graph_snapshot("run_1", "Run", v1)
        save_graph_snapshot("run_1", "Run", v2)

        loaded = load_graph_snapshot("run_1")
        self.assertEqual([e["name"] for e in loaded["entities"]], ["Gamma"])
        self.assertEqual(loaded["relationships"], [])
        self.assertEqual(len(list_graph_snapshots()), 1)  # idempotent per run_id

    def test_mid_save_failure_preserves_prior_snapshot(self):
        v1 = {"entities": [_entity("a", "Alpha"), _entity("b", "Beta")],
              "relationships": [{"source": "a", "target": "b", "relation": "predicts"}]}
        save_graph_snapshot("run_1", "Run", v1)
        before = load_graph_snapshot("run_1")

        v2 = {"entities": [_entity("c", "Gamma")], "relationships": []}
        with patch("pipeline.graph_persistence.json.dumps", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                save_graph_snapshot("run_1", "Run", v2)

        self.assertEqual(load_graph_snapshot("run_1"), before)

    def test_corrupted_row_loads_as_empty_not_crash(self):
        save_graph_snapshot("run_1", "Run", {"entities": [_entity("a", "Alpha")], "relationships": []})
        conn = db._get_conn()
        conn.execute("UPDATE graph_snapshots SET graph_json = 'not json' WHERE run_id = 'run_1'")
        conn.commit()
        conn.close()
        self.assertEqual(load_graph_snapshot("run_1"), {"entities": [], "relationships": []})


class ListGraphSnapshotsTests(_DbTestCase):
    def test_lists_newest_first(self):
        g = {"entities": [_entity("a", "A")], "relationships": []}
        save_graph_snapshot("run_old", "First", g)
        save_graph_snapshot("run_new", "Second", g)
        runs = list_graph_snapshots()
        self.assertEqual([r["run_id"] for r in runs], ["run_new", "run_old"])
        self.assertEqual(runs[0]["entity_count"], 1)

    def test_quality_dict_is_persisted_and_passes_through(self):
        save_graph_snapshot("run_1", "Scored", {"entities": [], "relationships": []},
                            quality={"build_status": "DEGRADED", "quality_score": 0.42})
        run = list_graph_snapshots()[0]
        self.assertEqual(run["build_status"], "DEGRADED")
        self.assertEqual(run["quality_score"], 0.42)

    def test_missing_quality_dict_stores_none_not_a_crash(self):
        save_graph_snapshot("run_1", "Unscored", {"entities": [], "relationships": []})
        run = list_graph_snapshots()[0]
        self.assertIsNone(run["build_status"])
        self.assertIsNone(run["quality_score"])


class DiffGraphSnapshotsTests(_DbTestCase):
    def test_identifies_new_removed_and_common_entities(self):
        save_graph_snapshot("run_a", "A", {"entities": [
            _entity("a1", "Shared Concept"), _entity("a2", "Only In A")], "relationships": []})
        save_graph_snapshot("run_b", "B", {"entities": [
            _entity("b1", "shared concept"),  # same name, different case/id
            _entity("b2", "Only In B")], "relationships": []})

        diff = diff_graph_snapshots("run_a", "run_b")
        self.assertEqual(diff["entities_only_in_a"], ["Only In A"])
        self.assertEqual(diff["entities_only_in_b"], ["Only In B"])
        self.assertEqual(diff["entities_common"], ["Shared Concept"])

    def test_identifies_new_and_common_relationships(self):
        save_graph_snapshot("run_a", "A", {
            "entities": [_entity("x", "X"), _entity("y", "Y")],
            "relationships": [{"source": "x", "target": "y", "relation": "predicts"}]})
        save_graph_snapshot("run_b", "B", {
            "entities": [_entity("x", "X"), _entity("y", "Y"), _entity("z", "Z")],
            "relationships": [{"source": "x", "target": "y", "relation": "predicts"},
                              {"source": "x", "target": "z", "relation": "evaluated_on"}]})

        diff = diff_graph_snapshots("run_a", "run_b")
        self.assertEqual(diff["relationships_common"], [("x", "y", "predicts")])
        self.assertEqual(diff["relationships_only_in_b"], [("x", "z", "evaluated_on")])
        self.assertEqual(diff["relationships_only_in_a"], [])


if __name__ == "__main__":
    unittest.main()
