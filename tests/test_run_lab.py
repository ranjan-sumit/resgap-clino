"""Computational Lab module: the sufficiency gate, and the skipped-simulation path."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import run_lab
from pipeline.llm_council import council_synthesise_insights
from pipeline.run_lab import (
    run_computational_lab, simulation_gate, skipped_model_council, skipped_simulation, usable_parameters,
)


def p(name, value=1.5, **kw):
    return {"name": name, "value": value, "confidence": "high", "is_derived": False, "category": "rate", **kw}


GOOD = [p("a"), p("b"), p("c")]


class UsableTests(unittest.TestCase):
    def test_only_directly_extracted_numeric_non_low_confidence_params_count(self):
        params = [p("ok"), p("derived", is_derived=True), p("low", confidence="low"), p("text", value="high"),
                  p("flag", value=True), p("zero", value=0)]
        self.assertEqual([x["name"] for x in usable_parameters(params)], ["ok", "zero"])


class GateTests(unittest.TestCase):
    def test_enough_good_parameters_pass(self):
        self.assertEqual(simulation_gate(GOOD, {"coverage_score": 7, "recommendation": "proceed"}), (True, ""))

    def test_an_insufficient_recommendation_blocks_and_names_what_is_missing(self):
        ok, reason = simulation_gate(GOOD, {"coverage_score": 1, "recommendation": "insufficient",
                                            "missing_critical": ["disease progression rates"]})
        self.assertFalse(ok)
        self.assertIn("insufficient", reason)
        self.assertIn("disease progression rates", reason)

    def test_low_coverage_blocks_even_without_an_explicit_recommendation(self):
        ok, reason = simulation_gate(GOOD, {"coverage_score": 3, "recommendation": "warn_and_proceed"})
        self.assertFalse(ok)
        self.assertIn("3/10", reason)

    def test_too_few_usable_parameters_blocks(self):
        ok, reason = simulation_gate([p("a"), p("b")], {"coverage_score": 8, "recommendation": "proceed"})
        self.assertFalse(ok)
        self.assertIn("2 usable", reason)

    def test_derived_and_low_confidence_params_do_not_rescue_the_count(self):
        params = [p("a"), p("b"), p("d", is_derived=True), p("l", confidence="low")]
        self.assertFalse(simulation_gate(params, {"coverage_score": 8})[0])

    def test_missing_sufficiency_fields_do_not_crash(self):
        self.assertFalse(simulation_gate([], {})[0])
        self.assertTrue(simulation_gate(GOOD, {})[0])

    def test_the_real_run1_case_is_blocked(self):
        # 17 parameters, all survey rates and demographics; sufficiency said coverage 1/10, insufficient
        params = [p(f"survey_{i}", value=10 + i, category="rate") for i in range(17)]
        ok, _ = simulation_gate(params, {"coverage_score": 1, "recommendation": "insufficient"})
        self.assertFalse(ok)


class CouncilProblemTests(unittest.TestCase):
    def test_a_council_with_findings_has_no_problem(self):
        self.assertIsNone(run_lab.council_problem({"final_decision": {"clinical_insights": ["x"]}}))
        self.assertIsNone(run_lab.council_problem({"final_decision": {"novel_finding": {"title": "t"}}}))

    def test_an_empty_council_names_the_chair_error_and_failed_agents(self):
        council = {"final_decision": {"novel_finding": None, "clinical_insights": []},
                   "all_runs": [{"final_decision": {"chair_error": "Error code: 429 - You exceeded your current quota"}}],
                   "all_agents": [{"failed": True}, {"_failed": True}, {}]}
        msg = run_lab.council_problem(council)
        self.assertIn("no findings", msg)
        self.assertIn("429", msg)
        self.assertIn("2 council agent call(s) failed", msg)

    def test_a_completely_empty_council_still_reports(self):
        self.assertIn("no findings", run_lab.council_problem({}))

    def test_comp_results_carry_the_council_error(self):
        results = OrchestrationTests.RESULTS
        with patch.object(run_lab, "extract_parameters", return_value=GOOD), \
             patch.object(run_lab, "derive_cross_paper_parameters", return_value=[]), \
             patch.object(run_lab, "check_sufficiency", return_value={"coverage_score": 1, "recommendation": "insufficient"}), \
             patch.object(run_lab, "params_to_csv", return_value=""), \
             patch.object(run_lab, "run_discovery_engine", return_value={}), \
             patch.object(run_lab, "run_multi_council", return_value={"final_decision": {}}), \
             patch.object(run_lab, "build_zip", return_value=b""):
            rows = []
            out = run_computational_lab(results, {}, MagicMock(), trace=lambda s, i, o: rows.append((s, o)))
        self.assertIn("no findings", out["council_error"])
        self.assertTrue(any(s == "Stage 11 — Insight council" and o.startswith("WARNING") for s, o in rows))


class SkippedStructuresTests(unittest.TestCase):
    def test_skipped_simulation_has_every_key_the_ui_and_reports_read(self):
        s = skipped_simulation("because")
        for key in ("model_used", "models_run", "headline_numbers", "sensitivity_ranking", "scenario_results",
                    "summary", "algorithm_results"):
            self.assertIn(key, s)
        self.assertTrue(s["skipped"])
        self.assertEqual(s["skip_reason"], "because")
        self.assertEqual(s["models_run"], [])

    def test_skipped_model_council_has_the_final_decision_shape(self):
        c = skipped_model_council("because")
        self.assertEqual(c["final_decision"]["rationale"], "because")
        self.assertEqual(c["agents"], [])


class InsightCouncilContextTests(unittest.TestCase):
    def _context_sent(self, sim):
        seen = {}

        def fake_run_council(agents, context_text, final_prompt, backend=None, **_kw):
            seen["ctx"] = context_text
            return {}
        with patch("pipeline.llm_council.run_council", side_effect=fake_run_council), \
             patch("pipeline.llm_council._backend_for", return_value=MagicMock()):
            council_synthesise_insights(sim, {"hypotheses": [{"title": "H"}]}, [p("a")], [{"title": "G"}],
                                        {"domain": "x"}, MagicMock())
        return seen["ctx"]

    def test_a_skipped_simulation_is_stated_plainly_with_no_numbers(self):
        ctx = self._context_sent(skipped_simulation("coverage is 1/10"))
        self.assertIn("NO SIMULATION WAS RUN", ctx)
        self.assertIn("coverage is 1/10", ctx)
        self.assertIn("NO numerical prediction", ctx)
        self.assertNotIn("Headline numbers", ctx)

    def test_a_real_simulation_still_passes_its_numbers(self):
        ctx = self._context_sent({"models_run": ["monte_carlo"], "headline_numbers": {"x": 0.5},
                                  "sensitivity_ranking": [{"parameter": "a", "importance": 1}]})
        self.assertIn("Headline numbers", ctx)
        self.assertNotIn("NO SIMULATION WAS RUN", ctx)


class OrchestrationTests(unittest.TestCase):
    RESULTS = {"wiki": {"pages": [{}]}, "gaps": [{"title": "g"}], "ref_papers": [],
               "papers": [{"filename": "a.pdf", "sections": {}, "tables": []}]}

    def _run(self, params, sufficiency):
        calls = []
        client = MagicMock()
        with patch.object(run_lab, "extract_parameters", return_value=params), \
             patch.object(run_lab, "derive_cross_paper_parameters", return_value=[]), \
             patch.object(run_lab, "check_sufficiency", return_value=sufficiency), \
             patch.object(run_lab, "params_to_csv", return_value="csv"), \
             patch.object(run_lab, "run_discovery_engine", return_value={"hypotheses": [{"title": "H1"}]}), \
             patch.object(run_lab, "council_select_model", side_effect=lambda *a, **k: calls.append("council") or
                          {"final_decision": {"selected_model": "m"}}), \
             patch.object(run_lab, "filter_confident_params", return_value=(params, [])), \
             patch.object(run_lab, "runnable_models", return_value=["monte_carlo"]), \
             patch.object(run_lab, "run_simulation", side_effect=lambda *a, **k: calls.append("sim") or
                          {"models_run": ["monte_carlo"], "headline_numbers": {"x": 1}}), \
             patch.object(run_lab, "run_multi_council", side_effect=lambda **k: calls.append("insights") or {"final_decision": {}}), \
             patch.object(run_lab, "build_zip", return_value=b"zip"):
            out = run_computational_lab(self.RESULTS, {"domain": "x"}, client)
        return out, calls

    def test_an_insufficient_corpus_skips_the_council_and_simulation_but_not_the_insights(self):
        out, calls = self._run(GOOD, {"coverage_score": 1, "recommendation": "insufficient"})
        self.assertEqual(calls, ["insights"])
        self.assertTrue(out["sim_results"]["skipped"])
        self.assertTrue(out["model_council"]["skipped"])
        self.assertIn("insufficient", out["simulation_skipped"])
        self.assertEqual(out["discovery"]["hypotheses"][0]["title"], "H1")        # discovery still runs

    def test_a_sufficient_corpus_runs_everything(self):
        out, calls = self._run(GOOD, {"coverage_score": 8, "recommendation": "proceed"})
        self.assertEqual(calls, ["council", "sim", "insights"])
        self.assertIsNone(out["simulation_skipped"])
        self.assertEqual(out["sim_results"]["models_run"], ["monte_carlo"])

    def test_comp_results_carry_every_key_the_app_and_database_expect(self):
        out, _ = self._run(GOOD, {"coverage_score": 8})
        for key in ("params", "derived_count", "t1_count", "t2_count", "sufficiency", "csv_data", "discovery",
                    "model_council", "sim_results", "insight_council", "n_runs", "zip_bytes"):
            self.assertIn(key, out)

    def test_progress_and_trace_callbacks_are_used(self):
        msgs, rows = [], []
        client = MagicMock()
        with patch.object(run_lab, "extract_parameters", return_value=GOOD), \
             patch.object(run_lab, "derive_cross_paper_parameters", return_value=[]), \
             patch.object(run_lab, "check_sufficiency", return_value={"coverage_score": 1, "recommendation": "insufficient"}), \
             patch.object(run_lab, "params_to_csv", return_value=""), \
             patch.object(run_lab, "run_discovery_engine", return_value={}), \
             patch.object(run_lab, "run_multi_council", return_value={}), \
             patch.object(run_lab, "build_zip", return_value=b""):
            run_computational_lab(self.RESULTS, {}, client, progress=lambda m, pct: msgs.append(m),
                                  trace=lambda s, i, o: rows.append((s, o)))
        self.assertTrue(any("skipped" in m.lower() for m in msgs))
        self.assertTrue(any(s == "Stage 10 — Simulation" and o.startswith("SKIPPED") for s, o in rows))


if __name__ == "__main__":
    unittest.main()
