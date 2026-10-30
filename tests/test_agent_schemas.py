"""PR-04a: each agent's items are checked against a schema; bad ones are rejected, counted and logged."""
import json

import pytest

from pipeline import evidence_reader as er
from pipeline import gap_agents as ga
from pipeline import literature_scout as scout
from pipeline.agent_schemas import SCHEMAS, check, keep_valid, valid_or_empty
from pipeline.llm_council import MODEL_SELECTION_AGENTS, MODEL_COUNCIL_FINAL_PROMPT, run_council
from pipeline.param_extractor import derive_cross_paper_parameters
from pipeline.proposal_generator import review_proposals
from tests.fakes import FakeClient
from utils.call_log import CallLog


def client_with_log(*replies):
    c = FakeClient(list(replies))
    c.call_log = CallLog()
    return c


def logged(client):
    return [json.loads(line) for line in client.call_log.to_jsonl().splitlines() if '"schema_error"' in line]


# ── the validator ───────────────────────────────────────────────────────────────────────────
def test_every_schema_accepts_a_realistic_item_and_rejects_an_empty_one():
    good = {
        "reader_item": {"type": "Result", "statement": "HR 0.7", "quote": "q", "passage": "P1", "confidence": "high"},
        "finder_gap": {"title": "T", "description": "D", "evidence_refs": ["E1"], "supporting_papers": ["P"]},
        "critic_review": {"id": "G1", "novelty": 4, "importance": 5, "feasibility": 3, "verdict": "keep"},
        "scout_plan_row": {"id": "G1", "queries": ["a b c"]},
        "scout_assessment": {"status": "partial", "reasoning": "r", "relevant": [1, 2]},
        "proposal": {"title": "T", "problem_statement": "P", "methodology": "M", "builds_on": ["x"]},
        "proposal_review": {"index": 0, "specificity": 4, "novelty": 3, "feasibility": 4, "impact": 4, "verdict": "accept"},
        "parameter": {"name": "orr", "value": 12.5, "ci_lower": None, "unit": "percent", "evidence_kind": "measured"},
        "council_consensus": {"consensus": "agreed", "key_points": ["a"]},
        "reference": {"title": "A study of things", "authors": ["Smith J"], "year": 2020, "doi": None},
        "council_model_choice": {"selected_model": "monte_carlo", "rationale": "r"},
        "council_insights": {"novel_finding": {"title": "t", "claim": "c"}, "clinical_insights": ["a"]},
    }
    assert set(good) == set(SCHEMAS)
    for agent, item in good.items():
        assert check(agent, item) == [], agent
        assert check(agent, {}) != [], agent


@pytest.mark.parametrize("agent,item,fragment", [
    ("critic_review", {"id": "G1", "novelty": 9}, "above 5"),
    ("critic_review", {"id": "G1", "verdict": "maybe"}, "not one of"),
    ("finder_gap", {"title": "", "description": "d"}, "empty"),
    ("finder_gap", {"title": "t", "description": "d", "supporting_papers": [{"x": 1}]}, "expected string"),
    ("parameter", {"name": "p", "value": "lots"}, "expected numlike"),
    ("proposal_review", {"index": -1}, "below 0"),
    ("scout_assessment", {"status": "unknown"}, "not one of"),
    ("reader_item", {"type": "Result"}, "needs one of"),
])
def test_the_error_names_what_is_wrong(agent, item, fragment):
    assert any(fragment in e for e in check(agent, item))


def test_numbers_written_as_text_are_accepted_for_parameters():
    assert check("parameter", {"name": "p", "value": "12.5"}) == []
    assert check("parameter", {"name": "p", "value": "12,5", "ci_lower": "10"}) == []


def test_keep_valid_returns_valid_items_unchanged_and_counts_the_rest():
    a, b = {"title": "A", "description": "d"}, {"title": "B", "description": "d", "gap_type": "dataset"}
    kept, bad = keep_valid("finder_gap", [a, {"title": "no description"}, b, "not an object"])
    assert kept == [a, b] and bad == 2
    assert keep_valid("finder_gap", None) == ([], 0)


# ── the call log ───────────────────────────────────────────────────────────────────────────
def test_schema_errors_are_counted_in_the_summary_and_written_to_the_log_without_keys():
    log = CallLog(secrets=["super-secret-key-value"])
    log.record_schema_error(stage="Stage 4", agent="finder_gap", detail="finder_gap.title: super-secret-key-value")
    assert log.summary()["schema_errors"] == 1
    text = log.to_jsonl()
    assert '"schema_error"' in text and "super-secret-key-value" not in text and "Stage 4" in text


# ── each agent ─────────────────────────────────────────────────────────────────────────────
def test_evidence_reader_rejects_an_item_without_a_statement():
    sentence = "The overall response rate was 41 percent in the treated group of 120 adults."
    segs = [{"text": sentence + " " + "Filler text about the cohort and its follow up. " * 30, "page": 1, "label": "text"}
            for _ in range(2)]
    reply = {"study_type": "other", "evidence": [
        {"type": "Result"},                                                    # no statement: rejected by the schema
        {"type": "Result", "statement": "Response rate 41 percent", "quote": sentence, "passage": "P1"}]}
    client = client_with_log(json.dumps(reply))
    objects, diag = er.read_paper("p.pdf", segs, client)
    assert diag["schema_rejected"] == 1 and diag["dropped_invalid"] >= 1
    assert any(o.text == "Response rate 41 percent" for o in objects)
    assert [e["agent"] for e in logged(client)] == ["reader_item"]


