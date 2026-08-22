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
    judge_candidates, apply_decision_table, run_challenge, _rerank_candidates,
    _filter_by_metadata, SEARCH_COVERAGE_THRESHOLD,
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
        # B27 fix: "Missing" is gap-framing, not literature vocabulary --
        # stripped before becoming a search query (see NegationFramingTests).
        self.assertIn("external validation", families[1])
        self.assertNotIn("Missing", families[1])

    def test_domain_boost_adds_a_third_family(self):
        domain_cfg = {"search_boost_terms": ["clinical validation", "healthcare"]}
        families = generate_query_families(_gap(), domain_config=domain_cfg)
        self.assertEqual(len(families), 3)

    def test_no_duplicate_families(self):
        gap = _gap(title="X", missing_connection="")
        families = generate_query_families(gap)
        self.assertEqual(len(families), len(set(families)))

    def test_negation_framing_words_are_stripped_from_the_query(self):
        # Real bug found live via evals/benchmarks/v2's ADHD-heritability
        # regression case: "...is unestablished" sent as-is to Semantic
        # Scholar (which doesn't go through arXiv's separate AND-join fix)
        # returned zero candidates for a genuinely well-established topic.
        gap = _gap(title="Genetic contribution to ADHD risk is unestablished",
                   missing_connection="heritability of ADHD")
        families = generate_query_families(gap)
        combined = " ".join(families).lower()
        self.assertNotIn("unestablished", combined)

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

    @patch("pipeline.gap_challenger._search_arxiv_with_status")
    @patch("pipeline.gap_challenger._search_semantic_scholar_with_status")
    def test_no_rerank_query_or_api_key_leaves_order_and_flag_false(self, mock_ss, mock_arxiv):
        mock_ss.return_value = ([_candidate("Paper A")], True)
        mock_arxiv.return_value = ([], True)
        funnel = run_search_funnel(["q1"])
        self.assertFalse(funnel["rerank_used"])
        self.assertEqual(funnel["post_rerank_count"], funnel["post_dedup_count"])

    @patch("pipeline.gap_challenger.rerank_candidates")
    @patch("pipeline.gap_challenger._search_arxiv_with_status")
    @patch("pipeline.gap_challenger._search_semantic_scholar_with_status")
    def test_rerank_reorders_candidates_when_enabled(self, mock_ss, mock_arxiv, mock_rerank):
        mock_ss.return_value = ([_candidate("Paper A"), _candidate("Paper B")], True)
        mock_arxiv.return_value = ([], True)
        # Reranker says Paper B (index 1) is more relevant than Paper A (index 0).
        mock_rerank.return_value = [{"index": 1, "score": 5.0}, {"index": 0, "score": 0.1}]
        funnel = run_search_funnel(["q1"], rerank_query="some gap", nvidia_api_key="key")
        self.assertTrue(funnel["rerank_used"])
        self.assertEqual([c["title"] for c in funnel["candidates"]], ["Paper B", "Paper A"])
        self.assertEqual(funnel["post_rerank_count"], 2)

    @patch("pipeline.gap_challenger.rerank_candidates")
    @patch("pipeline.gap_challenger._search_arxiv_with_status")
    @patch("pipeline.gap_challenger._search_semantic_scholar_with_status")
    def test_rerank_failure_falls_back_to_unranked_order(self, mock_ss, mock_arxiv, mock_rerank):
        mock_ss.return_value = ([_candidate("Paper A")], True)
        mock_arxiv.return_value = ([], True)
        mock_rerank.side_effect = Exception("NVIDIA API down")
        funnel = run_search_funnel(["q1"], rerank_query="some gap", nvidia_api_key="key")
        self.assertFalse(funnel["rerank_used"])
        self.assertEqual([c["title"] for c in funnel["candidates"]], ["Paper A"])

    @patch("pipeline.gap_challenger._search_arxiv_with_status")
    @patch("pipeline.gap_challenger._search_semantic_scholar_with_status")
    def test_metadata_filter_drops_implausible_year_candidates(self, mock_ss, mock_arxiv):
        from datetime import datetime
        future_year = datetime.now().year + 10
        mock_ss.return_value = ([_candidate("Good Paper", year=2022),
                                  _candidate("Bad Paper", year=future_year)], True)
        mock_arxiv.return_value = ([], True)
        funnel = run_search_funnel(["q1"])
        self.assertEqual(funnel["post_dedup_count"], 2)
        self.assertEqual(funnel["post_metadata_filter_count"], 1)
        self.assertEqual(funnel["metadata_filtered_count"], 1)
        self.assertEqual([c["title"] for c in funnel["candidates"]], ["Good Paper"])

    @patch("pipeline.gap_challenger._search_arxiv_with_status")
    @patch("pipeline.gap_challenger._search_semantic_scholar_with_status")
    def test_metadata_filter_year_bounds_are_opt_in(self, mock_ss, mock_arxiv):
        mock_ss.return_value = ([_candidate("Old Paper", year=1990)], True)
        mock_arxiv.return_value = ([], True)
        funnel = run_search_funnel(["q1"], year_from=2015)
        self.assertEqual(funnel["post_metadata_filter_count"], 0)
        funnel_no_bound = run_search_funnel(["q1"])
        self.assertEqual(funnel_no_bound["post_metadata_filter_count"], 1)


