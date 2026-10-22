"""
Tests for Story 2.4: _assess_coverage returns (result, cacheable) so callers
can distinguish a genuine, confident result from a degraded heuristic
fallback -- and validate_gaps checks the gap_validations cache (keyed on
gap title+description + domain-scoped search_boost_terms) before either
the academic-search calls or the LLM assessment call.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from utils.azure_client import Success, Failure, ErrorInfo
from pipeline import academic_search
from pipeline.academic_search import _assess_coverage, validate_gaps
from tests.pg_test_utils import new_test_schema, drop_test_schema


def _paper(title="A Paper", year=2020):
    return {"title": title, "year": year, "abstract": "", "citations": 0, "authors": [], "source": "test"}


class AssessCoverageCacheableSignalTests(unittest.TestCase):
    def test_no_papers_found_is_cacheable(self):
        result, cacheable = _assess_coverage({"title": "Gap"}, [], MagicMock())
        self.assertEqual(result["status"], "open")
        self.assertTrue(cacheable)

    def test_clean_llm_success_is_cacheable(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "solved", "reasoning": "well covered"}))
        result, cacheable = _assess_coverage({"title": "Gap"}, [_paper()], client)
        self.assertEqual(result["status"], "solved")
        self.assertTrue(cacheable)

    def test_llm_call_error_is_not_cacheable(self):
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="rate_limit", detail="429"))
        result, cacheable = _assess_coverage({"title": "Gap"}, [_paper()], client)
        self.assertIn(result["status"], ("open", "partial"))
        self.assertFalse(cacheable)

    def test_no_json_match_is_not_cacheable(self):
        client = MagicMock()
        client.chat_json.return_value = Success("I cannot determine this.")
        result, cacheable = _assess_coverage({"title": "Gap"}, [_paper()], client)
        self.assertIn(result["status"], ("open", "partial"))
        self.assertFalse(cacheable)

    def test_malformed_json_is_not_cacheable(self):
        client = MagicMock()
        client.chat_json.return_value = Success("{status: solved, not valid json}")
        result, cacheable = _assess_coverage({"title": "Gap"}, [_paper()], client)
        self.assertIn(result["status"], ("open", "partial"))
        self.assertFalse(cacheable)

    def test_off_schema_json_is_not_cacheable(self):
        # A syntactically valid but off-schema response (no recognized
        # status) must not be treated as a genuine result (review finding).
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"foo": "bar"}))
        result, cacheable = _assess_coverage({"title": "Gap"}, [_paper()], client)
        self.assertIn(result["status"], ("open", "partial"))
        self.assertFalse(cacheable)


class RecentPaperHeuristicTests(unittest.TestCase):
    """The degraded fallback's 'recent paper' check must stay relative to
    the current year -- a hardcoded cutoff silently rots as the calendar
    advances -- and must not blow up on missing/non-numeric years."""

    def _fallback(self, papers):
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="api_error", detail="down"))
        return _assess_coverage({"title": "Gap"}, papers, client)

    def test_papers_from_cutoff_year_count_as_recent(self):
        from datetime import datetime
        year = datetime.now().year - 4
        result, _ = self._fallback([_paper(year=year), _paper(year=year)])
        self.assertEqual(result["status"], "partial")

    def test_papers_older_than_cutoff_do_not_count_as_recent(self):
        from datetime import datetime
        year = datetime.now().year - 5
        result, _ = self._fallback([_paper(year=year), _paper(year=year)])
        self.assertEqual(result["status"], "open")

    def test_missing_and_non_numeric_years_are_skipped_not_fatal(self):
        from datetime import datetime
        year = datetime.now().year - 5
        papers = [
            _paper(year=None),
            _paper(year="unknown"),
            _paper(year=year),
            _paper(year=year),
        ]
        result, _ = self._fallback(papers)
        self.assertEqual(result["status"], "open")


class ValidateGapsCacheTests(unittest.TestCase):
    def setUp(self):
        self.schema = new_test_schema()
        self.patcher = patch.object(db, "_SCHEMA", self.schema)
        self.patcher.start()
        db.init_db()

    def tearDown(self):
        self.patcher.stop()
        drop_test_schema(self.schema)

    def _gap(self, title="Original Gap Title", description="A description of the gap."):
        return {"title": title, "description": description}

    def test_cache_miss_then_hit_skips_search_and_llm(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "solved", "reasoning": "covered"}))
        with patch("pipeline.academic_search._search_semantic_scholar_with_status", return_value=([_paper()], True)) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv_with_status", return_value=([], True)) as mock_arxiv, \
             patch("pipeline.academic_search.time.sleep"):
            gaps = [self._gap()]
            first = validate_gaps(gaps, client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 1)
            self.assertEqual(mock_arxiv.call_count, 1)
            self.assertEqual(client.chat_json.call_count, 1)
            self.assertEqual(first[0]["validation_status"], "solved")

            second = validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 1)      # not called again
            self.assertEqual(mock_arxiv.call_count, 1)    # not called again
            self.assertEqual(client.chat_json.call_count, 1)  # not called again
            self.assertEqual(second[0]["validation_status"], first[0]["validation_status"])
            self.assertEqual(second[0]["validation_reasoning"], first[0]["validation_reasoning"])
            self.assertEqual(second[0]["existing_papers"], first[0]["existing_papers"])
            self.assertEqual(second[0]["search_query_used"], first[0]["search_query_used"])

    def test_progress_callback_reports_each_gap_before_it_is_checked(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "open", "reasoning": "none found"}))
        seen = []
        with patch("pipeline.academic_search._search_semantic_scholar_with_status", return_value=([], True)), \
             patch("pipeline.academic_search._search_arxiv_with_status", return_value=([], True)), \
             patch("pipeline.academic_search.time.sleep"):
            out = validate_gaps([self._gap("A"), self._gap("B"), self._gap("C")], client, domain_config=None,
                                progress_callback=lambda done, total: seen.append((done, total)))
        self.assertEqual(seen, [(0, 3), (1, 3), (2, 3)])
        self.assertEqual(len(out), 3)

    def test_a_failing_progress_callback_does_not_stop_validation(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "open", "reasoning": "x"}))

        def boom(done, total):
            raise RuntimeError("display broke")
        with patch("pipeline.academic_search._search_semantic_scholar_with_status", return_value=([], True)), \
             patch("pipeline.academic_search._search_arxiv_with_status", return_value=([], True)), \
             patch("pipeline.academic_search.time.sleep"):
            out = validate_gaps([self._gap("A"), self._gap("B")], client, domain_config=None, progress_callback=boom)
        self.assertEqual(len(out), 2)

    def test_no_papers_found_is_cached(self):
        client = MagicMock()
        with patch("pipeline.academic_search._search_semantic_scholar_with_status", return_value=([], True)) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv_with_status", return_value=([], True)) as mock_arxiv, \
             patch("pipeline.academic_search.time.sleep"):
            validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 1)

            validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 1)  # cache hit, no second search
            self.assertEqual(mock_arxiv.call_count, 1)

    def test_fallback_result_is_never_cached(self):
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="rate_limit", detail="429"))
        with patch("pipeline.academic_search._search_semantic_scholar_with_status", return_value=([_paper()], True)) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv_with_status", return_value=([], True)), \
             patch("pipeline.academic_search.time.sleep"):
            validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 1)

            validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 2)  # retried -- fallback was never cached

    def test_different_domain_config_is_a_cache_miss(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "solved", "reasoning": "covered"}))
        with patch("pipeline.academic_search._search_semantic_scholar_with_status", return_value=([_paper()], True)) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv_with_status", return_value=([], True)), \
             patch("pipeline.academic_search.time.sleep"):
            validate_gaps([self._gap()], client, domain_config={"search_boost_terms": ["genomics"]})
            self.assertEqual(mock_ss.call_count, 1)

            validate_gaps([self._gap()], client, domain_config={"search_boost_terms": ["oncology"]})
            self.assertEqual(mock_ss.call_count, 2)  # different domain -> real miss

    def test_unrelated_domain_key_does_not_cause_a_cache_miss(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "solved", "reasoning": "covered"}))
        with patch("pipeline.academic_search._search_semantic_scholar_with_status", return_value=([_paper()], True)) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv_with_status", return_value=([], True)), \
             patch("pipeline.academic_search.time.sleep"):
            validate_gaps([self._gap()], client, domain_config={"search_boost_terms": ["genomics"], "wiki_focus": "a"})
            self.assertEqual(mock_ss.call_count, 1)

            validate_gaps([self._gap()], client, domain_config={"search_boost_terms": ["genomics"], "wiki_focus": "b"})
            self.assertEqual(mock_ss.call_count, 1)  # unrelated key changed -> still a hit

    def test_stage_version_bump_bypasses_and_repopulates(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "solved", "reasoning": "covered"}))
        with patch("pipeline.academic_search._search_semantic_scholar_with_status", return_value=([_paper()], True)) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv_with_status", return_value=([], True)), \
             patch("pipeline.academic_search.time.sleep"):
            validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 1)

            bumped_version = academic_search.GAP_VALIDATION_STAGE_VERSION + 1
            with patch.object(academic_search, "GAP_VALIDATION_STAGE_VERSION", bumped_version):
                validate_gaps([self._gap()], client, domain_config=None)
                self.assertEqual(mock_ss.call_count, 2)  # version bump -> real miss

                validate_gaps([self._gap()], client, domain_config=None)
                self.assertEqual(mock_ss.call_count, 2)  # bumped-version entry is now a hit

    def test_cache_hit_does_not_sleep(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "solved", "reasoning": "covered"}))
        with patch("pipeline.academic_search._search_semantic_scholar_with_status", return_value=([_paper()], True)), \
             patch("pipeline.academic_search._search_arxiv_with_status", return_value=([], True)), \
             patch("pipeline.academic_search.time.sleep") as mock_sleep:
            validate_gaps([self._gap()], client, domain_config=None)
            self.assertGreater(mock_sleep.call_count, 0)  # real work sleeps (0.5 between searches, 0.3 at loop end)

            mock_sleep.reset_mock()
            validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_sleep.call_count, 0)  # cache hit skips both sleeps entirely

    def test_empty_content_gap_is_never_cached(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "solved", "reasoning": "covered"}))
        with patch("pipeline.academic_search._search_semantic_scholar_with_status", return_value=([_paper()], True)) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv_with_status", return_value=([], True)), \
             patch("pipeline.academic_search.time.sleep"):
            empty_gap = {"title": "", "description": ""}
            validate_gaps([dict(empty_gap)], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 1)

            validate_gaps([dict(empty_gap)], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 2)  # never cached, always retried

    def test_both_providers_failing_is_never_cached(self):
        # A transient outage (both providers raising) is indistinguishable
        # from "no papers exist" at the results level -- the old code cached
        # the degraded {"status": "open"} guess forever. The outage result
        # must never enter the gap_validations cache: a second call must
        # re-run the searches.
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "solved", "reasoning": "covered"}))
        with patch("pipeline.academic_search._search_semantic_scholar_with_status", return_value=([], False)) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv_with_status", return_value=([], False)) as mock_arxiv, \
             patch("pipeline.academic_search.time.sleep"):
            first = validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 1)
            self.assertEqual(mock_arxiv.call_count, 1)
            self.assertEqual(first[0]["validation_status"], "open")  # degraded guess, honestly returned

            second = validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 2)  # not cached -- searches re-run
            self.assertEqual(mock_arxiv.call_count, 2)
            self.assertEqual(second[0]["validation_status"], "open")

    def test_one_provider_failing_still_caches(self):
        # Partial coverage is a real search: SS responded (even with zero
        # papers), so the assessment is genuine and cacheable.
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "solved", "reasoning": "covered"}))
        with patch("pipeline.academic_search._search_semantic_scholar_with_status", return_value=([], True)) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv_with_status", return_value=([], False)), \
             patch("pipeline.academic_search.time.sleep"):
            validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 1)

            validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 1)  # cache hit, no second search


if __name__ == "__main__":
    unittest.main()
