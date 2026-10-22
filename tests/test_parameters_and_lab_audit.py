import json
import math

import pytest

from pipeline import grounding as gr
from pipeline import param_quality as pq
from pipeline import simulation_engine as se
from pipeline.multi_run import drop_cross_list_duplicates, merge_council_runs
from pipeline.param_extractor import extract_parameters
from pipeline.run_lab import simulation_gate, usable_parameters
from utils.azure_client import Success


def P(name, value, category="prevalence", unit="percent", confidence="high", **kw):
    return {"name": name, "value": value, "category": category, "unit": unit, "confidence": confidence, **kw}


SCEN = ["Base Case"]


# ── B12: opinion vs measured ────────────────────────────────────────────────────────────────
def test_survey_proportions_are_tagged_opinion_and_measured_values_stay_measured():
    survey = P("share_agreeing", 62, "proportion", population="respondents to the global survey")
    lab = P("il8_increase", 35, "mean", unit="absolute", population="CF airway chips")
    pq.annotate_parameters([survey, lab], {})
    assert survey["evidence_kind"] == "opinion" and "respondents" in survey["kind_reason"]
    assert lab["evidence_kind"] == "measured"


def test_everything_from_a_survey_paper_that_is_a_proportion_is_an_opinion():
    p = P("awareness", 40, "proportion", source_paper="Survey paper")
    pq.annotate_parameters([p], {"Survey paper": "survey_or_questionnaire"})
    assert p["evidence_kind"] == "opinion"
    odds = P("or", 2.0, "odds_ratio", unit="ratio", source_paper="Survey paper")
    pq.annotate_parameters([odds], {"Survey paper": "survey_or_questionnaire"})
    assert odds["evidence_kind"] == "measured"                    # a ratio is not a headcount of opinions


def test_the_extractors_own_opinion_tag_is_respected():
    p = P("x", 10, "mean", evidence_kind="opinion")
    pq.annotate_parameters([p])
    assert p["evidence_kind"] == "opinion"


class _Client:
    def __init__(self, reply):
        self.reply = reply

    def set_stage(self, s): pass

    def chat_json(self, system, user, **kw):
        return Success(json.dumps(self.reply))


def test_extract_parameters_tags_survey_answers_and_excludes_them_from_modelling():
    wiki = {"pages": [{"title": "Survey paper", "source_file": "s.pdf", "key_findings": ["62% agree"]}]}
    reply = [{"name": "share_agreeing", "category": "proportion", "value": 62, "unit": "percent",
              "confidence": "medium", "population": "respondents"},
             {"name": "fev1_gain", "category": "mean", "value": 4.1, "unit": "absolute", "confidence": "high"}]
    params = extract_parameters(wiki, [{"filename": "s.pdf", "sections": {"Results": "x"}, "tables": []}],
                                _Client(reply), {"s.pdf": "survey_or_questionnaire"})
    by = {p["name"]: p for p in params}
    assert by["share_agreeing"]["evidence_kind"] == "opinion"
    assert [p["name"] for p in params if pq.is_modelling_input(p)] == ["fev1_gain"]
    assert by["share_agreeing"]["source_file"] == "s.pdf"


def test_opinions_do_not_count_toward_the_simulation_gate():
    opinions = [P(f"o{i}", 50 + i, "proportion", evidence_kind="opinion") for i in range(6)]
    assert usable_parameters(opinions) == []
    allowed, reason = simulation_gate(opinions, {"coverage_score": 8, "recommendation": "proceed"})
    assert allowed is False and "0 usable" in reason
    measured = [P(f"m{i}", 10 + i) for i in range(3)]
    assert simulation_gate(measured + opinions, {"coverage_score": 8})[0] is True


def test_opinions_are_excluded_from_the_simulation_but_kept_in_the_excluded_list():
    params = [P("m1", 10), P("m2", 12, "incidence"), P("op", 55, "proportion", evidence_kind="opinion")]
    usable, excluded = se.filter_confident_params(params)
    assert [p["name"] for p in usable] == ["m1", "m2"] and [p["name"] for p in excluded] == ["op"]


# ── B12: numeric sanity ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("param,fragment", [
    (P("p", 140), "outside 0 to 100"),
    (P("p", -3), "outside 0 to 100"),
    (P("or", -2, "odds_ratio", "ratio"), "outside (0, 100)"),
    (P("hr", 0, "hazard_ratio", "ratio"), "outside (0, 100)"),
    (P("r", -1, "rate", "per_year"), "cannot be negative"),
    (P("c", 50, "prevalence", ci_lower=60, ci_upper=70), "outside its own confidence interval"),
    (P("c", 50, "prevalence", ci_lower=70, ci_upper=60), "lower bound is above"),
    (P("m", 5000, "mean", "per_1000"), "per 1000"),
])
def test_impossible_values_are_flagged(param, fragment):
    assert any(fragment in i for i in pq.sanity_issues(param)), pq.sanity_issues(param)


