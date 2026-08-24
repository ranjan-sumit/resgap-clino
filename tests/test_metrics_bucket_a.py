"""
Tests for Epic 4.3 Bucket A metrics (evals/regression/metrics.py):
latency, extraction completeness, reference resolution (DOI path), and
evidence coverage. Latency/extraction-completeness/reference-resolution
are pure/mocked-DB; evidence coverage runs against a real, isolated
Postgres schema (tests/pg_test_utils.py), same convention as
tests/test_lineage.py.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from tests.pg_test_utils import new_test_schema, drop_test_schema
from evals.regression.metrics import (
    compute_evidence_coverage,
    compute_extraction_completeness,
    compute_latency,
    compute_reference_resolution_doi_path,
)


class ComputeLatencyTests(unittest.TestCase):
    @patch("evals.regression.metrics.get_run_manifest")
    def test_averages_real_durations(self, mock_manifest):
        mock_manifest.side_effect = [{"run_duration_seconds": 10.0}, {"run_duration_seconds": 20.0}]
        result = compute_latency(["run1", "run2"])
        self.assertEqual(result["latency_seconds"], 15.0)
        self.assertEqual(result["n_runs_evaluated"], 2)

    @patch("evals.regression.metrics.get_run_manifest")
    def test_missing_manifest_is_excluded_not_zero(self, mock_manifest):
        mock_manifest.side_effect = [{"run_duration_seconds": 10.0}, None]
        result = compute_latency(["run1", "run2"])
        self.assertEqual(result["latency_seconds"], 10.0)
        self.assertEqual(result["n_runs_missing_duration"], 1)

    @patch("evals.regression.metrics.get_run_manifest", return_value=None)
    def test_no_data_returns_none_not_zero(self, mock_manifest):
        result = compute_latency(["run1"])
        self.assertIsNone(result["latency_seconds"])


class ComputeExtractionCompletenessTests(unittest.TestCase):
    def test_real_fixture_produces_a_real_score(self):
        result = compute_extraction_completeness()
        self.assertEqual(result["n_papers_evaluated"], 3)
        self.assertIsNotNone(result["extraction_completeness"])
        self.assertGreaterEqual(result["extraction_completeness"], 0.0)
        self.assertLessEqual(result["extraction_completeness"], 1.0)
        self.assertIn("metric_caveat", result)


class ComputeReferenceResolutionDoiPathTests(unittest.TestCase):
    def test_real_fixture_produces_perfect_precision_and_recall(self):
        """The 3 real duplicate groups are clean DOI-identity cases --
        canonical_resolver should merge each group correctly with no
        cross-group contamination and no missed merges."""
        result = compute_reference_resolution_doi_path()
        self.assertEqual(result["n_groups_evaluated"], 3)
        self.assertEqual(result["reference_resolution_precision"], 1.0)
        self.assertEqual(result["reference_recall"], 1.0)
        self.assertTrue(result["cross_check"]["matches"])
        self.assertTrue(result["low_n_warning"])  # 3 < _LOW_N_THRESHOLD=5


class ComputeEvidenceCoverageTests(unittest.TestCase):
    def setUp(self):
        self.schema = new_test_schema()
        self.patcher = patch.object(db, "_SCHEMA", self.schema)
        self.patcher.start()
        db.init_db()

    def tearDown(self):
        self.patcher.stop()
        drop_test_schema(self.schema)

    def test_covered_and_absence_and_dangling_are_all_correctly_bucketed(self):
        results = {
            "papers": [], "context": {},
            "evidence_objects": {"p1.pdf": [{"evidence_id": "ev1", "text": "t"}]},
            "gaps": [
                {"gap_id": "g1", "evidence_basis": "positive_evidence", "motivating_evidence_ids": ["ev1"]},
                {"gap_id": "g2", "evidence_basis": "positive_evidence", "motivating_evidence_ids": ["ev-not-real"]},
                {"gap_id": "g3", "evidence_basis": "absence_of_evidence", "motivating_evidence_ids": []},
            ],
            "proposals": [],
        }
        db.save_run("cov-test", results)
        run_id = db.list_runs(limit=1)[0]["id"]

        result = compute_evidence_coverage(run_id)
        self.assertEqual(result["n_positive_evidence_gaps"], 2)
        self.assertEqual(result["n_absence_based"], 1)
        self.assertEqual(result["n_covered"], 1)
        self.assertEqual(result["n_unlinked"], 1)
        self.assertEqual(result["n_dangling_ids"], 1)
        self.assertEqual(result["evidence_coverage"], 0.5)

    def test_unknown_run_raises(self):
        with self.assertRaises(ValueError):
            compute_evidence_coverage("does-not-exist")

    def test_no_gaps_returns_none_not_zero(self):
        results = {"papers": [], "context": {}, "evidence_objects": {}, "gaps": [], "proposals": []}
        db.save_run("cov-test-2", results)
        run_id = db.list_runs(limit=1)[0]["id"]
        result = compute_evidence_coverage(run_id)
        self.assertIsNone(result["evidence_coverage"])


if __name__ == "__main__":
    unittest.main()