class FilterByMetadataTests(unittest.TestCase):
    def test_missing_year_is_kept_not_dropped(self):
        c = _candidate("No Year Paper", year=None)
        kept, dropped = _filter_by_metadata([c])
        self.assertEqual(kept, [c])
        self.assertEqual(dropped, 0)

    def test_future_year_is_dropped_as_implausible(self):
        from datetime import datetime
        future = datetime.now().year + 5
        c = _candidate("Time Traveler Paper", year=future)
        kept, dropped = _filter_by_metadata([c])
        self.assertEqual(kept, [])
        self.assertEqual(dropped, 1)

    def test_absurdly_old_year_is_dropped_as_implausible(self):
        c = _candidate("Bad Parse", year=42)
        kept, dropped = _filter_by_metadata([c])
        self.assertEqual(kept, [])
        self.assertEqual(dropped, 1)

    def test_normal_year_is_kept_by_default(self):
        c = _candidate("Normal Paper", year=2020)
        kept, dropped = _filter_by_metadata([c])
        self.assertEqual(kept, [c])
        self.assertEqual(dropped, 0)

    def test_year_from_excludes_older_candidates(self):
        old = _candidate("Old Paper", year=2010)
        new = _candidate("New Paper", year=2023)
        kept, dropped = _filter_by_metadata([old, new], year_from=2015)
        self.assertEqual(kept, [new])
        self.assertEqual(dropped, 1)

    def test_year_to_excludes_newer_candidates(self):
        old = _candidate("Old Paper", year=2010)
        new = _candidate("New Paper", year=2023)
        kept, dropped = _filter_by_metadata([old, new], year_to=2015)
        self.assertEqual(kept, [old])
        self.assertEqual(dropped, 1)

    def test_year_range_missing_year_still_kept(self):
        c = _candidate("No Year Paper", year=None)
        kept, dropped = _filter_by_metadata([c], year_from=2015, year_to=2020)
        self.assertEqual(kept, [c])
        self.assertEqual(dropped, 0)

    def test_no_bounds_no_op_on_normal_candidates(self):
        candidates = [_candidate("A", year=1990), _candidate("B", year=2024)]
        kept, dropped = _filter_by_metadata(candidates)
        self.assertEqual(kept, candidates)
        self.assertEqual(dropped, 0)


class RerankCandidatesHelperTests(unittest.TestCase):
    def test_no_api_key_skips_reranking(self):
        candidates = [_candidate("A")]
        result, used = _rerank_candidates("query", candidates, api_key="")
        self.assertEqual(result, candidates)
        self.assertFalse(used)

    def test_no_query_skips_reranking(self):
        candidates = [_candidate("A")]
        result, used = _rerank_candidates("", candidates, api_key="key")
        self.assertEqual(result, candidates)
        self.assertFalse(used)

    def test_empty_candidates_skips_reranking(self):
        result, used = _rerank_candidates("query", [], api_key="key")
        self.assertEqual(result, [])
        self.assertFalse(used)

    @patch("pipeline.gap_challenger.rerank_candidates")
    def test_rankings_covering_only_some_candidates_appends_the_rest(self, mock_rerank):
        candidates = [_candidate("A"), _candidate("B"), _candidate("C")]
        mock_rerank.return_value = [{"index": 2, "score": 1.0}]  # only "C" ranked
        result, used = _rerank_candidates("query", candidates, api_key="key")
        self.assertTrue(used)
        self.assertEqual([c["title"] for c in result], ["C", "A", "B"])


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
        # A bare MagicMock().api_key auto-creates a truthy attribute, which
        # would make _rerank_candidates() attempt a real HTTP call to
        # NVIDIA's reranker instead of skipping it -- explicit empty string
        # keeps this test's "mocked, no live service" guarantee.
        client.api_key = ""
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
