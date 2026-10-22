import json

import pytest

from pipeline import feedback_context as fc
from pipeline.gap_agents import find_gaps, paper_support
from pipeline.proposal_generator import review_proposals
from tests.test_gap_agents import (CONTEXT, EVIDENCE, GRAPH, PROFILES, WIKI, FakeClient, gap, handle)
from utils.azure_client import Success

FLOW = "Add flow to static culture models"
MRNA = "Test mRNA delivery in infected CF chips"
SINGLE = "Single cell source in the chip study"


def replies():
    return {
        "limitation_miner": [gap(FLOW, [handle("a.pdf", 0)])],
        "cross_paper_synthesizer": [gap(MRNA, [handle("b.pdf", 0), handle("a.pdf", 1)])],
        "methodology_auditor": lambda user: [gap(SINGLE, [])] if "Airway chip paper" in user else [],
    }


def equal_critic(cands):
    return [{"id": c["id"], "novelty": 4, "importance": 4, "feasibility": 4, "verdict": "keep"} for c in cands]


class SpyClient(FakeClient):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.critic_user = ""

    def chat_json(self, system, user, **kw):
        if "Methodology Critic" in system:
            self.critic_user = user
        return super().chat_json(system, user, **kw)


def run(client, **kw):
    return find_gaps(WIKI, GRAPH, CONTEXT, client, EVIDENCE, PROFILES, **kw)


# ── feedback_adjustment (pure) ──────────────────────────────────────────────────────────────
def _item(title, rating, reason="Not relevant to my project", kind="gap"):
    return {"kind": kind, "title": title, "rating": rating, "reason": reason}


def test_a_gap_like_a_downvoted_one_is_penalised_and_one_like_an_upvoted_one_boosted():
    delta, note = fc.feedback_adjustment("Add flow to static culture airway models", [_item(FLOW, -1)])
    assert delta == fc.PENALTY and "not useful" in note and "Not relevant" in note
    delta, note = fc.feedback_adjustment(FLOW, [_item(FLOW, 1, "Useful and well supported")])
    assert delta == fc.BOOST and "useful" in note


def test_unrelated_gaps_and_run_feedback_are_not_affected():
    assert fc.feedback_adjustment(MRNA, [_item(FLOW, -1)]) == (0.0, "")
    assert fc.feedback_adjustment(FLOW, [_item("Overall analysis", -1, kind="run")]) == (0.0, "")
    assert fc.feedback_adjustment("", [_item(FLOW, -1)]) == (0.0, "")


def test_the_total_adjustment_is_capped():
    many = [_item(FLOW, -1)] * 5
    assert fc.feedback_adjustment(FLOW, many)[0] == -1.5
    assert fc.feedback_adjustment(FLOW, [_item(FLOW, 1)] * 5)[0] == 1.0


# ── ranking and prompts ─────────────────────────────────────────────────────────────────────
def test_without_feedback_nothing_is_adjusted_or_noted():
    out = run(FakeClient(replies(), equal_critic))
    assert out["diagnostics"]["feedback_adjusted"] == []
    assert not any("feedback_note" in g for g in out["gaps"])


def test_a_downvoted_gap_ranks_below_equal_scoring_gaps_next_run():
    out = run(FakeClient(replies(), equal_critic), feedback_items=[_item(FLOW, -1)])
    assert out["gaps"][-1]["title"] == FLOW
    low = out["gaps"][-1]
    assert low["feedback_note"] and low["composite_score"] < out["gaps"][0]["composite_score"]
    assert out["diagnostics"]["feedback_adjusted"] == [{"title": FLOW, "change": fc.PENALTY}]


def test_an_upvoted_gap_scores_half_a_point_higher():
    plain = {g["title"]: g["composite_score"] for g in run(FakeClient(replies(), equal_critic))["gaps"]}
    out = run(FakeClient(replies(), equal_critic), feedback_items=[_item(SINGLE, 1, "Useful and well supported")])
    boosted = {g["title"]: g["composite_score"] for g in out["gaps"]}
    assert boosted[SINGLE] == round(plain[SINGLE] + fc.BOOST, 2)
    assert boosted[FLOW] == plain[FLOW] and boosted[MRNA] == plain[MRNA]