@pytest.mark.parametrize("param", [
    P("p", 18.5), P("p", 0.2, "transition_probability", "dimensionless"), P("or", 3.4, "odds_ratio", "ratio"),
    P("c", 50, "prevalence", ci_lower=45, ci_upper=55), P("m", -2.5, "mean", "absolute"),
])
def test_plausible_values_pass(param):
    assert pq.sanity_issues(param) == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "12", None, True])
def test_non_numbers_are_flagged(value):
    assert pq.sanity_issues(P("x", value)) == ["value is not a finite number"]


def test_an_impossible_parameter_is_demoted_and_not_modelled():
    p = P("bad", 250)
    pq.annotate_parameters([p])
    assert p["confidence"] == "low" and p["sanity_issues"] and not pq.is_modelling_input(p)


# ── B15: each algorithm on known inputs, and refusing bad ones ──────────────────────────────
def test_monte_carlo_reproduces_known_inputs_and_needs_two_outcomes():
    out = se.run_monte_carlo([P("prev", 20.0, ci_lower=18, ci_upper=22), P("inc", 5.0, "incidence", ci_lower=4, ci_upper=6)], SCEN)
    assert out["scenario_results"]["base_case"]["prev"]["mean"] == pytest.approx(20.0, abs=0.2)
    assert se.check_inputs("monte_carlo", [P("prev", 20.0)])[0] is False
    assert "at least 2 outcome parameters" in se.check_inputs("monte_carlo", [P("prev", 20.0)])[1]
    assert se.check_inputs("monte_carlo", [P("a", 1, "odds_ratio", "ratio"), P("b", 2, "odds_ratio", "ratio")])[0] is False


def test_markov_refuses_without_real_transition_probabilities():
    ok, why = se.check_inputs("markov_chain", [P("prev", 20.0), P("p", 10, "transition_probability")])
    assert ok is False and "generic default matrix" in why
    named = [P("healthy_to_diseased", 12, "transition_probability"), P("diseased_to_death", 20, "transition_probability")]
    assert se.check_inputs("markov_chain", named)[0] is True
    out = se.run_markov(named, SCEN)
    T = out["scenario_results"]["base_case"]["transition_matrix"]
    assert T[0][2] == pytest.approx(0.12 / sum([0.85, 0.10, 0.12, 0.01, 0.01]) , abs=0.05)
    assert all(abs(sum(row) - 1) < 1e-9 for row in T)


def test_survival_needs_a_real_survival_probability_and_gives_its_known_value():
    assert se.check_inputs("survival_analysis", [P("hr", 0.7, "hazard_ratio", "ratio")])[0] is False
    assert se.check_inputs("survival_analysis", [P("s", 150, "survival")])[0] is False       # impossible baseline
    assert se.check_inputs("survival_analysis", [P("s", 60, "survival")])[0] is True
    out = se.run_survival_analysis([P("s", 60.0, "survival")], SCEN)
    curve = out["scenario_results"]["base_case"]["survival_curve"]
    assert curve[0] == 1.0 and curve[5] == pytest.approx(0.6, abs=0.15) and curve == sorted(curve, reverse=True)


def test_conditional_risk_matches_the_hand_calculation_and_needs_a_baseline():
    out = se.run_bayesian_network([P("prev", 10.0), P("or1", 2.0, "odds_ratio", "ratio")], SCEN)
    r = out["scenario_results"]["base_case"]
    assert r["baseline_probability"] == pytest.approx(0.1) and r["posterior_probability"] == pytest.approx(2 / 11, abs=1e-3)
    ok, why = se.check_inputs("bayesian_network", [P("or1", 2.0, "odds_ratio", "ratio")])
    assert ok is False and "invent a 15% baseline" in why


def test_conditional_risk_honours_the_unit_of_the_baseline():
    per_1000 = se.run_bayesian_network([P("prev", 100.0, unit="per_1000"), P("or1", 2.0, "odds_ratio", "ratio")], SCEN)
    assert per_1000["scenario_results"]["base_case"]["baseline_probability"] == pytest.approx(0.1)
    fraction = se.run_bayesian_network([P("prev", 0.1, unit="dimensionless"), P("or1", 2.0, "odds_ratio", "ratio")], SCEN)
    assert fraction["scenario_results"]["base_case"]["baseline_probability"] == pytest.approx(0.1)


def test_bootstrap_uses_only_values_that_can_be_averaged_together():
    mixed = [P(f"p{i}", 10 + i) for i in range(6)] + [P("or", 3.4, "odds_ratio", "ratio"), P("cost", 5000, "other", "absolute")]
    assert [p["name"] for p in se.bootstrap_group(mixed)] == [f"p{i}" for i in range(6)]
    out = se.run_bootstrap(mixed, SCEN)
    assert out["scenario_results"]["base_case"]["mean"] == pytest.approx(12.5, abs=0.5)      # not dragged by 5000
    ok, why = se.check_inputs("bootstrap", [P("a", 1), P("b", 2), P("or", 3, "odds_ratio", "ratio")])
    assert ok is False and "largest such group has 2" in why