def test_gap_finder_rejects_a_gap_without_a_description():
    reply = {"gaps": [{"title": "Missing everything"},
                      {"title": "Ok", "description": "d", "evidence_refs": ["Eabc"]}]}
    client = client_with_log(json.dumps(reply))
    by_handle = {"Eabc": ("p.pdf", {"evidence_id": "abc", "text": "t", "provenance": {"quote": "q"}})}
    gaps, diag = ga._run_finder(client, "limitation_miner", "sys", "user", by_handle, {"p.pdf": "Paper"})
    assert diag["schema_rejected"] == 1 and diag["proposed"] == 2
    assert [g["title"] for g in gaps] == ["Ok"]
    assert [e["agent"] for e in logged(client)] == ["finder_gap"]


def test_critic_review_with_out_of_range_scores_is_rejected_and_the_valid_one_is_kept():
    reply = {"reviews": [{"id": "G1", "novelty": 9, "importance": 3, "feasibility": 3, "verdict": "keep"},
                         {"id": "G2", "novelty": 4, "importance": 5, "feasibility": 3, "verdict": "keep"}]}
    client = client_with_log(json.dumps(reply))
    cands = [{"_cid": "G1", "lens": "x", "title": "a", "description": "d"}, {"_cid": "G2", "lens": "x", "title": "b", "description": "d"}]
    reviews, error = ga._critic(client, cands)
    assert error is None and set(reviews) == {"G2"}
    assert logged(client)[0]["agent"] == "critic_review"


def test_scout_planner_row_without_an_id_is_rejected():
    reply = {"queries": [{"queries": ["a b c"]}, {"id": "G1", "queries": ["x y z", "q r s"]}]}
    client = client_with_log(json.dumps(reply))
    plan, error = scout.plan_queries([{"gap_id": "gid", "title": "t", "description": "d"}], client)
    assert error is None and plan == {"gid": ["x y z", "q r s"]}
    assert logged(client)[0]["agent"] == "scout_plan_row"


def test_scout_assessor_with_an_unknown_status_is_not_trusted():
    client = client_with_log(json.dumps({"status": "maybe", "reasoning": "r"}))
    result, genuine = scout._assess({"title": "t", "description": "d"}, [{"title": "p", "year": 2020}], client)
    assert genuine is False and result["status"] == "partial"
    assert logged(client)[0]["agent"] == "scout_assessment"


def test_proposal_reviewer_with_a_bad_verdict_leaves_the_proposal_unreviewed():
    proposals = [{"title": "P", "problem_statement": "x", "methodology": "y"}]
    client = client_with_log(json.dumps({"reviews": [{"index": 0, "verdict": "great", "specificity": 4}]}))
    kept, diag = review_proposals(proposals, [], client)
    assert len(kept) == 1 and "review" not in kept[0] and diag["reviewed"] == 0
    assert logged(client)[0]["agent"] == "proposal_review"


def test_parameters_with_a_non_numeric_value_are_rejected():
    params = [{"name": "a", "value": 1.0, "source_paper": "P1"}, {"name": "b", "value": 2.0, "source_paper": "P2"}]
    reply = [{"name": "bad", "value": "unknown"}, {"name": "good", "value": 3.5, "unit": "percent"}]
    client = client_with_log(json.dumps(reply))
    derived = derive_cross_paper_parameters(params, client)
    assert [p["name"] for p in derived] == ["good"] and derived[0]["is_derived"] is True
    assert logged(client)[0]["agent"] == "parameter"


class _Backend:
    def __init__(self, replies):
        self._replies = list(replies)

    def label(self, key):
        return key

    def call(self, key, system, user):
        return self._replies.pop(0) if self._replies else "opinion text"


def test_council_chair_replies_of_the_wrong_shape_are_logged_and_replaced_by_the_safe_fallback():
    client = client_with_log()
    backend = _Backend(["a", "b", "c",                                            # three seats
                        json.dumps({"key_points": ["no consensus field"]}),     # chair: invalid consensus
                        json.dumps({"rationale": "no selected_model"})])        # chair: invalid final decision
    out = run_council(MODEL_SELECTION_AGENTS, "ctx", MODEL_COUNCIL_FINAL_PROMPT, backend,
                      final_schema="council_model_choice", client=client)
    assert out["consensus"]["consensus"].startswith("{")                           # the raw text is kept as the consensus
    assert "decision" in out["final_decision"] and "selected_model" not in out["final_decision"]
    assert [e["agent"] for e in logged(client)] == ["council_consensus", "council_model_choice"]


def test_a_valid_council_reply_passes_untouched():
    client = client_with_log()
    consensus = {"consensus": "use monte carlo", "key_points": ["a"], "confidence": "high"}
    final = {"selected_model": "monte_carlo", "rationale": "r"}
    backend = _Backend(["a", "b", "c", json.dumps(consensus), json.dumps(final)])
    out = run_council(MODEL_SELECTION_AGENTS, "ctx", MODEL_COUNCIL_FINAL_PROMPT, backend,
                      final_schema="council_model_choice", client=client)
    assert out["consensus"] == consensus and out["final_decision"] == final and logged(client) == []


def test_valid_or_empty_passes_a_valid_value_through():
    value = {"status": "open"}
    assert valid_or_empty("scout_assessment", value) is value
    assert valid_or_empty("scout_assessment", {"status": "nope"}) is None
