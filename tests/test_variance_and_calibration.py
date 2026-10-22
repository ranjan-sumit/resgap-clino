import json
from unittest.mock import patch

import pytest

from pipeline import gap_agents, proposal_generator
from pipeline import run_pipeline as rp
from pipeline import variance as vr
from pipeline.agent_config import GAP_CRITIC, PROPOSAL_REVIEWER
from pipeline.gap_agents import find_gaps
from pipeline.run_quality import compute_run_quality
from tests.fixtures.make_golden_run import golden_results, seed_run
from tests.test_gap_agents import CONTEXT, EVIDENCE, GRAPH, PROFILES, WIKI, FakeClient, gap, handle
from utils.model_router import ModelConfig, ModelSpec
from utils.model_settings import recommend


# ── rubric anchors ──────────────────────────────────────────────────────────────────────────
def test_critic_and_reviewer_prompts_carry_scoring_anchors_with_examples():
    for prompt in (gap_agents._CRITIC_PROMPT, proposal_generator._REVIEWER_PROMPT):
        assert "SCORING ANCHORS" in prompt and "Use the whole 1-5 range" in prompt
        assert "Example of a" in prompt and "1 =" in prompt and "5 =" in prompt


def test_the_prompt_versions_changed_with_the_prompts():
    assert GAP_CRITIC.prompt_version == "2" and PROPOSAL_REVIEWER.prompt_version == "2"


def test_the_prompts_still_ask_for_their_json_shape():
    assert '"reviews"' in gap_agents._CRITIC_PROMPT and "Review every candidate id exactly once" in gap_agents._CRITIC_PROMPT
    assert '"reviews"' in proposal_generator._REVIEWER_PROMPT


# ── score spread ────────────────────────────────────────────────────────────────────────────
def test_spread_flags_identical_scores_only_with_enough_items():
    assert vr.score_spread([4, 4, 4])["flat"] is True
    assert vr.score_spread([4, 4])["flat"] is False                     # two items cannot show a spread
    s = vr.score_spread([2, 3, 5, 5])
    assert (s["distinct"], s["min"], s["max"], s["flat"]) == (3, 2.0, 5.0, False) and s["stdev"] > 0
    assert vr.score_spread([None, "x", True])["n"] == 0


def _proposal(sp, no, fe, im):
    return {"review": {"scores": {"specificity": sp, "novelty": no, "feasibility": fe, "impact": im}}}


def test_a_reviewer_that_gives_every_proposal_4_4_4_4_is_called_out():
    rep = vr.calibration_report([], [_proposal(4, 4, 4, 4)] * 3)
    assert any("identical scores" in w and "4/4/4/4" in w for w in rep["warnings"])
    assert rep["reviewer"]["impact"]["flat"] is True


def test_a_mixed_quality_fixture_gives_a_spread_and_no_warning():
    props = [_proposal(5, 4, 4, 4), _proposal(2, 2, 3, 2), _proposal(3, 3, 5, 3)]
    gaps = [{"scores": {"novelty": 5, "importance": 4, "feasibility": 3}},
            {"scores": {"novelty": 2, "importance": 2, "feasibility": 5}},
            {"scores": {"novelty": 3, "importance": 5, "feasibility": 2}}]
    rep = vr.calibration_report(gaps, props)
    assert rep["warnings"] == []
    assert all(not s["flat"] and s["distinct"] > 1 for s in rep["reviewer"].values())


def test_one_flat_criterion_is_named():
    props = [_proposal(5, 4, 4, 4), _proposal(2, 2, 4, 2), _proposal(3, 3, 4, 3)]
    assert any("every proposal the same on feasibility" in w for w in vr.calibration_report([], props)["warnings"])


def test_a_critic_that_scores_everything_alike_is_called_out():
    gaps = [{"scores": {"novelty": 3, "importance": 3, "feasibility": 3}}] * 4
    assert any("all 4 gaps identical scores" in w for w in vr.calibration_report(gaps, [])["warnings"])


def test_critic_spread_is_measured_on_the_final_gaps_of_a_real_find_gaps_call():
    def critic(cands):
        return [{"id": c["id"], "novelty": n, "importance": n, "feasibility": 6 - n, "verdict": "keep"}
                for c, n in zip(cands, (5, 3, 1, 4, 2))]
    replies = {"limitation_miner": [gap("Add flow to static culture models", [handle("a.pdf", 0)])],
               "cross_paper_synthesizer": [gap("Test mRNA delivery in infected CF chips", [handle("b.pdf", 0), handle("a.pdf", 1)])],
               "methodology_auditor": lambda user: [gap("Single cell source in the chip study", [])] if "Airway chip paper" in user else []}
    out = find_gaps(WIKI, GRAPH, CONTEXT, FakeClient(replies, critic), EVIDENCE, PROFILES)
    rep = vr.calibration_report(out["gaps"], [])
    assert rep["critic"]["novelty"]["distinct"] == 3 and rep["warnings"] == []