def test_tornado_says_where_each_range_came_from():
    out = se.run_tornado([P("a", 10.0, ci_lower=8, ci_upper=13), P("b", 4.0)], SCEN)
    src = {s["parameter"]: s["range_source"] for s in out["parameter_swings"]}
    assert "confidence interval" in src["a"] and "assumed" in src["b"]
    assert se.check_inputs("tornado", [P("z", 0)])[0] is False


def test_hybrid_needs_both_its_parts():
    ok, why = se.check_inputs("hybrid", [P("prev", 20.0), P("inc", 5.0, "incidence")])
    assert ok is False and "transition" in why


def test_run_simulation_refuses_unsuitable_algorithms_with_reasons_and_runs_the_rest():
    params = [P("prev", 20.0), P("inc", 5.0, "incidence"), P("or1", 2.0, "odds_ratio", "ratio")]
    council = {"final_decision": {"selected_model": "markov_chain"}}
    out = se.run_simulation(params, council, {})
    assert "monte_carlo" in out["models_run"] and "tornado" in out["models_run"]
    assert "markov_chain" in out["models_skipped"] and "generic default matrix" in out["models_skipped"]["markov_chain"]
    assert out["algorithm_results"]["markov_chain"] == {"model_used": "markov_chain", "skipped": out["models_skipped"]["markov_chain"]}
    assert all(not math.isnan(v) for v in out["headline_numbers"].values() if isinstance(v, float))


def test_nothing_runs_when_nothing_is_suitable():
    out = se.run_simulation([P("op", 55, "proportion", evidence_kind="opinion")], {}, {})
    assert out["models_run"] == [] and out["scenario_results"] == {}


# ── B15: council output without repeats ─────────────────────────────────────────────────────
def _run(idx, clinical=(), research=()):
    return {"run_index": idx, "final_decision": {"clinical_insights": list(clinical), "research_insights": list(research),
                                                   "novel_finding": {}}}


def test_one_run_repeating_itself_is_not_agreement():
    twice = "Airway chips can model CFTR modulator response in patient cells"
    merged = merge_council_runs([_run(1, clinical=[twice, twice + " accurately"]), _run(2, clinical=["Something else entirely about sputum"])])
    top = merged["clinical_insight_groups"][0]
    assert top["count"] == 1 and top["frequency"] == "1/2 runs"


def test_an_insight_filed_under_both_clinical_and_research_is_shown_once():
    shared = "Airway chips model CFTR modulator response in patient derived cells"
    merged = merge_council_runs([_run(1, clinical=[shared], research=[shared + " reliably", "Test mRNA delivery in infected chips"])])
    research = [g["representative"] for g in merged["research_insight_groups"]]
    assert len(research) == 1 and "mRNA" in research[0]
    assert merged["coverage_stats"]["duplicate_insights_merged"] == 1
    assert merged["clinical_insight_groups"][0].get("also_in_research") is True


def test_distinct_insights_are_never_folded():
    primary = [{"representative": "survey response rates were low among clinicians", "runs": [1], "count": 1}]
    secondary = [{"representative": "organ on chip platforms predict drug response", "runs": [1], "count": 1}]
    kept, folded = drop_cross_list_duplicates(primary, secondary)
    assert kept == secondary and folded == 0


# ── B15: named entities ─────────────────────────────────────────────────────────────────────
KNOWN = gr.corpus_words({"text": "CFTR modulators and IL-8 release in airway chips; FEV1 improved with elexacaftor"})


def test_a_named_entity_no_paper_mentions_is_flagged_and_known_ones_are_not():
    text = "CFTR modulators such as ivacaftor and elexacaftor reduce IL-8 and TNF-alpha, improving FEV1 and BRCA1 status"
    assert gr.unsupported_entities(text, KNOWN) == ["BRCA1", "ivacaftor"]
    assert "CFTR" not in gr.unsupported_entities(text, KNOWN) and "elexacaftor" not in gr.unsupported_entities(text, KNOWN)
    assert "IL-8" not in gr.unsupported_entities(text, KNOWN) and "FEV1" not in gr.unsupported_entities(text, KNOWN)


def test_common_acronyms_and_plain_words_are_not_entities():
    assert gr.entity_candidates("The FDA and WHO use DNA and MRI in an AI study with OR 2.0 and CI 95%") == []


def test_annotate_claims_flags_entities_marks_speculative_and_lowers_confidence():
    items = [{"claim": "ivacaftor will cut exacerbations", "confidence": "high"},
             {"claim": "CFTR modulators help", "confidence": "high"}]
    n = gr.annotate_claims(items, ("claim",), set(), known_words=KNOWN)
    assert n == 1
    assert items[0]["unsupported_entities"] == ["ivacaftor"] and items[0]["speculative"] is True
    assert items[0]["confidence"] == "medium"
    assert "unsupported_entities" not in items[1] and "speculative" not in items[1]


def test_without_known_words_only_numbers_are_checked_as_before():
    items = [{"claim": "ivacaftor raises FEV1 by 35%", "confidence": "high"}]
    gr.annotate_claims(items, ("claim",), {"10"})
    assert "unsupported_entities" not in items[0] and items[0]["unsupported_numbers"] == ["35%"]
