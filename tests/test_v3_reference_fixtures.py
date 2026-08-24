"""
Tests for Epic 4.3 Bucket B's evals/benchmarks/v3 reference-resolution
fixtures and evals/regression/metrics.py::compute_reference_resolution_
full_chain(). No mocks -- canonical_resolver functions are pure, no API
calls.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.canonical_resolver import filter_and_dedupe_references, merge_canonical_references
from evals.regression.metrics import compute_reference_resolution_full_chain

_V3_DIR = os.path.join(os.path.dirname(__file__), "..", "evals", "benchmarks", "v3")


def _load(filename):
    with open(os.path.join(_V3_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


class TitleAuthorYearFallbackCaseTests(unittest.TestCase):
    def test_positive_group_merges_and_negative_pair_does_not(self):
        result = compute_reference_resolution_full_chain()
        self.assertTrue(result["v3_positive_group_correct"])
        self.assertTrue(result["v3_negative_pair_correct"])

    def test_group_count_crosses_low_n_threshold(self):
        result = compute_reference_resolution_full_chain()
        self.assertEqual(result["n_groups_evaluated"], 5)
        self.assertFalse(result["low_n_warning"])

    def test_combined_recall_is_perfect_on_real_fixtures(self):
        result = compute_reference_resolution_full_chain()
        self.assertEqual(result["reference_recall"], 1.0)


class TitleOnlyQuarantineCaseTests(unittest.TestCase):
    def test_matches_documented_expected_behavior(self):
        case = _load("case-title-only-quarantine.json")
        from pipeline.canonical_resolver import resolve_canonical_identity
        resolution = resolve_canonical_identity(case["reference"])
        self.assertEqual(resolution["identity_level"], case["expected_identity_level"])
        trusted, diag = filter_and_dedupe_references([case["reference"]])
        self.assertEqual(len(trusted) > 0, case["expected_in_trusted_output"])


class UnknownTitleCollisionCaseTests(unittest.TestCase):
    """Regression guard for the documented real finding -- fails loudly,
    on purpose, if canonical_resolver.py's behavior changes, forcing a
    deliberate update to the case's observed_behavior rather than a
    silently stale claim."""

    def test_merge_canonical_references_collapses_distinct_records(self):
        case = _load("case-unknown-title-collision.json")
        merged = merge_canonical_references(case["fixture_references"])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["identity_level"], "title_only_partial")
        self.assertEqual(len(merged[0]["provider_records"]), 3)

    def test_filter_and_dedupe_drops_all_of_them(self):
        case = _load("case-unknown-title-collision.json")
        trusted, diag = filter_and_dedupe_references(case["fixture_references"])
        self.assertEqual(len(trusted), 0)
        self.assertEqual(diag["status_counts"]["QUARANTINED"], 3)


if __name__ == "__main__":
    unittest.main()
