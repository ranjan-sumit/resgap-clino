"""
Tests for pipeline/graph_persistence.py (Clinova Phase 3, Epic 3.1).
Mocked HTTP -- no live ArcadeDB server needed for this suite, matching
this codebase's existing convention (live-server verification happens by
hand, same as evals/benchmarks/ scripts).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.graph_persistence import (
    connect_ok, save_graph_snapshot, load_graph_snapshot,
    list_graph_snapshots, diff_graph_snapshots, _normalize_name, _config,
)


def _resp(status_code=200, json_data=None, raise_exc=None):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data or {}
    if raise_exc:
        m.raise_for_status.side_effect = raise_exc
    else:
        m.raise_for_status.return_value = None
    return m


class ConnectOkTests(unittest.TestCase):
    @patch("pipeline.graph_persistence.requests.get")
    def test_returns_true_on_204(self, mock_get):
        mock_get.return_value = _resp(status_code=204)
        ok, msg = connect_ok({"url": "http://localhost:2480", "user": "root", "password": "x", "database": "d"})
        self.assertTrue(ok)

    @patch("pipeline.graph_persistence.requests.get")
    def test_returns_false_on_connection_error_not_raise(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")
        ok, msg = connect_ok({"url": "http://localhost:2480", "user": "root", "password": "x", "database": "d"})
        self.assertFalse(ok)
        self.assertIn("localhost:2480", msg)

    @patch("pipeline.graph_persistence.requests.get")
    def test_unexpected_status_is_not_ok(self, mock_get):
        mock_get.return_value = _resp(status_code=500)
        ok, msg = connect_ok({"url": "http://localhost:2480", "user": "root", "password": "x", "database": "d"})
        self.assertFalse(ok)


class NormalizeNameTests(unittest.TestCase):
    def test_case_and_whitespace_insensitive(self):
        self.assertEqual(_normalize_name("  ADHD   Risk "), "adhd risk")

    def test_none_does_not_crash(self):
        self.assertEqual(_normalize_name(None), "")


_TEST_CONFIG = {"url": "http://localhost:2480", "user": "root", "password": "x", "database": "d"}


class SaveGraphSnapshotTests(unittest.TestCase):
    @patch("pipeline.graph_persistence.requests.post")
    def test_delete_statements_use_the_from_keyword(self, mock_post):
        # Real bug found live (2026-08-22): ArcadeDB's DELETE VERTEX
        # requires "FROM" ("DELETE VERTEX FROM GraphEntity WHERE ...") --
        # omitting it is a SQL syntax error (CommandSQLParsingException),
        # confirmed live before fixing.
        mock_post.return_value = _resp(json_data={"result": []})
        save_graph_snapshot("run_1", "Test", {"entities": [], "relationships": []}, config=_TEST_CONFIG)
        delete_calls = [c for c in mock_post.call_args_list
                        if "DELETE VERTEX" in c.kwargs["json"]["command"]]
        self.assertTrue(delete_calls)
        for c in delete_calls:
            self.assertIn("DELETE VERTEX FROM", c.kwargs["json"]["command"])

    @patch("pipeline.graph_persistence.requests.post")
    def test_saves_entities_and_relationships(self, mock_post):
        # Each _command() call maps to one requests.post -- return a
        # fresh @rid-bearing vertex result for entity inserts, empty for
        # everything else (delete/run-insert/edge-create don't need one).
        def side_effect(url, json=None, **kwargs):
            cmd = (json or {}).get("command", "")
            if "INSERT INTO GraphEntity" in cmd:
                return _resp(json_data={"result": [{"@rid": f"#1:{mock_post.call_count}"}]})
            return _resp(json_data={"result": []})

        mock_post.side_effect = side_effect

        graph = {
            "entities": [
                {"id": "adhd", "name": "ADHD", "type": "concept", "importance": "high", "papers": ["P1"]},
                {"id": "internalising", "name": "Internalising problems", "type": "concept",
                 "importance": "high", "papers": ["P1"]},
            ],
            "relationships": [
                {"source": "adhd", "target": "internalising", "relation": "predicts", "paper": "P1", "evidence": "..."},
            ],
        }
        summary = save_graph_snapshot("run_1", "Test Run", graph, config=_TEST_CONFIG)
        self.assertEqual(summary["run_id"], "run_1")
        self.assertEqual(summary["entity_count"], 2)
        self.assertEqual(summary["relationship_count"], 1)

    @patch("pipeline.graph_persistence.requests.post")
    def test_relationship_referencing_unknown_entity_is_skipped_not_crashed(self, mock_post):
        def side_effect(url, json=None, **kwargs):
            cmd = (json or {}).get("command", "")
            if "INSERT INTO GraphEntity" in cmd:
                return _resp(json_data={"result": [{"@rid": "#1:0"}]})
            return _resp(json_data={"result": []})
        mock_post.side_effect = side_effect

        graph = {
            "entities": [{"id": "adhd", "name": "ADHD", "type": "concept", "importance": "high", "papers": []}],
            "relationships": [{"source": "adhd", "target": "nonexistent_entity", "relation": "predicts"}],
        }
        summary = save_graph_snapshot("run_1", "Test Run", graph, config=_TEST_CONFIG)
        self.assertEqual(summary["relationship_count"], 0)

    @patch("pipeline.graph_persistence.requests.post")
    def test_quality_dict_is_persisted_onto_the_graphrun_insert(self, mock_post):
        mock_post.return_value = _resp(json_data={"result": []})
        quality = {"build_status": "DEGRADED", "quality_score": 0.42}
        save_graph_snapshot("run_1", "Test", {"entities": [], "relationships": []},
                             config=_TEST_CONFIG, quality=quality)
        run_insert_calls = [c for c in mock_post.call_args_list
                             if "INSERT INTO GraphRun" in c.kwargs["json"]["command"]]
        self.assertTrue(run_insert_calls)
        params = run_insert_calls[0].kwargs["json"]["params"]
        self.assertEqual(params["build_status"], "DEGRADED")
        self.assertEqual(params["quality_score"], 0.42)

    @patch("pipeline.graph_persistence.requests.post")
    def test_missing_quality_dict_stores_none_not_a_crash(self, mock_post):
        mock_post.return_value = _resp(json_data={"result": []})
        save_graph_snapshot("run_1", "Test", {"entities": [], "relationships": []}, config=_TEST_CONFIG)
        run_insert_calls = [c for c in mock_post.call_args_list
                             if "INSERT INTO GraphRun" in c.kwargs["json"]["command"]]
        params = run_insert_calls[0].kwargs["json"]["params"]
        self.assertIsNone(params["build_status"])
        self.assertIsNone(params["quality_score"])


class LoadGraphSnapshotTests(unittest.TestCase):
    @patch("pipeline.graph_persistence.requests.post")
    def test_relationship_query_uses_at_prefixed_out_in(self, mock_post):
        # Real bug found live (2026-08-22): ArcadeDB SQL silently returns
        # null (not an error) for `out.entity_id`/`in.entity_id` -- the
        # correct edge-link dereference needs the @-prefixed
        # @out.entity_id/@in.entity_id. Confirmed live against the real
        # server before fixing; this locks the correct query in.
        mock_post.return_value = _resp(json_data={"result": []})
        load_graph_snapshot("run_1", config=_TEST_CONFIG)
        rel_call = next(c for c in mock_post.call_args_list
                         if "GraphRelation WHERE" in c.kwargs["json"]["command"])
        cmd = rel_call.kwargs["json"]["command"]
        self.assertIn("@out.entity_id", cmd)
        self.assertIn("@in.entity_id", cmd)
        self.assertNotIn(" out.entity_id", cmd)
        self.assertNotIn(" in.entity_id", cmd)

    @patch("pipeline.graph_persistence.requests.post")
    def test_reconstructs_the_graph_builder_shape(self, mock_post):
        def side_effect(url, json=None, **kwargs):
            cmd = (json or {}).get("command", "")
            if "GraphEntity WHERE" in cmd:
                return _resp(json_data={"result": [
                    {"entity_id": "adhd", "name": "ADHD", "type": "concept",
                     "importance": "high", "papers": ["P1"]},
                ]})
            if "GraphRelation WHERE" in cmd:
                return _resp(json_data={"result": [
                    {"source": "adhd", "target": "internalising", "relation": "predicts",
                     "paper": "P1", "evidence": "..."},
                ]})
            return _resp(json_data={"result": []})
        mock_post.side_effect = side_effect

        graph = load_graph_snapshot("run_1", config=_TEST_CONFIG)
        self.assertEqual(len(graph["entities"]), 1)
        self.assertEqual(graph["entities"][0]["name"], "ADHD")
        self.assertEqual(len(graph["relationships"]), 1)
        self.assertEqual(graph["relationships"][0]["relation"], "predicts")

    @patch("pipeline.graph_persistence.requests.post")
    def test_never_saved_run_id_returns_empty_graph_not_error(self, mock_post):
        mock_post.return_value = _resp(json_data={"result": []})
        graph = load_graph_snapshot("nonexistent_run", config=_TEST_CONFIG)
        self.assertEqual(graph, {"entities": [], "relationships": []})


class ListGraphSnapshotsTests(unittest.TestCase):
    @patch("pipeline.graph_persistence.requests.post")
    def test_lists_saved_runs(self, mock_post):
        mock_post.return_value = _resp(json_data={"result": [
            {"run_id": "run_2", "name": "Second", "saved_at": "2026-08-22T12:00:00",
             "entity_count": 5, "relationship_count": 3},
            {"run_id": "run_1", "name": "First", "saved_at": "2026-08-22T10:00:00",
             "entity_count": 4, "relationship_count": 2},
        ]})
        runs = list_graph_snapshots(config=_TEST_CONFIG)
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0]["run_id"], "run_2")

    @patch("pipeline.graph_persistence.requests.post")
    def test_build_status_and_quality_score_pass_through(self, mock_post):
        mock_post.return_value = _resp(json_data={"result": [
            {"run_id": "run_1", "name": "Scored", "saved_at": "2026-08-22T10:00:00",
             "entity_count": 4, "relationship_count": 2,
             "build_status": "CLEAN", "quality_score": 0.91},
        ]})
        runs = list_graph_snapshots(config=_TEST_CONFIG)
        self.assertEqual(runs[0]["build_status"], "CLEAN")
        self.assertEqual(runs[0]["quality_score"], 0.91)

    @patch("pipeline.graph_persistence.requests.post")
    def test_run_saved_before_scoring_existed_reports_none_not_a_crash(self, mock_post):
        mock_post.return_value = _resp(json_data={"result": [
            {"run_id": "run_0", "name": "Old", "saved_at": "2026-08-20T10:00:00",
             "entity_count": 4, "relationship_count": 2},
        ]})
        runs = list_graph_snapshots(config=_TEST_CONFIG)
        self.assertIsNone(runs[0]["build_status"])
        self.assertIsNone(runs[0]["quality_score"])


class DiffGraphSnapshotsTests(unittest.TestCase):
    @patch("pipeline.graph_persistence.load_graph_snapshot")
    def test_identifies_new_removed_and_common_entities(self, mock_load):
        graph_a = {
            "entities": [
                {"id": "a1", "name": "Shared Concept", "type": "concept"},
                {"id": "a2", "name": "Only In A", "type": "concept"},
            ],
            "relationships": [],
        }
        graph_b = {
            "entities": [
                {"id": "b1", "name": "shared concept", "type": "concept"},  # same name, different case/id
                {"id": "b2", "name": "Only In B", "type": "concept"},
            ],
            "relationships": [],
        }
        mock_load.side_effect = [graph_a, graph_b]

        diff = diff_graph_snapshots("run_a", "run_b", config=_TEST_CONFIG)
        self.assertEqual(diff["entities_only_in_a"], ["Only In A"])
        self.assertEqual(diff["entities_only_in_b"], ["Only In B"])
        self.assertEqual(diff["entities_common"], ["Shared Concept"])

    @patch("pipeline.graph_persistence.load_graph_snapshot")
    def test_identifies_new_and_common_relationships(self, mock_load):
        graph_a = {
            "entities": [{"id": "x", "name": "X"}, {"id": "y", "name": "Y"}],
            "relationships": [{"source": "x", "target": "y", "relation": "predicts"}],
        }
        graph_b = {
            "entities": [{"id": "x", "name": "X"}, {"id": "y", "name": "Y"}, {"id": "z", "name": "Z"}],
            "relationships": [
                {"source": "x", "target": "y", "relation": "predicts"},
                {"source": "x", "target": "z", "relation": "evaluated_on"},
            ],
        }
        mock_load.side_effect = [graph_a, graph_b]

        diff = diff_graph_snapshots("run_a", "run_b", config=_TEST_CONFIG)
        self.assertEqual(diff["relationships_common"], [("x", "y", "predicts")])
        self.assertEqual(diff["relationships_only_in_b"], [("x", "z", "evaluated_on")])
        self.assertEqual(diff["relationships_only_in_a"], [])


if __name__ == "__main__":
    unittest.main()
