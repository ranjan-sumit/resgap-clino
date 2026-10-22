"""Proposal Reviewer agent: accept / revise (rewritten once) / reject, with nothing lost on failure."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.proposal_generator import review_proposals
from utils.azure_client import ErrorInfo, Failure, Success


def prop(i, gap_id="g1"):
    return {"title": f"Proposal {i}", "problem_statement": f"problem {i}", "methodology": f"method {i}",
            "novelty": f"novel {i}", "addresses_gap": "Gap one", "addresses_gap_id": gap_id,
            "addresses_gap_id_resolution": "llm_exact", "addresses_gap_ref": "abc"}


GAPS = [{"gap_id": "g1", "title": "Gap one", "description": "d", "evidence": ["Paper (p.2): “quote”"],
         "validation_status": "open", "existing_papers": [{"title": "Existing paper A"}]}]


class FakeClient:
    def __init__(self, review=None, revision=None, fail_review=False, fail_revision=False):
        self.review, self.revision = review, revision
        self.fail_review, self.fail_revision = fail_review, fail_revision
        self.stages, self.calls = [], []

    def set_stage(self, s):
        self.stages.append(s)

    def chat_json(self, system, user, **kw):
        if "grant-panel reviewer" in system:
            self.calls.append("review")
            if self.fail_review:
                return Failure(ErrorInfo(kind="timeout", detail="x"))
            return Success(self.review if isinstance(self.review, str) else json.dumps({"reviews": self.review}))
        self.calls.append("revise")
        if self.fail_revision:
            return Failure(ErrorInfo(kind="timeout", detail="x"))
        return Success(json.dumps(self.revision))


def review(i, verdict, **kw):
    return {"index": i, "specificity": 4, "novelty": 3, "feasibility": 4, "impact": 4, "verdict": verdict,
            "issues": kw.get("issues", []), "required_changes": kw.get("changes", ""), "reason": kw.get("reason", "")}


class ReviewTests(unittest.TestCase):
    def test_accepted_proposals_get_scores_and_stay_unchanged(self):
        out, diag = review_proposals([prop(1), prop(2)], GAPS, FakeClient([review(0, "accept"), review(1, "accept")]))
        self.assertEqual([p["title"] for p in out], ["Proposal 1", "Proposal 2"])
        self.assertEqual(out[0]["review"]["verdict"], "accept")
        self.assertEqual(out[0]["review"]["scores"]["specificity"], 4)
        self.assertEqual(diag["accepted"], 2)

    def test_rejected_proposals_are_removed_and_reported_with_the_reason(self):
        out, diag = review_proposals([prop(1), prop(2)], GAPS,
                                     FakeClient([review(0, "accept"), review(1, "reject", reason="already done")]))
        self.assertEqual([p["title"] for p in out], ["Proposal 1"])
        self.assertEqual(diag["rejected"], [{"title": "Proposal 2", "reason": "already done"}])

    def test_a_revise_verdict_rewrites_once_and_keeps_the_gap_link(self):
        revised = [{"title": "Proposal 1 (sharper)", "problem_statement": "p", "methodology": "m", "novelty": "n"}]
        client = FakeClient([review(0, "revise", changes="name the donor numbers", issues=["vague"])], revised)
        out, diag = review_proposals([prop(1)], GAPS, client)
        self.assertEqual(out[0]["title"], "Proposal 1 (sharper)")
        self.assertEqual(out[0]["addresses_gap_id"], "g1")               # the link survives the rewrite
        self.assertEqual(out[0]["addresses_gap_id_resolution"], "llm_exact")
        self.assertTrue(out[0]["review"]["revised"])
        self.assertEqual(out[0]["review"]["required_changes"], "name the donor numbers")
        self.assertEqual(diag["revised"], 1)
        self.assertEqual(client.calls, ["review", "revise"])             # one review, one revision, no loop

    def test_a_failed_revision_keeps_the_original(self):
        out, diag = review_proposals([prop(1)], GAPS,
                                     FakeClient([review(0, "revise", changes="x")], fail_revision=True))
        self.assertEqual(out[0]["title"], "Proposal 1")
        self.assertEqual(diag["revised"], 0)

    def test_a_failed_review_returns_every_proposal_untouched(self):
        out, diag = review_proposals([prop(1), prop(2)], GAPS, FakeClient(fail_review=True))
        self.assertEqual(len(out), 2)
        self.assertIn("review failed", diag["error"])
        self.assertNotIn("review", out[0])

    def test_an_unreadable_review_returns_every_proposal(self):
        out, diag = review_proposals([prop(1)], GAPS, FakeClient("sorry, no JSON"))
        self.assertEqual(len(out), 1)
        self.assertEqual(diag["error"], "review reply could not be read")

    def test_a_proposal_the_reviewer_skipped_is_kept(self):
        out, _ = review_proposals([prop(1), prop(2)], GAPS, FakeClient([review(0, "accept")]))
        self.assertEqual(len(out), 2)

    def test_an_unknown_verdict_is_treated_as_accept(self):
        out, diag = review_proposals([prop(1)], GAPS, FakeClient([review(0, "maybe")]))
        self.assertEqual(out[0]["review"]["verdict"], "accept")

    def test_the_reviewer_sees_the_gap_evidence_and_what_search_found(self):
        seen = {}

        class Spy(FakeClient):
            def chat_json(self, system, user, **kw):
                seen["user"] = user
                return super().chat_json(system, user, **kw)
        review_proposals([prop(1)], GAPS, Spy([review(0, "accept")]))
        self.assertIn("Existing paper A", seen["user"])
        self.assertIn("quote", seen["user"])

    def test_no_proposals_means_no_calls(self):
        client = FakeClient([])
        out, diag = review_proposals([], GAPS, client)
        self.assertEqual(out, [])
        self.assertEqual(client.calls, [])

    def test_the_reviewer_runs_under_its_own_stage_name(self):
        client = FakeClient([review(0, "accept")])
        review_proposals([prop(1)], GAPS, client)
        self.assertEqual(client.stages[0], "Stage 6b — Proposal Review")


if __name__ == "__main__":
    unittest.main()
