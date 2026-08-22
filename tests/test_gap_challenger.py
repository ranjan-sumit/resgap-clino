"""
Tests for pipeline/gap_challenger.py (Clinova Phase 3, Epic 3.4 -- the
Gap Challenger state machine). Per 10-phased-implementation-plan.md's
Phase 3 testing strategy: "every cell of the decision table exercised."
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import Success, Failure, ErrorInfo
from pipeline.gap_challenger import (
    check_evidence_supported, generate_query_families, run_search_funnel,
    judge_candidates, apply_decision_table, run_challenge,
    SEARCH_COVERAGE_THRESHOLD,
)


def _gap(confidence="high", title="Missing external validation", description="No held-out cohort tested",
         missing_connection="external validation"):
    return {"title": title, "description": description, "missing_connection": missing_connection,
            "confidence": confidence, "gap_type": "evaluation"}


def _candidate(title, year=2023, abstract="something"):
    return {"title": title, "year": year, "abstract": abstract, "source": "Semantic Scholar"}


class EvidenceGateTests(unittest.TestCase):
    def test_high_confidence_passes(self):
        self.assertTrue(check_evidence_supported(_gap(confidence="high")))

    def test_medium_confidence_passes(self):
        self.assertTrue(check_evidence_supported(_gap(confidence="medium")))

    def test_low_confidence_fails(self):
        self.assertFalse(check_evidence_supported(_gap(confidence="low")))

    def test_missing_confidence_fails(self):
        gap = _gap()
        del gap["confidence"]
        self.assertFalse(check_evidence_supported(gap))


class QueryFamilyTests(unittest.TestCase):
    def test_generates_specific_and_broader_queries(self):
        families = generate_query_families(_gap())
        self.assertGreaterEqual(len(families), 2)
        self.assertIn("Missing external validation", families[1])

    def test_domain_boost_adds_a_third_family(self):
        domain_cfg = {"search_boost_terms": ["clinical validation", "healthcare"]}
        families = generate_query_families(_gap(), domain_config=domain_cfg)
        self.assertEqual(len(families), 3)

    def test_no_duplicate_families(self):
        gap = _gap(title="X", missing_connection="")
        families = generate_query_families(gap)
        self.assertEqual(len(families), len(set(families)))

    def test_empty_gap_falls_back_to_description(self):
        gap = {"title": "", "description": "some fallback text", "missing_connection": ""}
        families = generate_query_families(gap)
        self.assertEqual(families, ["some fallback text"])


class SearchFunnelTests(unittest.TestCase):
    @patch("pipeline.gap_challenger._search_arxiv_with_status")
    @patch("pipeline.gap_challenger._search_semantic_scholar_with_status")
    def test_both_providers_succeed_gives_full_coverage(self, mock_ss, mock_arxiv):
        mock_ss.return_value = ([_candidate("Paper A")], True)
        mock_arxiv.return_value = ([_candidate("Paper B")], True)
        funnel = run_search_funnel(["query one"])
        self.assertEqual(funnel["search_coverage_score"], 1.0)
        self.assertEqual(funnel["post_dedup_count"], 2)

    @patch("pipeline.gap_challenger._search_arxiv_with_status")
    @patch("pipeline.gap_challenger._search_semantic_scholar_with_status")
    def test_one_provider_failing_halves_coverage(self, mock_ss, mock_arxiv):
        mock_ss.return_value = ([_candidate("Paper A")], True)
        mock_arxiv.return_value = ([], False)
        funnel = run_search_funnel(["query one"])
        self.assertEqual(funnel["search_coverage_score"], 0.5)

    @patch("pipeline.gap_challenger._search_arxiv_with_status")
    @patch("pipeline.gap_challenger._search_semantic_scholar_with_status")
    def test_both_providers_failing_gives_zero_coverage(self, mock_ss, mock_arxiv):
        mock_ss.return_value = ([], False)
        mock_arxiv.return_value = ([], False)
        funnel = run_search_funnel(["query one"])
        self.assertEqual(funnel["search_coverage_score"], 0.0)

    @patch("pipeline.gap_challenger._search_arxiv_with_status")
    @patch("pipeline.gap_challenger._search_semantic_scholar_with_status")
    def test_a_provider_succeeding_on_any_query_family_counts(self, mock_ss, mock_arxiv):
        # Succeeds (empty result) on the first query, fails on the second --
        # provider_success should still be True once any call succeeds.
        mock_ss.side_effect = [([], True), ([_candidate("A")], True)]
        mock_arxiv.side_effect = [([], False), ([], False)]
        funnel = run_search_funnel(["q1", "q2"])
        self.assertTrue(funnel["provider_success"]["semantic_scholar"])
        self.assertFalse(funnel["provider_success"]["arxiv"])
        self.assertEqual(funnel["search_coverage_score"], 0.5)

    @patch("pipeline.gap_challenger._search_arxiv_with_status")
    @patch("pipeline.gap_challenger._search_semantic_scholar_with_status")
    def test_duplicate_titles_across_queries_are_deduped(self, mock_ss, mock_arxiv):
        mock_ss.return_value = ([_candidate("Same Paper")], True)
        mock_arxiv.return_value = ([_candidate("Same Paper")], True)
        funnel = run_search_funnel(["q1"])
        self.assertEqual(funnel["candidate_count"], 2)
        self.assertEqual(funnel["post_dedup_count"], 1)


class JudgeCandidatesTests(unittest.TestCase):
    def test_successful_judgment_annotates_candidates(self):
        client = MagicMock()
        client.chat_json.return_value = Success(
            '[{"title": "A", "relevant": true, "relevance_type": "direct", '
            '"contradicts_gap": false, "confidence": "high"}]'
        )
        judged = judge_candidates(_gap(), [_candidate("A")], client)
        self.assertEqual(len(judged), 1)
        self.assertTrue(judged[0]["relevant"])
        self.assertEqual(judged[0]["relevance_type"], "direct")
        self.assertEqual(judged[0]["confidence"], "high")

    def test_llm_call_failure_marks_all_not_relevant(self):
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="api_error", detail="down"))
        judged = judge_candidates(_gap(), [_candidate("A"), _candidate("B")], client)
        self.assertEqual(len(judged), 2)
        self.assertTrue(all(not j["relevant"] for j in judged))

    def test_malformed_json_marks_all_not_relevant(self):
        client = MagicMock()
        client.chat_json.return_value = Success("not json at all")
        judged = judge_candidates(_gap(), [_candidate("A")], client)
        self.assertFalse(judged[0]["relevant"])

    def test_empty_candidate_list_returns_empty_without_calling_llm(self):
        client = MagicMock()
        judged = judge_candidates(_gap(), [], client)
        self.assertEqual(judged, [])
        client.chat_json.assert_not_called()

    def test_candidates_capped_at_max(self):
        client = MagicMock()
        client.chat_json.return_value = Success("[]")
        many = [_candidate(f"P{i}") for i in range(20)]
        judged = judge_candidates(_gap(), many, client, max_candidates=8)
        self.assertEqual(len(judged), 8)


def _judged(relevant=True, relevance_type="direct", contradicts=False, confidence="high", title="P"):
    return {"title": title, "relevant": relevant, "relevance_type": relevance_type,
            "contradicts_gap": contradicts, "confidence": confidence}


class DecisionTableTests(unittest.TestCase):
    """Every row of 04-ai-research-architecture.md §5.2's decision table."""

    def test_row1_low_coverage_always_insufficient_evidence_even_with_strong_results(self):
        strong = [_judged() for _ in range(5)]
        result = apply_decision_table(SEARCH_COVERAGE_THRESHOLD - 0.01, strong)
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")

    def test_row1_zero_coverage_insufficient_evidence(self):
        result = apply_decision_table(0.0, [])
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")

    def test_row2_sufficient_coverage_no_results_is_open(self):
        result = apply_decision_table(SEARCH_COVERAGE_THRESHOLD, [])
        self.assertEqual(result["status"], "OPEN")

    def test_row2_sufficient_coverage_only_irrelevant_results_is_open(self):
        irrelevant = [_judged(relevant=False) for _ in range(3)]
        result = apply_decision_table(1.0, irrelevant)
        self.assertEqual(result["status"], "OPEN")

    def test_row3_one_adjacent_relevant_no_contradiction_is_partially_open(self):
        candidates = [_judged(relevant=True, relevance_type="adjacent", contradicts=False, confidence="medium")]
        result = apply_decision_table(1.0, candidates)
        self.assertEqual(result["status"], "PARTIALLY_OPEN")

    def test_row4_relevant_with_contradiction_is_contested(self):
        candidates = [
            _judged(relevant=True, relevance_type="direct", contradicts=True, confidence="high"),
        ]
        result = apply_decision_table(1.0, candidates)
        self.assertEqual(result["status"], "CONTESTED")

    def test_row5_two_converging_high_confidence_no_contradiction_is_likely_closed(self):
        candidates = [
            _judged(relevant=True, relevance_type="direct", contradicts=False, confidence="high", title="A"),
            _judged(relevant=True, relevance_type="direct", contradicts=False, confidence="high", title="B"),
        ]
        result = apply_decision_table(1.0, candidates)
        self.assertEqual(result["status"], "LIKELY_CLOSED")
        self.assertEqual(result["converging_count"], 2)

    def test_row6_three_converging_high_confidence_no_contradiction_is_closed(self):
        candidates = [
            _judged(relevant=True, relevance_type="direct", contradicts=False, confidence="high", title=f"P{i}")
            for i in range(3)
        ]
        result = apply_decision_table(1.0, candidates)
        self.assertEqual(result["status"], "CLOSED")
        self.assertEqual(result["converging_count"], 3)

    def test_contradiction_overrides_would_be_closed_result(self):
        # 3 direct/high-confidence results, but one of them contradicts --
        # must not be CLOSED despite meeting the raw count.
        candidates = [
            _judged(relevant=True, relevance_type="direct", contradicts=False, confidence="high", title="A"),
            _judged(relevant=True, relevance_type="direct", contradicts=False, confidence="high", title="B"),
            _judged(relevant=True, relevance_type="direct", contradicts=True, confidence="high", title="C"),
        ]
        result = apply_decision_table(1.0, candidates)
        self.assertEqual(result["status"], "CONTESTED")

    def test_medium_confidence_direct_results_do_not_count_as_converging(self):
        # Relevant + direct but only medium confidence -- not "converging,
        # high-confidence" per the table, so falls to PARTIALLY_OPEN even
        # with 3 of them.
        candidates = [
            _judged(relevant=True, relevance_type="direct", contradicts=False, confidence="medium", title=f"P{i}")
            for i in range(3)
        ]
        result = apply_decision_table(1.0, candidates)
        self.assertEqual(result["status"], "PARTIALLY_OPEN")


