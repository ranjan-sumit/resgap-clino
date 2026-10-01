"""
Regression tests for simulation_engine fixes:
  - run_survival_analysis: clamped baseline argument (no NaN from
    base_surv * modifier > 1, no degenerate flat curve from base_surv == 1),
    survival-direction scenario modifiers (Optimistic >= Base >= Pessimistic),
    hazard_ratio applied as a hazard exponent (S(t)**hr), rate/hazard_ratio
    params no longer fed into base_surv calibration.
  - run_monte_carlo: scenario direction for survival-category params, and
    sensitivity ranked by correlating the already-drawn samples.
  - run_tornado: explicit-null CI bounds do not raise.
  - run_bayesian_network: prevalence at/above 100 stays finite.
  - run_bootstrap: mean-zero with zero spread is stable.
  - run_all_applicable: combined sensitivity keeps every importance in [0, 1].
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.simulation_engine import (
    run_monte_carlo,
    run_survival_analysis,
    run_bayesian_network,
    run_bootstrap,
    run_tornado,
    run_simulation,
)


def _param(name, category, value, confidence="high", **extra):
    p = {"name": name, "category": category, "value": value, "confidence": confidence}
    p.update(extra)
    return p


class SurvivalScenarioDirectionTests(unittest.TestCase):
    def test_base_085_all_scenarios_finite_and_correctly_ordered(self):
        params = [_param("sv", "survival", 85.0)]
        result = run_survival_analysis(
            params, ["Base Case", "Optimistic", "Pessimistic"]
        )
        sr = result["scenario_results"]
        for key in ("base_case", "optimistic", "pessimistic"):
            curve = sr[key]["survival_curve"]
            self.assertTrue(all(np.isfinite(curve)), f"{key} curve has NaN/inf")
            self.assertTrue(all(0.0 <= c <= 1.0 for c in curve), f"{key} curve out of range")
        # base 0.85 x Optimistic's 1.25 survival modifier exceeds 1.0 pre-clamp
        self.assertGreaterEqual(
            sr["optimistic"]["five_year_survival"],
            sr["base_case"]["five_year_survival"],
        )
        self.assertGreaterEqual(
            sr["base_case"]["five_year_survival"],
            sr["pessimistic"]["five_year_survival"],
        )

    def test_perfect_baseline_survival_is_clamped_not_degenerate(self):
        # base_surv exactly 1.0 made -log(1)=0 -> lam ~5e9 -> flat curve and
        # median ~3.9e9 years with no error.
        params = [_param("sv", "survival", 100.0)]
        result = run_survival_analysis(params, ["Base Case"])
        sc = result["scenario_results"]["base_case"]
        self.assertTrue(all(np.isfinite(sc["survival_curve"])))
        self.assertLess(sc["median_survival_years"], 1000)
        self.assertGreater(sc["five_year_survival"], 0.0)


class SurvivalHazardRatioTests(unittest.TestCase):
    def test_hr_above_one_lowers_survival_vs_hr_below_one(self):
        base = [_param("sv", "survival", 85.0)]
        high = run_survival_analysis(
            base + [_param("hr", "hazard_ratio", 2.0)], ["Base Case"]
        )
        low = run_survival_analysis(
            base + [_param("hr", "hazard_ratio", 0.5)], ["Base Case"]
        )
        hi5 = high["scenario_results"]["base_case"]["five_year_survival"]
        lo5 = low["scenario_results"]["base_case"]["five_year_survival"]
        self.assertTrue(np.isfinite(hi5) and np.isfinite(lo5))
        self.assertGreater(hi5, 0.0)
        self.assertLess(hi5, lo5)

    def test_extreme_hr_does_not_flatten_or_nan_the_curve(self):
        # HR 200 pre-fix fed 200/100=2.0 through base_surv calibration; any
        # value >= 100 silently flattened the curve.
        params = [
            _param("sv", "survival", 85.0),
            _param("hr", "hazard_ratio", 200.0),
        ]
        result = run_survival_analysis(params, ["Base Case"])
        curve = result["scenario_results"]["base_case"]["survival_curve"]
        self.assertTrue(all(np.isfinite(c) for c in curve))
        self.assertTrue(all(0.0 <= c <= 1.0 for c in curve))
        # S(0) == 1.0 exactly; a real curve must still decline over time
        self.assertLess(curve[-1], curve[0])


class MonteCarloRegressionTests(unittest.TestCase):
    def test_survival_param_optimistic_beats_pessimistic(self):
        # Survival-type quantities: "Optimistic" must RAISE survival, not
        # apply the adverse-outcome modifier that makes it worse.
        params = [_param("sv", "survival", 85.0, ci_lower=80.0, ci_upper=90.0)]
        result = run_monte_carlo(params, ["Base Case", "Optimistic", "Pessimistic"])
        sr = result["scenario_results"]
        self.assertGreaterEqual(
            sr["optimistic"]["sv"]["mean"], sr["base_case"]["sv"]["mean"]
        )
        self.assertGreaterEqual(
            sr["base_case"]["sv"]["mean"], sr["pessimistic"]["sv"]["mean"]
        )

    def test_sensitivity_recovers_known_strong_driver(self):
        # One parameter with a wide CI obviously drives the combined output;
        # the ranking must put it on top, not arbitrary noise from
        # correlating freshly redrawn independent samples.
        params = [
            _param("strong", "prevalence", 50.0, ci_lower=5.0, ci_upper=95.0),
            _param("weak", "prevalence", 50.0, ci_lower=48.0, ci_upper=52.0),
        ]
        result = run_monte_carlo(params, ["Base Case"])
        ranking = result["sensitivity_ranking"]
        self.assertEqual(ranking[0]["parameter"], "strong")
        self.assertGreater(ranking[0]["importance"], 0.5)
        self.assertGreater(ranking[0]["importance"], ranking[-1]["importance"])


class TornadoNullCiTests(unittest.TestCase):
    def test_explicit_null_ci_bounds_fall_back_without_crashing(self):
        # param_extractor.py's schema defines ci_lower/ci_upper as
        # <float or null> -- an explicit None must behave like a missing key.
        params = [_param("prev", "prevalence", 20.0, ci_lower=None, ci_upper=None)]
        result = run_tornado(params, ["Base Case"])
        self.assertEqual(len(result["parameter_swings"]), 1)
        swing = result["parameter_swings"][0]
        self.assertTrue(np.isfinite(swing["swing_total"]))
        self.assertAlmostEqual(swing["swing_total"], 40.0, places=4)


class BayesianBaselineClipTests(unittest.TestCase):
    def test_prevalence_100_and_110_stay_finite(self):
        for value in (100.0, 110.0):
            params = [
                _param("prev", "prevalence", value),
                _param("or1", "odds_ratio", 2.0),
                _param("or2", "odds_ratio", 1.5),
            ]
            result = run_bayesian_network(params, ["Base Case"])
            sc = result["scenario_results"]["base_case"]
            self.assertTrue(np.isfinite(sc["posterior_probability"]), f"value={value}")
            self.assertGreater(sc["posterior_probability"], 0.0)
            self.assertLessEqual(sc["posterior_probability"], 1.0)


class BootstrapZeroMeanTests(unittest.TestCase):
    def test_zero_mean_with_zero_spread_is_stable(self):
        # std < 0.1 * abs(mean) compares against 0 when the mean is 0, so a
        # perfectly reproducible zero-mean result was mislabeled unstable.
        params = [
            _param("a", "prevalence", 0.0),
            _param("b", "proportion", 0.0),
        ]
        result = run_bootstrap(params, ["Base Case"], n_boot=200)
        self.assertEqual(
            result["scenario_results"]["base_case"]["stability"], "stable"
        )


class CombinedSensitivityNormalizationTests(unittest.TestCase):
    def test_tornado_importance_is_normalized_into_unit_range(self):
        # Tornado importance (swing_total/100) is unbounded; the combined
        # ranking must not contain values above 1.0 once normalized.
        params = [
            _param("wide", "prevalence", 50.0, ci_lower=10.0, ci_upper=90.0),
            _param("narrow", "prevalence", 50.0, ci_lower=45.0, ci_upper=55.0),
            _param("mid", "prevalence", 50.0, ci_lower=40.0, ci_upper=60.0),
        ]
        result = run_simulation(params, {}, {})
        combined = result["sensitivity_ranking"]
        self.assertTrue(combined)
        for entry in combined:
            self.assertGreaterEqual(entry["importance"], 0.0)
            self.assertLessEqual(entry["importance"], 1.0)


if __name__ == "__main__":
    unittest.main()