def test_the_critic_prompt_carries_the_feedback_text():
    client = SpyClient(replies(), equal_critic)
    run(client, feedback_text="Researcher feedback from earlier analyses in this project:\n- \"x\" marked not useful")
    assert "Researcher feedback from earlier analyses" in client.critic_user
    client2 = SpyClient(replies(), equal_critic)
    run(client2)
    assert "Researcher feedback" not in client2.critic_user


def test_the_reviewer_prompt_carries_the_feedback_text():
    seen = {}

    class Reviewer:
        def set_stage(self, s): pass
        def chat_json(self, system, user, **kw):
            seen["user"] = user
            return Success(json.dumps({"reviews": []}))

    props = [{"title": "P", "problem_statement": "p", "methodology": "m", "novelty": "n", "addresses_gap_id": "g"}]
    review_proposals(props, [], Reviewer(), feedback_text="Researcher feedback: avoid vague ones")
    assert "Researcher feedback: avoid vague ones" in seen["user"]


def test_feedback_from_the_database_reaches_find_gaps_input(isolated_env):
    import utils.database as db
    from tests.fixtures.make_golden_run import seed_run
    run_id = seed_run()
    db.upsert_feedback(project_id=db.DEFAULT_PROJECT_ID, run_id=run_id, target_type="gap", target_id="gid-1",
                       target_label=FLOW, rating=-1, reason=fc.REASON_NOT_RELEVANT, comment="not my topic")
    items = fc.get_feedback_items(db.DEFAULT_PROJECT_ID, "all")
    assert any(i["title"] == FLOW and i["rating"] == -1 for i in items)
    out = run(FakeClient(replies(), equal_critic), feedback_items=items)
    assert out["gaps"][-1]["title"] == FLOW
    assert "not my topic" in fc.build_feedback_context(db.DEFAULT_PROJECT_ID, "agent")


# ── coverage rule ───────────────────────────────────────────────────────────────────────────
def lopsided_critic(cands):
    """The only gap citing b.pdf (the survey) is the lowest scored."""
    out = []
    for c in cands:
        low = c["title"] == MRNA
        out.append({"id": c["id"], "novelty": 1 if low else 5, "importance": 1 if low else 5,
                    "feasibility": 1 if low else 5, "verdict": "keep"})
    return out


def test_a_paper_that_supports_no_gap_is_reported():
    out = run(FakeClient(replies(), lopsided_critic), max_gaps=2)
    assert [g["title"] for g in out["gaps"]] == [FLOW, SINGLE] or MRNA not in [g["title"] for g in out["gaps"]]
    assert out["diagnostics"]["papers_without_gaps"] == ["Survey paper"]
    assert out["diagnostics"]["paper_support"]["b.pdf"] == 0


def test_a_minimum_per_paper_promotes_the_best_gap_citing_it():
    out = run(FakeClient(replies(), lopsided_critic), max_gaps=2, min_gaps_per_paper=1)
    titles = [g["title"] for g in out["gaps"]]
    assert MRNA in titles and len(titles) == 3                  # promoted beyond the cut
    assert out["diagnostics"]["papers_without_gaps"] == []
    assert out["diagnostics"]["promoted_for_coverage"] == [{"paper": "b.pdf", "title": MRNA}]
    assert [g["rank"] for g in out["gaps"]] == [1, 2, 3]
    assert MRNA not in [g["title"] for g in out["rejected"]]


def test_no_promotion_when_every_paper_is_already_supported():
    out = run(FakeClient(replies(), equal_critic), min_gaps_per_paper=1)
    assert out["diagnostics"]["promoted_for_coverage"] == [] and len(out["gaps"]) == 3


def test_impossible_minimum_does_not_loop_or_invent_gaps():
    out = run(FakeClient(replies(), equal_critic), min_gaps_per_paper=5)
    assert len(out["gaps"]) == 3                                # nothing more to promote; it simply stops


def test_paper_support_counts_by_title_or_filename():
    titles = {"a.pdf": "Airway chip paper", "b.pdf": "Survey paper"}
    gaps = [{"supporting_papers": ["Airway chip paper"]}, {"supporting_papers": ["Survey paper", "a.pdf"]}]
    assert paper_support(gaps, EVIDENCE, titles) == {"a.pdf": 2, "b.pdf": 1}