# ── independence of the judge ───────────────────────────────────────────────────────────────
def test_a_judge_that_is_the_writer_is_flagged_and_a_different_model_is_not():
    cfg = recommend({"gemini"})
    assert vr.self_preference_note(cfg) is None                         # chair uses the stronger model
    same = ModelConfig({**cfg.roles, "council_chair": cfg.roles["analysis"]}, cfg.fallback)
    note = vr.self_preference_note(same)
    assert note and cfg.roles["analysis"].model in note and "Council chair" in note


# ── temperature ─────────────────────────────────────────────────────────────────────────────
def test_structured_stages_use_a_low_temperature():
    from utils.azure_client import AzureOpenAIClient
    with patch("utils.azure_client.OpenAI"):
        client = AzureOpenAIClient(api_key="k", base_url="https://example.test/v1", model="m", fallback_model=None)
    with patch.object(client, "chat") as chat:
        client.chat_json("system", "user")
    assert chat.call_args.kwargs["temperature"] <= 0.1


# ── run-to-run agreement ────────────────────────────────────────────────────────────────────
RUN_A = [
    {"title": "Add flow to static culture airway chip models", "description": "Static culture lacks shear flow so cilia behave abnormally"},
    {"title": "Test mRNA delivery in infected CF airway chips", "description": "Gene therapy delivery through mucus has not been tested in infection models"},
    {"title": "Single cell source limits chip generalisability", "description": "All chips derive from one donor cell source"},
]
RUN_B = [   # the same findings, reworded and reordered, plus one new gap
    {"title": "Gene therapy mRNA delivery through infected mucus in CF chips", "description": "Delivery of mRNA across mucus in an infection model is untested"},
    {"title": "Shear flow missing from static airway chip culture", "description": "Cilia behave abnormally without flow in static culture"},
    {"title": "Cost-effectiveness of modulators in low income countries", "description": "No economic analysis exists for access"},
]


def test_reworded_runs_on_the_same_corpus_overlap_above_a_threshold():
    out = vr.semantic_gap_overlap(RUN_A, RUN_B)
    assert out["matched"] == 2 and out["only_in_a"] == 1 and out["only_in_b"] == 1
    assert out["overlap"] == 0.5 and out["overlap"] >= 0.4
    pairs = {(m["a"], m["b"]) for m in out["matches"]}
    assert ("Add flow to static culture airway chip models", "Shear flow missing from static airway chip culture") in pairs


def test_identical_and_unrelated_runs():
    assert vr.semantic_gap_overlap(RUN_A, RUN_A)["overlap"] == 1.0
    assert vr.semantic_gap_overlap(RUN_A, RUN_B[2:])["overlap"] == 0.0
    assert vr.semantic_gap_overlap([], [])["overlap"] == 1.0
    assert vr.semantic_gap_overlap(RUN_A, [])["overlap"] == 0.0


def test_matching_is_one_to_one():
    twin = [{"title": "airway chip static culture flow", "description": "shear flow culture"}] * 2
    out = vr.semantic_gap_overlap(twin, [twin[0]])
    assert out["matched"] == 1 and out["only_in_a"] == 1


def test_only_runs_on_the_same_papers_are_comparable():
    a, b = golden_results(), golden_results()
    assert vr.same_paper_set(a, b)
    b["papers"] = b["papers"][:2]
    assert not vr.same_paper_set(a, b)
    assert vr.compare_with_previous(a, b) is None
    assert vr.compare_with_previous(a, golden_results(), "r0")["vs_run"] == "r0"
    assert not vr.same_paper_set({}, {})


def test_the_pipeline_finds_the_previous_comparable_run_in_the_project(isolated_env):
    previous = golden_results()
    previous["gaps"] = [dict(g) for g in previous["gaps"]]
    pid = seed_run(previous, name="earlier")
    other = golden_results()
    other["papers"] = other["papers"][:1]
    seed_run(other, name="different papers")                                   # newer, but not comparable
    current = golden_results()
    found = rp._repeatability_vs_previous(current, "default")
    assert found and found["vs_run"] == pid and found["overlap"] == 1.0 and found["n_previous"] == 2


def test_no_previous_run_means_no_metric(isolated_env):
    assert rp._repeatability_vs_previous(golden_results(), "default") is None


def test_a_database_problem_never_breaks_the_run(isolated_env):
    with patch("utils.database.list_runs", side_effect=RuntimeError("db down")):
        assert rp._repeatability_vs_previous(golden_results(), "default") is None


# ── stored with the run ─────────────────────────────────────────────────────────────────────
def test_run_quality_carries_the_new_metrics():
    r = golden_results()
    r["repeatability"] = {"overlap": 0.62}
    r["calibration"] = {"warnings": ["x"]}
    q = compute_run_quality(r)
    assert q["repeatability_overlap"] == 0.62 and q["judges_flat"] is True
    q2 = compute_run_quality(golden_results())
    assert q2["repeatability_overlap"] is None and q2["judges_flat"] is False


def test_overview_shows_agreement_and_calibration_warnings():
    from ui import evidence_view as ev
    r = golden_results()
    r["repeatability"] = {"overlap": 0.5}
    r["calibration"] = {"warnings": ["The proposal reviewer gave all 3 proposals identical scores (for example 4/4/4/4)"]}
    assert "50% agreement with the previous run" in ev.quality_chips(r)
    assert any("identical scores" in w for w in ev.warnings_summary(r))