class RunChallengeOrchestrationTests(unittest.TestCase):
    @patch("pipeline.gap_challenger._search_arxiv_with_status")
    @patch("pipeline.gap_challenger._search_semantic_scholar_with_status")
    def test_low_confidence_gap_never_reaches_search(self, mock_ss, mock_arxiv):
        result = run_challenge(_gap(confidence="low"), MagicMock())
        self.assertEqual(result["challenger_state"], "GENERATED")
        self.assertIsNone(result["challenger_status"])
        mock_ss.assert_not_called()
        mock_arxiv.assert_not_called()

    @patch("pipeline.gap_challenger._search_arxiv_with_status")
    @patch("pipeline.gap_challenger._search_semantic_scholar_with_status")
    def test_full_pipeline_reaches_challenged_with_a_terminal_status(self, mock_ss, mock_arxiv):
        mock_ss.return_value = ([_candidate("Relevant Paper")], True)
        mock_arxiv.return_value = ([], True)
        client = MagicMock()
        client.chat_json.return_value = Success(
            '[{"title": "Relevant Paper", "relevant": true, "relevance_type": "adjacent", '
            '"contradicts_gap": false, "confidence": "medium"}]'
        )
        result = run_challenge(_gap(confidence="high"), client)
        self.assertEqual(result["challenger_state"], "CHALLENGED")
        self.assertEqual(result["challenger_status"], "PARTIALLY_OPEN")
        self.assertIn("challenge_funnel", result)
        self.assertIn("search_coverage_score", result["challenge_funnel"])
        self.assertIn("judged_candidates", result["challenge_funnel"])

    def test_gap_with_no_usable_query_text_stays_search_pending(self):
        gap = {"title": "", "description": "", "missing_connection": "", "confidence": "high"}
        result = run_challenge(gap, MagicMock())
        self.assertEqual(result["challenger_state"], "SEARCH_PENDING")
        self.assertIsNone(result["challenger_status"])


if __name__ == "__main__":
    unittest.main()
