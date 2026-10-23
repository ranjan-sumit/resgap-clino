"""
Tests for pipeline/gap_challenger.py (Clinova Phase 3, Epic 3.4 -- the
Gap Challenger state machine). Per 10-phased-implementation-plan.md's
Phase 3 testing strategy: "every cell of the decision table exercised."
"""
import sys
import unittest
import json
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
    """The funnel searches through the literature check's providers (Europe PMC, Semantic Scholar, arXiv for ML)."""

    def _funnel(self, papers, flags, queries=("query one",), **kw):
        with patch("pipeline.gap_challenger.scout._search_gap", return_value=(papers, flags)):
            return run_search_funnel(list(queries), **kw)

    def test_both_providers_succeed_gives_full_coverage(self):
        f = self._funnel([_candidate("Paper A about airways"), _candidate("Paper B about mucus")],
                         {"semantic_scholar": [True], "europe_pmc": [True]})
        self.assertEqual(f["search_coverage_score"], 1.0)
        self.assertEqual(f["post_dedup_count"], 2)
        self.assertEqual(f["providers_queried"], ["semantic_scholar", "europe_pmc"])

    def test_one_provider_failing_halves_coverage(self):
        f = self._funnel([_candidate("Paper A about airways")], {"semantic_scholar": [False], "europe_pmc": [True]})
        self.assertEqual(f["search_coverage_score"], 0.5)
        self.assertEqual(f["provider_success"], {"semantic_scholar": False, "europe_pmc": True})

    def test_all_providers_failing_gives_zero_coverage(self):
        f = self._funnel([], {"semantic_scholar": [False], "europe_pmc": [False]})
        self.assertEqual(f["search_coverage_score"], 0.0)

    def test_a_provider_succeeding_on_any_query_counts(self):
        f = self._funnel([], {"semantic_scholar": [True, False], "europe_pmc": [False, False]}, queries=("q1", "q2"))
        self.assertTrue(f["provider_success"]["semantic_scholar"])
        self.assertFalse(f["provider_success"]["europe_pmc"])
        self.assertEqual(f["search_coverage_score"], 0.25)          # 1 of 2 families answered x 1 of 2 providers

    def test_a_family_where_every_provider_call_failed_is_not_executed(self):
        f = self._funnel([], {"semantic_scholar": [False, True], "europe_pmc": [False, True]}, queries=("q1", "q2"))
        self.assertEqual(f["search_coverage_score"], 0.5)           # 0.5 x 1.0

    def test_arxiv_counts_as_a_provider_only_when_it_was_used(self):
        f = self._funnel([], {"semantic_scholar": [True], "europe_pmc": [True], "arxiv": [False]}, use_arxiv=True)
        self.assertEqual(f["providers_queried"], ["semantic_scholar", "europe_pmc", "arxiv"])
        self.assertAlmostEqual(f["search_coverage_score"], 0.667, places=3)

    def test_duplicates_are_merged_by_doi_or_title(self):
        a = dict(_candidate("Same Paper About Airways"), doi="10.1/x")
        b = dict(_candidate("same paper about airways"), doi="https://doi.org/10.1/x")
        f = self._funnel([a, b, _candidate("Other Paper About Mucus")], {"semantic_scholar": [True], "europe_pmc": [True]})
        self.assertEqual(f["candidate_count"], 3)
        self.assertEqual(f["post_dedup_count"], 2)

    def test_records_whose_title_is_a_section_name_are_discarded(self):
        f = self._funnel([_candidate("Papers"), _candidate("Abstract"), _candidate("Short"),
                          _candidate("A real paper title about cystic fibrosis")],
                         {"semantic_scholar": [True], "europe_pmc": [True]})
        self.assertEqual([c["title"] for c in f["candidates"]], ["A real paper title about cystic fibrosis"])

    def test_without_a_rerank_query_the_order_is_kept_and_the_flag_is_false(self):
        f = self._funnel([_candidate("Paper A about airways")], {"semantic_scholar": [True], "europe_pmc": [True]})
        self.assertFalse(f["rerank_used"])
        self.assertEqual(f["post_rerank_count"], f["post_dedup_count"])

    def test_the_candidates_are_ranked_against_the_gap_without_any_network_call(self):
        papers = [_candidate("Stock price forecasting with neural networks", abstract="daily prices"),
                  _candidate("CFTR modulators in a human airway chip", abstract="modulator rescue of ion transport")]
        with patch("socket.socket", side_effect=AssertionError("network used by the ranker")):
            f = self._funnel(papers, {"semantic_scholar": [True], "europe_pmc": [True]},
                             rerank_query="CFTR modulator rescue in an airway chip")
        self.assertTrue(f["rerank_used"])
        self.assertEqual(f["ranker"], "token-overlap-v1")
        self.assertEqual(f["candidates"][0]["title"], "CFTR modulators in a human airway chip")

    def test_metadata_filter_drops_implausible_year_candidates(self):
        from datetime import datetime
        f = self._funnel([_candidate("Good Paper about airways", year=2022),
                          _candidate("Bad Paper about airways", year=datetime.now().year + 10)],
                         {"semantic_scholar": [True], "europe_pmc": [True]})
        self.assertEqual(f["post_dedup_count"], 2)
        self.assertEqual(f["post_metadata_filter_count"], 1)
        self.assertEqual([c["title"] for c in f["candidates"]], ["Good Paper about airways"])

    def test_metadata_filter_year_bounds_are_opt_in(self):
        flags = {"semantic_scholar": [True], "europe_pmc": [True]}
        self.assertEqual(self._funnel([_candidate("Old Paper about airways", year=1990)], flags, year_from=2015)["post_metadata_filter_count"], 0)
        self.assertEqual(self._funnel([_candidate("Old Paper about airways", year=1990)], flags)["post_metadata_filter_count"], 1)


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
    def test_no_query_skips_reranking(self):
        candidates = [_candidate("A")]
        result, used = _rerank_candidates("", candidates)
        self.assertEqual(result, candidates)
        self.assertFalse(used)

    def test_empty_candidates_skips_reranking(self):
        result, used = _rerank_candidates("query", [])
        self.assertEqual(result, [])
        self.assertFalse(used)

    def test_candidates_are_returned_best_first_and_none_are_lost(self):
        candidates = [_candidate("Unrelated finance paper", abstract="stocks"),
                      _candidate("Airway chip CFTR modulator", abstract="airway chip"),
                      _candidate("Another unrelated paper", abstract="weather")]
        result, used = _rerank_candidates("airway chip CFTR modulator", candidates)
        self.assertTrue(used)
        self.assertEqual(result[0]["title"], "Airway chip CFTR modulator")
        self.assertEqual(sorted(c["title"] for c in result), sorted(c["title"] for c in candidates))


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


