"""
Tests for Story 3.2: pipeline/pooling.py implements DerSimonian-Laird
random-effects meta-analysis pooling for combining odds/relative/hazard
ratios extracted from multiple papers, replacing the old (buggy) direct
multiplication of independently-sampled per-study ratios. Standalone per
AC #3 -- no dependency on pipeline.simulation_engine.
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.pooling import pool_risk_ratios, sample_pooled_risk, _pool


def _ratio(value, ci_lower=None, ci_upper=None, confidence="high"):
    p = {"value": value, "confidence": confidence}
    if ci_lower is not None:
        p["ci_lower"] = ci_lower
    if ci_upper is not None:
        p["ci_upper"] = ci_upper
    return p


class PoolRiskRatiosSingleStudyTests(unittest.TestCase):
    def test_single_study_with_ci_returns_its_own_value_and_ci(self):
        # CI bounds must be geometric-mean-consistent with value (i.e.
        # symmetric around ln(value) in log space) for an exact round-trip
        # -- otherwise the input CI itself wasn't internally consistent
        # with its own point estimate, and a small reconstruction gap is
        # expected, not a bug.
        value = 2.0
        lo = float(value * np.exp(-0.3))
        hi = float(value * np.exp(0.3))
        p = _ratio(value, ci_lower=lo, ci_upper=hi)
        result = pool_risk_ratios([p])
        self.assertAlmostEqual(result["pooled_ratio"], value, places=4)
        self.assertAlmostEqual(result["ci_lower"], lo, places=3)
        self.assertAlmostEqual(result["ci_upper"], hi, places=3)
        self.assertEqual(result["tau_squared"], 0.0)
        self.assertEqual(result["n_studies"], 1)
        self.assertEqual(result["method"], "DerSimonian-Laird")

    def test_single_study_without_ci_uses_fallback_se(self):
        p = _ratio(2.0)
        result = pool_risk_ratios([p])
        self.assertAlmostEqual(result["pooled_ratio"], 2.0, places=4)
        self.assertEqual(result["tau_squared"], 0.0)
        self.assertLess(result["ci_lower"], 2.0)
        self.assertGreater(result["ci_upper"], 2.0)


class PoolRiskRatiosHomogeneousTests(unittest.TestCase):
    def test_two_homogeneous_ratios_near_zero_tau_squared(self):
        params = [_ratio(2.0, 1.8, 2.2), _ratio(2.0, 1.8, 2.2)]
        result = pool_risk_ratios(params)
        self.assertAlmostEqual(result["tau_squared"], 0.0, places=6)
        self.assertAlmostEqual(result["pooled_ratio"], 2.0, places=2)


class PoolRiskRatiosHeterogeneousTests(unittest.TestCase):
    def test_two_heterogeneous_ratios_positive_tau_squared(self):
        params = [_ratio(1.5, 1.3, 1.7), _ratio(4.0, 3.5, 4.5)]
        result = pool_risk_ratios(params)
        self.assertGreater(result["tau_squared"], 0.0)

    def test_random_effects_ci_wider_than_fixed_effect_for_same_data(self):
        # The rigorous AC #2 proof: RE CI vs. FE CI of the SAME data, via
        # the same shared _pool() helper (tau_squared=0 for the FE point) --
        # mathematically guaranteed wider whenever tau_squared > 0.
        params = [_ratio(1.5, 1.3, 1.7), _ratio(4.0, 3.5, 4.5)]
        result = pool_risk_ratios(params)
        self.assertGreater(result["tau_squared"], 0.0)

        y_values = [np.log(p["value"]) for p in params]
        variances = [((np.log(p["ci_upper"]) - np.log(p["ci_lower"])) / 3.92) ** 2 for p in params]
        _, fe_variance = _pool(y_values, variances, 0.0)
        fe_ci_width_log = 2 * 1.96 * (fe_variance ** 0.5)

        re_ci_width_log = np.log(result["ci_upper"]) - np.log(result["ci_lower"])
        self.assertGreater(re_ci_width_log, fe_ci_width_log)

    def test_illustrative_comparison_against_old_multiplication_behavior(self):
        # Illustrative, not a strict proof (these compute different
        # quantities) -- documents that the new pooled sampling differs
        # from the old per-study-multiply approach for the same input.
        params = [_ratio(1.5, 1.3, 1.7), _ratio(4.0, 3.5, 4.5)]
        pooled = pool_risk_ratios(params)
        new_samples = sample_pooled_risk(pooled, 20000)

        # Reproduce the OLD (pre-Story-3.2) logic inline: independently
        # sample each study's own normal distribution and multiply.
        rng = np.random.default_rng(42)
        old_combined = np.ones(20000)
        for p in params:
            std = max((p["ci_upper"] - p["ci_lower"]) / 3.92, 1e-6)
            old_combined *= np.clip(rng.normal(p["value"], std, 20000), 0.1, 20)

        self.assertNotAlmostEqual(float(np.mean(new_samples)), float(np.mean(old_combined)), places=1)


class PoolRiskRatiosEdgeCaseTests(unittest.TestCase):
    def test_empty_list_raises_value_error(self):
        with self.assertRaises(ValueError):
            pool_risk_ratios([])

    def test_skips_non_positive_value_but_pools_the_rest(self):
        params = [_ratio(2.0, 1.8, 2.2), _ratio(-5.0), _ratio(0)]
        result = pool_risk_ratios(params)
        self.assertEqual(result["n_studies"], 1)
        self.assertAlmostEqual(result["pooled_ratio"], 2.0, places=4)

    def test_all_invalid_values_raises_value_error(self):
        params = [_ratio(-1.0), _ratio(0), {"value": None}]
        with self.assertRaises(ValueError):
            pool_risk_ratios(params)

    def test_nan_value_is_skipped_not_silently_included(self):
        params = [_ratio(2.0, 1.8, 2.2), _ratio(float("nan"))]
        result = pool_risk_ratios(params)
        self.assertEqual(result["n_studies"], 1)
        self.assertTrue(np.isfinite(result["pooled_ratio"]))

    def test_infinite_value_is_skipped_not_silently_included(self):
        params = [_ratio(2.0, 1.8, 2.2), _ratio(float("inf"))]
        result = pool_risk_ratios(params)
        self.assertEqual(result["n_studies"], 1)
        self.assertTrue(np.isfinite(result["pooled_ratio"]))

    def test_all_nan_or_inf_raises_value_error(self):
        params = [_ratio(float("nan")), _ratio(float("inf"))]
        with self.assertRaises(ValueError):
            pool_risk_ratios(params)

    def test_inverted_ci_falls_back_to_default_se_not_near_zero_variance(self):
        # ci_lower > ci_upper must NOT produce a negative se that gets
        # floored into a bogus near-zero variance (near-infinite weight) --
        # it must behave IDENTICALLY to having no CI at all (both use the
        # same 0.2-log-scale fallback).
        good = _ratio(2.0, 1.8, 2.2)
        inverted = _ratio(5.0, ci_lower=8.0, ci_upper=2.0)  # reversed bounds
        no_ci = _ratio(5.0)  # no CI at all -> same 0.2 fallback expected

        result_inverted = pool_risk_ratios([good, inverted])
        result_no_ci = pool_risk_ratios([good, no_ci])

        self.assertAlmostEqual(result_inverted["tau_squared"], result_no_ci["tau_squared"], places=6)
        self.assertAlmostEqual(result_inverted["pooled_ratio"], result_no_ci["pooled_ratio"], places=6)

    def test_zero_width_ci_falls_back_to_default_se(self):
        good = _ratio(2.0, 1.8, 2.2)
        zero_width = _ratio(3.0, ci_lower=3.0, ci_upper=3.0)
        result = pool_risk_ratios([good, zero_width])
        self.assertEqual(result["n_studies"], 2)
        self.assertTrue(np.isfinite(result["tau_squared"]))

    def test_low_confidence_param_is_skipped(self):
        params = [_ratio(2.0, 1.8, 2.2, confidence="high"), _ratio(9.0, confidence="low")]
        result = pool_risk_ratios(params)
        self.assertEqual(result["n_studies"], 1)
        self.assertAlmostEqual(result["pooled_ratio"], 2.0, places=4)

    def test_missing_confidence_is_skipped(self):
        params = [_ratio(2.0, 1.8, 2.2, confidence="high"), {"value": 9.0}]
        result = pool_risk_ratios(params)
        self.assertEqual(result["n_studies"], 1)

    def test_all_low_confidence_raises_value_error(self):
        params = [_ratio(2.0, confidence="low"), {"value": 3.0}]
        with self.assertRaises(ValueError):
            pool_risk_ratios(params)


class PoolInternalHelperEdgeCaseTests(unittest.TestCase):
    def test_pool_empty_lists_raises_value_error(self):
        with self.assertRaises(ValueError):
            _pool([], [], 0.0)

    def test_pool_mismatched_lengths_raises_value_error(self):
        with self.assertRaises(ValueError):
            _pool([1.0, 2.0], [0.1], 0.0)


class SamplePooledRiskTests(unittest.TestCase):
    def test_returns_n_samples_within_clip_range(self):
        pooled = pool_risk_ratios([_ratio(2.0, 1.5, 2.7)])
        samples = sample_pooled_risk(pooled, 5000)
        self.assertEqual(len(samples), 5000)
        self.assertTrue((samples >= 0.1).all())
        self.assertTrue((samples <= 20).all())

    def test_empirical_mean_reasonably_close_to_pooled_ratio(self):
        pooled = pool_risk_ratios([_ratio(2.0, 1.5, 2.7)])
        samples = sample_pooled_risk(pooled, 20000)
        mean = float(np.mean(samples))
        self.assertGreater(mean, pooled["pooled_ratio"] / 2)
        self.assertLess(mean, pooled["pooled_ratio"] * 2)


class PoolCiGuardTests(unittest.TestCase):
    def test_all_infinite_cis_fall_back_to_default_se_no_nan(self):
        # inf bounds used to pass hi > lo -> se=inf -> weight 0 for every
        # param -> total_weight 0 -> division by zero -> NaN pooled estimate.
        params = [_ratio(2.0, float("inf"), float("inf")),
                  _ratio(3.0, float("inf"), float("inf"))]
        result = pool_risk_ratios(params)
        self.assertEqual(result["n_studies"], 2)
        self.assertTrue(np.isfinite(result["pooled_ratio"]))
        self.assertTrue(np.isfinite(result["ci_lower"]))
        self.assertTrue(np.isfinite(result["ci_upper"]))

    def test_infinite_ci_behaves_identically_to_no_ci(self):
        good = _ratio(2.0, 1.8, 2.2)
        inf_ci = _ratio(5.0, float("inf"), float("inf"))
        no_ci = _ratio(5.0)
        result_inf = pool_risk_ratios([good, inf_ci])
        result_no_ci = pool_risk_ratios([good, no_ci])
        self.assertAlmostEqual(result_inf["tau_squared"], result_no_ci["tau_squared"], places=6)
        self.assertAlmostEqual(result_inf["pooled_ratio"], result_no_ci["pooled_ratio"], places=6)

    def test_string_ci_bounds_do_not_raise_uncaught(self):
        params = [_ratio(2.0, "not-a-number", "also-not"), _ratio(3.0, 1.0, 5.0)]
        result = pool_risk_ratios(params)
        self.assertEqual(result["n_studies"], 2)
        self.assertTrue(np.isfinite(result["pooled_ratio"]))


if __name__ == "__main__":
    unittest.main()
