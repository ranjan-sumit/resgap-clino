"""
Tests for Story 3.1: simulation_engine only simulates medium/high-confidence
parameters (AD-6). filter_confident_params() is the single, shared choke
point every caller uses; _sample() additionally guards itself as a
belt-and-suspenders check against a future bypass.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.simulation_engine import (
    filter_confident_params,
    _sample,
    run_simulation,
    resolve_models_to_run,
    auto_select_models,
)


def _param(name, confidence, value=10.0, category="prevalence", **extra):
    p = {"name": name, "confidence": confidence, "value": value, "category": category}
    p.update(extra)
    return p


class FilterConfidentParamsTests(unittest.TestCase):
    def test_medium_and_high_are_usable(self):
        params = [_param("a", "high"), _param("b", "medium")]
        usable, excluded = filter_confident_params(params)
        self.assertEqual(usable, params)
        self.assertEqual(excluded, [])

    def test_low_is_excluded(self):
        params = [_param("a", "low")]
        usable, excluded = filter_confident_params(params)
        self.assertEqual(usable, [])
        self.assertEqual(excluded, params)

    def test_missing_confidence_is_excluded(self):
        p = {"name": "a", "value": 10.0, "category": "prevalence"}
        usable, excluded = filter_confident_params([p])
        self.assertEqual(usable, [])
        self.assertEqual(excluded, [p])

    def test_invalid_confidence_value_is_excluded(self):
        # Strict literal match against exactly {"medium", "high"} -- not
        # case-insensitive, not fuzzy.
        params = [_param("a", "Medium"), _param("b", "unknown")]
        usable, excluded = filter_confident_params(params)
        self.assertEqual(usable, [])
        self.assertEqual(excluded, params)


class SampleGuardTests(unittest.TestCase):
    def test_raises_on_low_confidence(self):
        with self.assertRaises(ValueError):
            _sample(_param("a", "low"))

    def test_raises_on_missing_confidence(self):
        with self.assertRaises(ValueError):
            _sample({"name": "a", "value": 10.0})

    def test_does_not_raise_on_medium(self):
        _sample(_param("a", "medium"))  # no exception

    def test_does_not_raise_on_high(self):
        _sample(_param("a", "high"))  # no exception


class RunSimulationConfidenceGateTests(unittest.TestCase):
    def test_excluded_low_confidence_key_present_and_correct(self):
        params = [
            _param("a", "high"),
            _param("b", "low"),
            _param("c", "medium"),
        ]
        result = run_simulation(params, {}, {})
        self.assertIn("excluded_low_confidence", result)
        excluded_names = {p["name"] for p in result["excluded_low_confidence"]}
        self.assertEqual(excluded_names, {"b"})

    def test_all_low_confidence_does_not_crash(self):
        params = [_param("a", "low"), _param("b", "low")]
        result = run_simulation(params, {}, {})
        self.assertEqual(len(result["excluded_low_confidence"]), 2)
        self.assertIn("models_run", result)

    def test_monte_carlo_risk_pooling_excludes_low_confidence_ratio(self):
        # A structural, deterministic proof rather than a statistical one:
        # with the ONLY odds_ratio param being low-confidence, risk_p must
        # end up empty after filtering, so "risk_adjusted_outcome" (only
        # ever added when risk_p is non-empty) must not appear at all.
        params_low_only = [
            _param("prev", "high", value=20.0, category="prevalence"),
            _param("bad_or", "low", value=50.0, category="odds_ratio"),
        ]
        result_low_only = run_simulation(params_low_only, {}, {})
        mc_low_only = result_low_only["algorithm_results"]["monte_carlo"]
        self.assertNotIn("risk_adjusted_outcome", mc_low_only["scenario_results"]["base_case"])

        # Swap in a high-confidence ratio for the same underlying param: now
        # risk_p is non-empty and the key must appear.
        params_high = [
            _param("prev", "high", value=20.0, category="prevalence"),
            _param("good_or", "high", value=2.0, category="odds_ratio"),
        ]
        result_high = run_simulation(params_high, {}, {})
        mc_high = result_high["algorithm_results"]["monte_carlo"]
        self.assertIn("risk_adjusted_outcome", mc_high["scenario_results"]["base_case"])

    def test_monte_carlo_surfaces_risk_pooling_with_positive_tau_squared_for_heterogeneous_ratios(self):
        # Story 3.2 integration proof: run_monte_carlo's wiring to
        # pool_risk_ratios/sample_pooled_risk is actually live end-to-end,
        # not just correct in pooling.py's own isolated unit tests.
        params = [
            _param("prev", "high", value=20.0, category="prevalence",
                   ci_lower=18.0, ci_upper=22.0),
            _param("or1", "high", value=1.5, category="odds_ratio",
                   ci_lower=1.3, ci_upper=1.7),
            _param("or2", "high", value=4.0, category="relative_risk",
                   ci_lower=3.5, ci_upper=4.5),
        ]
        result = run_simulation(params, {}, {})
        mc = result["algorithm_results"]["monte_carlo"]
        base_case = mc["scenario_results"]["base_case"]
        self.assertIn("risk_pooling", base_case)
        pooling = base_case["risk_pooling"]
        self.assertEqual(pooling["method"], "DerSimonian-Laird")
        self.assertEqual(pooling["n_studies"], 2)
        self.assertGreater(pooling["tau_squared"], 0.0)

    def test_all_invalid_risk_ratios_degrade_gracefully_without_crashing_the_model(self):
        # Review fix: pool_risk_ratios raising ValueError (every risk_p
        # entry invalid) must not wipe out the whole Monte Carlo result --
        # only the risk-adjustment step should be skipped.
        params = [
            _param("prev", "high", value=20.0, category="prevalence"),
            _param("bad_or", "high", value=-5.0, category="odds_ratio"),
        ]
        result = run_simulation(params, {}, {})
        mc = result["algorithm_results"]["monte_carlo"]
        self.assertNotIn("error", mc)
        base_case = mc["scenario_results"]["base_case"]
        self.assertNotIn("risk_adjusted_outcome", base_case)
        self.assertNotIn("risk_pooling", base_case)
        self.assertIn("prev", base_case)  # unrelated outcome stats still computed


class ResolveModelsToRunConsistencyTests(unittest.TestCase):
    """Review fix: proves app.py's Stage 10 preview (resolve_models_to_run)
    can no longer diverge from what run_simulation() actually runs --
    including via the council-override path, which the original Task 3 fix
    missed since it only re-filtered params, not the override logic."""

    def test_council_override_not_reachable_by_auto_select_alone_is_still_previewed(self):
        # auto_select_models alone would not pick bayesian_network for a
        # single prevalence param with no risk_p (needs >=2 risk ratios AND
        # a prevalence param) -- only the council override adds it.
        params = [_param("prev", "high", value=15.0, category="prevalence")]
        council_decision = {"final_decision": {"selected_model": "bayesian_network"}}
        preview = resolve_models_to_run(params, council_decision, {})
        self.assertIn("bayesian_network", preview)

    def test_preview_matches_actual_models_run_including_override(self):
        params = [
            _param("prev", "high", value=15.0, category="prevalence"),
            _param("or1", "high", value=2.0, category="odds_ratio"),
            _param("or2", "high", value=1.5, category="relative_risk"),
        ]
        council_decision = {"final_decision": {"selected_model": "markov_chain"}}
        simulation_params, _ = filter_confident_params(params)
        preview = resolve_models_to_run(simulation_params, council_decision, {})
        result = run_simulation(params, council_decision, {})
        self.assertEqual(preview, result["models_run"])


class AutoSelectModelsOwnLogicTests(unittest.TestCase):
    """Review fix: exercises auto_select_models' own heuristics directly,
    without a council override forcing a model in regardless (every prior
    test used council_decision={}, which always defaults selected_model to
    "monte_carlo" and force-inserts it -- narrower coverage than it looked)."""

    def test_empty_params_selects_tornado_and_bootstrap_fallback(self):
        # "tornado" is always included; sparse data (< 5 usable params)
        # also triggers the "bootstrap" fallback per auto_select_models'
        # own coverage-score/param-count heuristic -- neither depends on
        # any council override.
        self.assertEqual(auto_select_models([], {}), ["tornado", "bootstrap"])

    def test_all_low_confidence_reduces_to_tornado_and_bootstrap_with_no_forcing_override(self):
        params = [_param("a", "low"), _param("b", "low")]
        # selected_model maps to nothing in model_map, so no override fires --
        # this exercises auto_select_models' own decision on empty input.
        council_decision = {"final_decision": {"selected_model": "nonexistent_model"}}
        result = run_simulation(params, council_decision, {})
        self.assertEqual(result["models_run"], ["tornado", "bootstrap"])


if __name__ == "__main__":
    unittest.main()