class JudgeParsingHardeningTests(unittest.TestCase):
    """Regression tests for judge-output parsing: strict booleans (a JSON
    string "false" is truthy in Python), case normalization, and matching
    judgments to candidates by title rather than list position."""

    def test_string_false_does_not_count_as_relevant(self):
        client = MagicMock()
        client.chat_json.return_value = Success(
            '[{"title": "A", "relevant": "false", "contradicts_gap": "false", "confidence": "high"}]'
        )
        judged = judge_candidates(_gap(), [_candidate("A")], client)
        self.assertFalse(judged[0]["relevant"])
        self.assertFalse(judged[0]["contradicts_gap"])
        self.assertTrue(judged[0]["judged"])  # judgment WAS found and applied

    def test_string_true_counts_as_relevant(self):
        client = MagicMock()
        client.chat_json.return_value = Success(
            '[{"title": "A", "relevant": "true", "relevance_type": "direct", '
            '"contradicts_gap": "false", "confidence": "high"}]'
        )
        judged = judge_candidates(_gap(), [_candidate("A")], client)
        self.assertTrue(judged[0]["relevant"])

    def test_capitalized_values_are_normalized(self):
        client = MagicMock()
        client.chat_json.return_value = Success(
            '[{"title": "A", "relevant": true, "relevance_type": "Direct", '
            '"contradicts_gap": false, "confidence": "High"}]'
        )
        judged = judge_candidates(_gap(), [_candidate("A")], client)
        self.assertTrue(judged[0]["relevant"])
        self.assertEqual(judged[0]["relevance_type"], "direct")
        self.assertEqual(judged[0]["confidence"], "high")

    def test_judgments_are_matched_by_title_not_position(self):
        # The judge reversed the order -- position-based alignment would
        # attribute each judgment to the wrong candidate.
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps([
            {"title": "B", "relevant": True, "relevance_type": "direct",
             "contradicts_gap": False, "confidence": "high"},
            {"title": "A", "relevant": False, "contradicts_gap": False, "confidence": "low"},
        ]))
        judged = judge_candidates(_gap(), [_candidate("A"), _candidate("B")], client)
        by_title = {j["title"]: j for j in judged}
        self.assertFalse(by_title["A"]["relevant"])
        self.assertTrue(by_title["B"]["relevant"])
        self.assertEqual(by_title["B"]["relevance_type"], "direct")

    def test_candidate_with_no_matching_judgment_is_unjudged(self):
        client = MagicMock()
        client.chat_json.return_value = Success(
            '[{"title": "A", "relevant": true, "relevance_type": "direct", '
            '"contradicts_gap": false, "confidence": "high"}]'
        )
        judged = judge_candidates(_gap(), [_candidate("A"), _candidate("B")], client)
        by_title = {j["title"]: j for j in judged}
        self.assertTrue(by_title["A"]["judged"])
        self.assertFalse(by_title["B"]["judged"])
        self.assertFalse(by_title["B"]["relevant"])

    def test_llm_call_failure_marks_everything_unjudged(self):
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="api_error", detail="down"))
        judged = judge_candidates(_gap(), [_candidate("A")], client)
        self.assertFalse(judged[0]["relevant"])
        self.assertFalse(judged[0]["judged"])

    def test_malformed_json_marks_everything_unjudged(self):
        client = MagicMock()
        client.chat_json.return_value = Success("not json at all")
        judged = judge_candidates(_gap(), [_candidate("A")], client)
        self.assertFalse(judged[0]["relevant"])
        self.assertFalse(judged[0]["judged"])


