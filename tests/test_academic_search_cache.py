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
        with patch("pipeline.academic_search._search_semantic_scholar", return_value=[_paper()]) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv", return_value=[]) as mock_arxiv, \
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

    def test_no_papers_found_is_cached(self):
        client = MagicMock()
        with patch("pipeline.academic_search._search_semantic_scholar", return_value=[]) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv", return_value=[]) as mock_arxiv, \
             patch("pipeline.academic_search.time.sleep"):
            validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 1)

            validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 1)  # cache hit, no second search
            self.assertEqual(mock_arxiv.call_count, 1)

    def test_fallback_result_is_never_cached(self):
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="rate_limit", detail="429"))
        with patch("pipeline.academic_search._search_semantic_scholar", return_value=[_paper()]) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv", return_value=[]), \
             patch("pipeline.academic_search.time.sleep"):
            validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 1)

            validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 2)  # retried -- fallback was never cached

    def test_different_domain_config_is_a_cache_miss(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "solved", "reasoning": "covered"}))
        with patch("pipeline.academic_search._search_semantic_scholar", return_value=[_paper()]) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv", return_value=[]), \
             patch("pipeline.academic_search.time.sleep"):
            validate_gaps([self._gap()], client, domain_config={"search_boost_terms": ["genomics"]})
            self.assertEqual(mock_ss.call_count, 1)

            validate_gaps([self._gap()], client, domain_config={"search_boost_terms": ["oncology"]})
            self.assertEqual(mock_ss.call_count, 2)  # different domain -> real miss

    def test_unrelated_domain_key_does_not_cause_a_cache_miss(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "solved", "reasoning": "covered"}))
        with patch("pipeline.academic_search._search_semantic_scholar", return_value=[_paper()]) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv", return_value=[]), \
             patch("pipeline.academic_search.time.sleep"):
            validate_gaps([self._gap()], client, domain_config={"search_boost_terms": ["genomics"], "wiki_focus": "a"})
            self.assertEqual(mock_ss.call_count, 1)

            validate_gaps([self._gap()], client, domain_config={"search_boost_terms": ["genomics"], "wiki_focus": "b"})
            self.assertEqual(mock_ss.call_count, 1)  # unrelated key changed -> still a hit

    def test_stage_version_bump_bypasses_and_repopulates(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "solved", "reasoning": "covered"}))
        with patch("pipeline.academic_search._search_semantic_scholar", return_value=[_paper()]) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv", return_value=[]), \
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
        with patch("pipeline.academic_search._search_semantic_scholar", return_value=[_paper()]), \
             patch("pipeline.academic_search._search_arxiv", return_value=[]), \
             patch("pipeline.academic_search.time.sleep") as mock_sleep:
            validate_gaps([self._gap()], client, domain_config=None)
            self.assertGreater(mock_sleep.call_count, 0)  # real work sleeps (0.5 between searches, 0.3 at loop end)

            mock_sleep.reset_mock()
            validate_gaps([self._gap()], client, domain_config=None)
            self.assertEqual(mock_sleep.call_count, 0)  # cache hit skips both sleeps entirely

    def test_empty_content_gap_is_never_cached(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"status": "solved", "reasoning": "covered"}))
        with patch("pipeline.academic_search._search_semantic_scholar", return_value=[_paper()]) as mock_ss, \
             patch("pipeline.academic_search._search_arxiv", return_value=[]), \
             patch("pipeline.academic_search.time.sleep"):
            empty_gap = {"title": "", "description": ""}
            validate_gaps([dict(empty_gap)], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 1)

            validate_gaps([dict(empty_gap)], client, domain_config=None)
            self.assertEqual(mock_ss.call_count, 2)  # never cached, always retried


if __name__ == "__main__":
    unittest.main()
