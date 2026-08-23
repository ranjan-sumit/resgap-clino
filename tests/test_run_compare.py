"""
Tests for pipeline/run_compare.py (Clinova Phase 4, Epic 4.4's motivating
slice, FR-28). Mocked utils.database (load_run/get_run_manifest) -- no
live Postgres dependency for this suite, matching this codebase's
established convention (live-server verification happens by hand
separately, same as pipeline/graph_persistence.py's tests).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.run_compare import compare_runs, _diff_papers, _diff_graph, _diff_gaps, _diff_proposals


def _run(papers=None, graph=None, gaps=None, proposals=None, evidence_objects=None):
    return {"results": {
        "papers": papers or [], "graph": graph or {}, "gaps": gaps or [],
        "proposals": proposals or [], "evidence_objects": evidence_objects or {},
    }}


class DiffPapersTests(unittest.TestCase):
    def test_added_and_removed(self):
        a = [{"filename": "a.pdf"}, {"filename": "b.pdf"}]
        b = [{"filename": "b.pdf"}, {"filename": "c.pdf"}]
        result = _diff_papers(a, b)
        self.assertEqual(result["added"], ["c.pdf"])
        self.assertEqual(result["removed"], ["a.pdf"])
        self.assertEqual(result["common_count"], 1)

    def test_identical_papers_no_diff(self):
        papers = [{"filename": "a.pdf"}]
        result = _diff_papers(papers, papers)
        self.assertEqual(result["added"], [])
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["common_count"], 1)


class DiffGraphTests(unittest.TestCase):
    def test_entities_added_and_removed_by_normalized_name(self):
        graph_a = {"entities": [{"id": "e1", "name": "ADHD"}], "relationships": []}
        graph_b = {"entities": [{"id": "e1", "name": "  adhd  "}, {"id": "e2", "name": "ASD"}], "relationships": []}
        result = _diff_graph(graph_a, graph_b)
        self.assertEqual(result["entities_added"], ["ASD"])
        self.assertEqual(result["entities_removed"], [])
        self.assertEqual(result["entities_common_count"], 1)

    def test_relationships_matched_by_normalized_endpoint_names(self):
        graph_a = {
            "entities": [{"id": "e1", "name": "ADHD"}, {"id": "e2", "name": "ASD"}],
            "relationships": [{"source": "e1", "target": "e2", "relation": "co-occurs"}],
        }
        graph_b = {
            "entities": [{"id": "x1", "name": "adhd"}, {"id": "x2", "name": "asd"}],
            "relationships": [{"source": "x1", "target": "x2", "relation": "co-occurs"}],
        }
        result = _diff_graph(graph_a, graph_b)
        self.assertEqual(result["relationships_added"], [])
        self.assertEqual(result["relationships_removed"], [])
        self.assertEqual(result["relationships_common_count"], 1)

    def test_relationship_referencing_unknown_entity_is_skipped_not_crashed(self):
        graph_a = {"entities": [{"id": "e1", "name": "A"}],
                    "relationships": [{"source": "e1", "target": "missing", "relation": "x"}]}
        result = _diff_graph(graph_a, {"entities": [], "relationships": []})
        self.assertEqual(result["relationships_common_count"], 0)
        self.assertEqual(result["relationships_removed"], [])

    def test_empty_graphs_do_not_crash(self):
        result = _diff_graph({}, {})
        self.assertEqual(result["entities_common_count"], 0)


class DiffGapsTests(unittest.TestCase):
    def test_added_and_removed_by_normalized_title(self):
        a = [{"title": "Gap One", "confidence": "high"}]
        b = [{"title": "  gap one  ", "confidence": "high"}, {"title": "Gap Two", "confidence": "medium"}]
        result = _diff_gaps(a, b)
        self.assertEqual(result["added"], ["Gap Two"])
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["common_count"], 1)

    def test_confidence_change_detected_for_common_gap(self):
        a = [{"title": "Gap One", "confidence": "medium"}]
        b = [{"title": "Gap One", "confidence": "high"}]
        result = _diff_gaps(a, b)
        self.assertEqual(len(result["confidence_changes"]), 1)
        self.assertEqual(result["confidence_changes"][0]["confidence_a"], "medium")
        self.assertEqual(result["confidence_changes"][0]["confidence_b"], "high")

    def test_no_confidence_change_when_identical(self):
        gaps = [{"title": "Gap One", "confidence": "high"}]
        result = _diff_gaps(gaps, gaps)
        self.assertEqual(result["confidence_changes"], [])


class DiffProposalsTests(unittest.TestCase):
    def test_added_and_removed_counts(self):
        a = [{"title": "Proposal A"}]
        b = [{"title": "Proposal A"}, {"title": "Proposal B"}]
        result = _diff_proposals(a, b)
        self.assertEqual(result["added_count"], 1)
        self.assertEqual(result["removed_count"], 0)
        self.assertEqual(result["common_count"], 1)


class CompareRunsTests(unittest.TestCase):
    @patch("utils.database.get_run_manifest")
    @patch("utils.database.load_run")
    def test_full_compare_assembles_all_sections(self, mock_load_run, mock_get_manifest):
        mock_load_run.side_effect = lambda rid: {
            "run_a": _run(
                papers=[{"filename": "a.pdf"}],
                gaps=[{"title": "Gap One", "confidence": "medium"}],
                evidence_objects={"a.pdf": [{"e": 1}, {"e": 2}]},
            ),
            "run_b": _run(
                papers=[{"filename": "a.pdf"}, {"filename": "b.pdf"}],
                gaps=[{"title": "Gap One", "confidence": "high"}, {"title": "Gap Two", "confidence": "low"}],
                evidence_objects={"a.pdf": [{"e": 1}], "b.pdf": [{"e": 2}, {"e": 3}]},
            ),
        }[rid]
        mock_get_manifest.side_effect = lambda rid: {
            "run_a": {"model_bundle_version": "nvidia:openai/gpt-oss-20b", "run_duration_seconds": 100.0},
            "run_b": {"model_bundle_version": "nvidia:deepseek-ai/deepseek-v4-flash-0731", "run_duration_seconds": 80.0},
        }[rid]

        result = compare_runs("run_a", "run_b")

        self.assertEqual(result["papers"]["added"], ["b.pdf"])
        self.assertEqual(result["evidence"]["count_a"], 2)
        self.assertEqual(result["evidence"]["count_b"], 3)
        self.assertEqual(result["evidence"]["delta"], 1)
        self.assertEqual(result["gaps"]["added"], ["Gap Two"])
        self.assertEqual(len(result["gaps"]["confidence_changes"]), 1)
        self.assertEqual(result["manifest"]["model_bundle_version_a"], "nvidia:openai/gpt-oss-20b")
        self.assertEqual(result["manifest"]["model_bundle_version_b"], "nvidia:deepseek-ai/deepseek-v4-flash-0731")
        self.assertEqual(result["manifest"]["run_duration_seconds_a"], 100.0)

    @patch("utils.database.get_run_manifest")
    @patch("utils.database.load_run")
    def test_missing_run_raises_value_error_not_silently_empty(self, mock_load_run, mock_get_manifest):
        mock_load_run.side_effect = lambda rid: {} if rid == "missing_run" else _run()
        with self.assertRaises(ValueError):
            compare_runs("missing_run", "run_b")

    @patch("utils.database.get_run_manifest")
    @patch("utils.database.load_run")
    def test_missing_manifest_degrades_to_none_not_a_crash(self, mock_load_run, mock_get_manifest):
        # A run saved before Epic 4.2 existed has no manifest row.
        mock_load_run.return_value = _run()
        mock_get_manifest.return_value = None
        result = compare_runs("run_a", "run_b")
        self.assertIsNone(result["manifest"]["model_bundle_version_a"])


if __name__ == "__main__":
    unittest.main()