def _judged(relevant=True, relevance_type="direct", contradicts=False, confidence="high", title="P"):
    return {"title": title, "relevant": relevant, "relevance_type": relevance_type,
            "contradicts_gap": contradicts, "confidence": confidence}


class DecisionTableTests(unittest.TestCase):
    """Every row of 04-ai-research-architecture.md §5.2's decision table."""

    def test_row1_low_coverage_never_concludes_that_a_gap_is_open(self):
        # an incomplete search cannot show that nobody has done the work
        for judged in ([], [_judged(relevant=False)], [_judged(relevance_type="adjacent")]):
            result = apply_decision_table(SEARCH_COVERAGE_THRESHOLD - 0.01, judged)
            self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")

    def test_row1_low_coverage_still_reports_closure_when_papers_directly_do_the_work(self):
        # papers that do the work are evidence however many sources answered; never CLOSED on an incomplete search
        result = apply_decision_table(0.5, [_judged() for _ in range(5)])
        self.assertEqual(result["status"], "LIKELY_CLOSED")
        self.assertEqual(apply_decision_table(0.5, [_judged()])["status"], "INSUFFICIENT_EVIDENCE")

    def test_row1_low_coverage_with_a_contradiction_is_not_reported_as_closed(self):
        judged = [_judged(), _judged(), _judged(contradicts=True)]
        self.assertEqual(apply_decision_table(0.5, judged)["status"], "INSUFFICIENT_EVIDENCE")

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


_NO_PLANNER = patch("pipeline.gap_challenger.scout.plan_queries", return_value=({}, "planner off"))


def _funnel_result(**over):
    base = {"query_families": ["q"], "providers_queried": ["semantic_scholar", "europe_pmc"],
            "provider_success": {"semantic_scholar": True, "europe_pmc": True},
            "candidate_count": 0, "post_dedup_count": 0, "post_metadata_filter_count": 0,
            "metadata_filtered_count": 0, "post_rerank_count": 0, "rerank_used": False, "ranker": "token-overlap-v1",
            "candidates": [], "search_coverage_score": 1.0}
    base.update(over)
    return base


def _search(papers, flags=None):
    return patch("pipeline.gap_challenger.scout._search_gap",
                 return_value=(papers, flags or {"semantic_scholar": [True] * 3, "europe_pmc": [True] * 3}))


class RunChallengeOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.planner = _NO_PLANNER.start()
        self.addCleanup(_NO_PLANNER.stop)

    def test_low_confidence_gap_never_reaches_search(self):
        with patch("pipeline.gap_challenger.scout._search_gap") as search:
            result = run_challenge(_gap(confidence="low"), MagicMock())
        self.assertEqual(result["challenger_state"], "GENERATED")
        self.assertIsNone(result["challenger_status"])
        search.assert_not_called()

    def test_full_pipeline_reaches_challenged_with_a_terminal_status(self):
        client = MagicMock()
        client.chat_json.return_value = Success(
            '[{"title": "Relevant Paper about validation", "relevant": true, "relevance_type": "adjacent", '
            '"contradicts_gap": false, "confidence": "medium"}]'
        )
        with _search([_candidate("Relevant Paper about validation")]):
            result = run_challenge(_gap(confidence="high"), client)
        self.assertEqual(result["challenger_state"], "CHALLENGED")
        self.assertEqual(result["challenger_status"], "PARTIALLY_OPEN")
        self.assertIn("challenge_funnel", result)
        self.assertIn("search_coverage_score", result["challenge_funnel"])
        self.assertIn("judged_candidates", result["challenge_funnel"])
        self.assertEqual(result["challenge_funnel"]["ranker"], "token-overlap-v1")

    def test_gap_with_no_usable_query_text_stays_search_pending(self):
        gap = {"title": "", "description": "", "missing_connection": "", "confidence": "high"}
        result = run_challenge(gap, MagicMock())
        self.assertEqual(result["challenger_state"], "SEARCH_PENDING")
        self.assertIsNone(result["challenger_status"])

    def test_judge_failure_resolves_to_insufficient_evidence_not_open(self):
        # ADR-008: an unjudged candidate pool must never run the decision
        # table -- "the judge call failed" is not "searched, nothing found."
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="api_error", detail="down"))
        with _search([_candidate("Paper A about validation")]):
            result = run_challenge(_gap(confidence="high"), client)
        self.assertEqual(result["challenger_state"], "CHALLENGED")
        self.assertEqual(result["challenger_status"], "INSUFFICIENT_EVIDENCE")
        self.assertFalse(result["challenge_funnel"]["judged"])
        self.assertIn("challenger_reason", result)

    def test_partial_judgment_coverage_resolves_to_insufficient_evidence(self):
        client = MagicMock()
        client.chat_json.return_value = Success(
            '[{"title": "Paper A about validation", "relevant": true, "relevance_type": "direct", '
            '"contradicts_gap": false, "confidence": "high"}]'
        )
        with _search([_candidate("Paper A about validation"), _candidate("Paper B about validation")]):
            result = run_challenge(_gap(confidence="high"), client)
        self.assertEqual(result["challenger_status"], "INSUFFICIENT_EVIDENCE")

    def test_the_rerank_query_is_stripped_of_gap_framing(self):
        with patch("pipeline.gap_challenger.run_search_funnel", return_value=_funnel_result()) as funnel:
            run_challenge(_gap(confidence="high"), MagicMock())
        self.assertNotIn("Missing", funnel.call_args.kwargs["rerank_query"])
        self.assertIn("external validation", funnel.call_args.kwargs["rerank_query"])

    def test_no_third_party_key_is_read_or_sent(self):
        # the old reranker took NVIDIA_API_KEY from the environment and sent gap and abstract text to NVIDIA
        with patch.dict("os.environ", {"NVIDIA_API_KEY": "env-key"}), \
             patch("pipeline.gap_challenger.run_search_funnel", return_value=_funnel_result()) as funnel:
            run_challenge(_gap(confidence="high"), MagicMock())
        self.assertNotIn("nvidia_api_key", funnel.call_args.kwargs)
        import inspect
        self.assertNotIn("nvidia", inspect.signature(run_challenge).parameters)

    def test_arxiv_is_searched_only_when_asked_to(self):
        with patch("pipeline.gap_challenger.run_search_funnel", return_value=_funnel_result()) as funnel:
            run_challenge(_gap(confidence="high"), MagicMock(), use_arxiv=True)
            self.assertTrue(funnel.call_args.kwargs["use_arxiv"])
            run_challenge(_gap(confidence="high"), MagicMock())
            self.assertFalse(funnel.call_args.kwargs["use_arxiv"])


class PlannedQueryTests(unittest.TestCase):
    def test_the_planners_short_queries_are_what_gets_searched(self):
        gap = dict(_gap(confidence="high"), gap_id="g1")
        with patch("pipeline.gap_challenger.scout.plan_queries", return_value=({"g1": ["airway chip CFTR", "modulator rescue chip"]}, None)), \
             patch("pipeline.gap_challenger.run_search_funnel", return_value=_funnel_result()) as funnel:
            result = run_challenge(gap, MagicMock())
        self.assertEqual(funnel.call_args.args[0], ["airway chip CFTR", "modulator rescue chip"])
        self.assertIsNone(result["challenge_funnel"]["planner_error"])

    def test_when_the_planner_fails_the_deterministic_queries_are_used_and_the_reason_is_recorded(self):
        gap = dict(_gap(confidence="high"), gap_id="g1")
        with patch("pipeline.gap_challenger.scout.plan_queries", return_value=({}, "query planner failed: timeout")), \
             patch("pipeline.gap_challenger.run_search_funnel", return_value=_funnel_result()) as funnel:
            result = run_challenge(gap, MagicMock())
        self.assertEqual(funnel.call_args.args[0], generate_query_families(gap))
        self.assertEqual(result["challenge_funnel"]["planner_error"], "query planner failed: timeout")

    def test_a_planner_exception_does_not_stop_the_challenge(self):
        gap = dict(_gap(confidence="high"), gap_id="g1")
        with patch("pipeline.gap_challenger.scout.plan_queries", side_effect=RuntimeError("boom")), \
             patch("pipeline.gap_challenger.run_search_funnel", return_value=_funnel_result()):
            result = run_challenge(gap, MagicMock())
        self.assertEqual(result["challenger_state"], "CHALLENGED")


if __name__ == "__main__":
    unittest.main()
