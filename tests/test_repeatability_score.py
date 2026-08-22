"""
Tests for pipeline/repeatability_score.py (Clinova Phase 3, Epic 3.6).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.repeatability_score import (
    compute_repeatability_score, _gap_overlap, _claim_stability,
    _ranking_correlation, _confidence_drift, _is_likely_duplicate_run,
)


def _g(title, confidence="medium"):
    return {"title": title, "confidence": confidence}


class GapOverlapTests(unittest.TestCase):
    def test_identical_sets_give_full_overlap(self):
        gaps = [_g("A"), _g("B")]
        self.assertEqual(_gap_overlap(gaps, gaps), 1.0)

    def test_disjoint_sets_give_zero_overlap(self):
        self.assertEqual(_gap_overlap([_g("A")], [_g("B")]), 0.0)

    def test_partial_overlap_is_jaccard(self):
        # {A,B} vs {B,C} -> intersection {B}=1, union {A,B,C}=3 -> 1/3
        self.assertAlmostEqual(_gap_overlap([_g("A"), _g("B")], [_g("B"), _g("C")]), 1 / 3)

    def test_both_empty_is_full_overlap_not_zero(self):
        # Nothing to disagree about -- a zero-gap result reproduced
        # identically is perfect agreement, not perfect disagreement.
        self.assertEqual(_gap_overlap([], []), 1.0)

    def test_title_matching_is_case_and_whitespace_insensitive(self):
        self.assertEqual(_gap_overlap([_g("Missing   Validation")], [_g("missing validation")]), 1.0)


class ClaimStabilityTests(unittest.TestCase):
    def test_identical_sets_full_stability(self):
        gaps = [_g("A"), _g("B")]
        self.assertEqual(_claim_stability(gaps, gaps), 1.0)

    def test_disjoint_sets_zero_stability(self):
        self.assertEqual(_claim_stability([_g("A")], [_g("B")]), 0.0)

    def test_differs_from_jaccard_when_set_sizes_differ(self):
        # A={X}, B={X,Y,Z}: stability = avg(1/1, 1/3) = 2/3; Jaccard = 1/3.
        a = [_g("X")]
        b = [_g("X"), _g("Y"), _g("Z")]
        stability = _claim_stability(a, b)
        overlap = _gap_overlap(a, b)
        self.assertAlmostEqual(stability, 2 / 3)
        self.assertAlmostEqual(overlap, 1 / 3)
        self.assertNotEqual(round(stability, 3), round(overlap, 3))


class RankingCorrelationTests(unittest.TestCase):
    def test_fewer_than_two_common_gaps_is_undefined(self):
        self.assertIsNone(_ranking_correlation([_g("A")], [_g("B")]))
        self.assertIsNone(_ranking_correlation([_g("A")], [_g("A")]))

    def test_same_relative_order_gives_positive_correlation(self):
        a = [_g("A"), _g("B"), _g("C")]
        b = [_g("A"), _g("B"), _g("C")]
        corr = _ranking_correlation(a, b)
        self.assertIsNotNone(corr)
        self.assertAlmostEqual(corr, 1.0)

    def test_reversed_order_gives_negative_correlation(self):
        a = [_g("A"), _g("B"), _g("C")]
        b = [_g("C"), _g("B"), _g("A")]
        corr = _ranking_correlation(a, b)
        self.assertIsNotNone(corr)
        self.assertLess(corr, 0)


class ConfidenceDriftTests(unittest.TestCase):
    def test_no_common_gaps_is_undefined(self):
        self.assertIsNone(_confidence_drift([_g("A")], [_g("B")]))

    def test_identical_confidence_zero_drift(self):
        a = [_g("A", "high")]
        b = [_g("A", "high")]
        self.assertEqual(_confidence_drift(a, b), 0.0)

    def test_high_vs_low_gives_max_drift(self):
        a = [_g("A", "high")]
        b = [_g("A", "low")]
        self.assertEqual(_confidence_drift(a, b), 1.0)

    def test_high_vs_medium_gives_half_drift(self):
        a = [_g("A", "high")]
        b = [_g("A", "medium")]
        self.assertEqual(_confidence_drift(a, b), 0.5)


class DuplicateRunDetectionTests(unittest.TestCase):
    def test_identical_content_and_order_is_duplicate(self):
        run = [_g("A", "high"), _g("B", "medium")]
        self.assertTrue(_is_likely_duplicate_run(run, list(run)))

    def test_different_order_is_not_duplicate(self):
        a = [_g("A", "high"), _g("B", "medium")]
        b = [_g("B", "medium"), _g("A", "high")]
        self.assertFalse(_is_likely_duplicate_run(a, b))

    def test_different_confidence_is_not_duplicate(self):
        a = [_g("A", "high")]
        b = [_g("A", "medium")]
        self.assertFalse(_is_likely_duplicate_run(a, b))

    def test_different_length_is_not_duplicate(self):
        a = [_g("A")]
        b = [_g("A"), _g("B")]
        self.assertFalse(_is_likely_duplicate_run(a, b))

    def test_both_empty_is_not_flagged_duplicate(self):
        # Two genuinely empty gap lists aren't "the same saved list", just
        # two runs that both found nothing -- distinct from the real
        # Computational-Lab-reuse case this detection targets.
        self.assertFalse(_is_likely_duplicate_run([], []))


class ComputeRepeatabilityScoreTests(unittest.TestCase):
    def test_raises_on_fewer_than_two_runs(self):
        with self.assertRaises(ValueError):
            compute_repeatability_score([[_g("A")]])

    def test_two_identical_runs_are_flagged_and_excluded_from_the_means(self):
        # Real-data finding (2026-08-22): app.py's Computational Lab
        # feature saves the SAME pipeline results under a new run_id
        # alongside new simulation output -- two runs can be identical
        # without being an independent repeat, so this must not be
        # silently averaged in as "perfect repeatability" by default.
        run = [_g("A", "high"), _g("B", "medium")]
        report = compute_repeatability_score([run, list(run)])
        self.assertEqual(report["n_runs"], 2)
        self.assertEqual(report["n_pairs"], 1)
        self.assertEqual(report["n_duplicate_pairs_excluded"], 1)
        self.assertIsNone(report["gap_overlap_mean"])
        self.assertIsNone(report["claim_stability_mean"])
        self.assertIsNone(report["confidence_drift_mean"])
        self.assertTrue(report["pairs"][0]["likely_duplicate_run"])
        self.assertIsNotNone(report["duplicate_run_note"])

    def test_include_duplicate_runs_true_restores_the_raw_numbers(self):
        run = [_g("A", "high"), _g("B", "medium")]
        report = compute_repeatability_score([run, list(run)], include_duplicate_runs=True)
        self.assertEqual(report["n_duplicate_pairs_excluded"], 0)
        self.assertEqual(report["gap_overlap_mean"], 1.0)
        self.assertEqual(report["claim_stability_mean"], 1.0)
        self.assertEqual(report["confidence_drift_mean"], 0.0)

    def test_same_titles_different_order_is_not_flagged_as_duplicate(self):
        # Order differing is a real (if coincidental) independent-run
        # signal, not the "same saved list" signature -- must not be
        # over-broadly flagged.
        run_a = [_g("A", "high"), _g("B", "medium")]
        run_b = [_g("B", "medium"), _g("A", "high")]
        report = compute_repeatability_score([run_a, run_b])
        self.assertFalse(report["pairs"][0]["likely_duplicate_run"])
        self.assertIsNotNone(report["gap_overlap_mean"])

    def test_genuinely_different_runs_are_not_flagged_as_duplicate(self):
        report = compute_repeatability_score([[_g("A")], [_g("B")]])
        self.assertFalse(report["pairs"][0]["likely_duplicate_run"])
        self.assertIsNone(report["duplicate_run_note"])

    def test_three_runs_produces_three_pairs(self):
        run1 = [_g("A"), _g("B")]
        run2 = [_g("A"), _g("C")]
        run3 = [_g("B"), _g("C")]
        report = compute_repeatability_score([run1, run2, run3])
        self.assertEqual(report["n_pairs"], 3)
        self.assertLess(report["gap_overlap_mean"], 1.0)

    def test_run_ids_are_used_in_pair_labels(self):
        report = compute_repeatability_score([[_g("A")], [_g("A")]], run_ids=["run_x", "run_y"])
        self.assertEqual(report["pairs"][0]["run_a"], "run_x")
        self.assertEqual(report["pairs"][0]["run_b"], "run_y")

    def test_ranking_proxy_note_present_and_honest(self):
        report = compute_repeatability_score([[_g("A")], [_g("A")]])
        self.assertIn("opportunity_score", report["ranking_proxy_note"])

    def test_undefined_pairs_are_not_silently_averaged_as_zero(self):
        # No common gaps at all across any pair -- ranking_correlation_mean
        # and confidence_drift_mean must be None, not 0.0 (which would
        # falsely claim "confirmed zero drift/no correlation").
        run1 = [_g("A")]
        run2 = [_g("B")]
        report = compute_repeatability_score([run1, run2])
        self.assertIsNone(report["ranking_correlation_mean"])
        self.assertIsNone(report["confidence_drift_mean"])
        self.assertEqual(report["ranking_correlation_undefined_pairs"], 1)
        self.assertEqual(report["confidence_drift_undefined_pairs"], 1)


if __name__ == "__main__":
    unittest.main()
