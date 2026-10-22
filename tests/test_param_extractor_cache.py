"""
Tests for Story 2.2: extract_parameters checks the parameters cache (keyed on
the wiki-derived `context` string, not paper full_text) before calling the
LLM, and only writes back on a genuine Success -- never on LLMCallError.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from utils.azure_client import Success, Failure, ErrorInfo
from pipeline import param_extractor
from pipeline.param_extractor import extract_parameters
from tests.pg_test_utils import new_test_schema, drop_test_schema


def _page(title="Paper One", key_findings=("finding a",)):
    return {
        "title": title, "source_file": f"{title}.pdf",
        "key_findings": list(key_findings), "limitations": [], "methods": [],
        "datasets": [], "contributions": [],
    }


def _paper(filename="paper.pdf"):
    return {"filename": filename, "sections": {}, "tables": []}


class ExtractParametersCacheTests(unittest.TestCase):
    def setUp(self):
        self.schema = new_test_schema()
        self.patcher = patch.object(db, "_SCHEMA", self.schema)
        self.patcher.start()
        db.init_db()

    def tearDown(self):
        self.patcher.stop()
        drop_test_schema(self.schema)

    def test_cache_miss_then_hit_skips_second_llm_call(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps(
            [{"name": "prevalence", "value": 10, "category": "prevalence", "source_paper": "Paper One"}]
        ))
        wiki = {"pages": [_page()]}
        papers = [_paper()]

        first = extract_parameters(wiki, papers, client)
        self.assertEqual(client.chat_json.call_count, 1)
        self.assertEqual(len(first), 1)

        second = extract_parameters(wiki, papers, client)
        self.assertEqual(client.chat_json.call_count, 1)  # not called again
        self.assertEqual(len(second), 1)

    def test_paper_index_is_freshly_applied_on_a_cache_hit(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps(
            [{"name": "prevalence", "value": 10, "category": "prevalence"}]
        ))
        page, paper = _page(), _paper()

        # First call: this paper is alone, so paper_index == 0.
        first = extract_parameters({"pages": [page]}, [paper], client)
        self.assertEqual(first[0]["paper_index"], 0)

        # Second call: same paper/context, but now preceded by another paper
        # in the list -- a real cache hit must still report the CURRENT index (1).
        other_page, other_paper = _page(title="Other Paper", key_findings=("different",)), _paper(filename="other.pdf")
        client.chat_json.return_value = Success(json.dumps(
            [{"name": "other_param", "value": 5, "category": "other"}]
        ))
        wiki2 = {"pages": [other_page, page]}
        papers2 = [other_paper, paper]
        second = extract_parameters(wiki2, papers2, client)

        # other_paper's params (index 0) + paper's cached params (index 1, re-stamped)
        cached_entry = [p for p in second if p["name"] == "prevalence"][0]
        self.assertEqual(cached_entry["paper_index"], 1)
        self.assertEqual(client.chat_json.call_count, 2)  # only other_paper triggered a real call

    def test_llm_call_error_is_never_cached(self):
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="rate_limit", detail="429"))
        wiki = {"pages": [_page()]}
        papers = [_paper()]

        # Spy on the real compute_cache_key instead of hand-deriving the
        # expected `context` string here -- duplicating extract_parameters'
        # context-building formula in the test would silently stop proving
        # anything if that formula ever changes (review finding).
        real_compute_cache_key = param_extractor.compute_cache_key
        captured = {}

        def _spy(*args, **kwargs):
            result = real_compute_cache_key(*args, **kwargs)
            captured["cache_key"] = result[0]
            return result

        with patch.object(param_extractor, "compute_cache_key", side_effect=_spy):
            result = extract_parameters(wiki, papers, client)

        self.assertEqual(result, [])  # existing Story 1.2 behavior: skip this paper's params
        self.assertIn("cache_key", captured)
        self.assertIsNone(db.get_cached_parameters(captured["cache_key"]))

    def test_malformed_but_successful_response_is_not_cached(self):
        # A Success result whose content fails every _robust_parse strategy
        # must not be cached as a confident "no params" -- that would freeze
        # a transient garbled/truncated LLM response forever (review finding).
        client = MagicMock()
        client.chat_json.return_value = Success("not json at all { truncated")
        wiki = {"pages": [_page()]}
        papers = [_paper()]

        result = extract_parameters(wiki, papers, client)
        self.assertEqual(result, [])
        self.assertEqual(client.chat_json.call_count, 1)

        # A second call for the identical paper must retry the LLM rather
        # than trusting a cached [] from the garbled response above.
        client.chat_json.return_value = Success(json.dumps([{"name": "p1", "value": 1, "category": "other"}]))
        second = extract_parameters(wiki, papers, client)
        self.assertEqual(len(second), 1)
        self.assertEqual(client.chat_json.call_count, 2)

    def test_confidently_empty_response_is_cached(self):
        # A genuine "no parameters found" response (a clean, parseable empty
        # array) IS a real result and should still be cached like any other
        # Success -- only an unparseable response should be skipped.
        client = MagicMock()
        client.chat_json.return_value = Success("[]")
        wiki = {"pages": [_page()]}
        papers = [_paper()]

        extract_parameters(wiki, papers, client)
        extract_parameters(wiki, papers, client)
        self.assertEqual(client.chat_json.call_count, 1)  # second call was a cache hit

    def test_stage_version_bump_bypasses_a_previously_cached_entry(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps(
            [{"name": "prevalence", "value": 10, "category": "prevalence"}]
        ))
        wiki = {"pages": [_page()]}
        papers = [_paper()]

        extract_parameters(wiki, papers, client)
        self.assertEqual(client.chat_json.call_count, 1)

        with patch.object(param_extractor, "PARAM_STAGE_VERSION", param_extractor.PARAM_STAGE_VERSION + 1):
            extract_parameters(wiki, papers, client)
        self.assertEqual(client.chat_json.call_count, 2)  # version bump -> real cache miss

    def test_duplicate_paper_in_same_run_is_a_cache_hit(self):
        # A write followed immediately by a read within a SINGLE
        # extract_parameters call, not just across two separate top-level
        # calls -- proves the write commits in time for a later iteration of
        # the same loop to see it (review finding).
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps(
            [{"name": "prevalence", "value": 10, "category": "prevalence"}]
        ))
        page, paper = _page(), _paper()
        wiki = {"pages": [page, page]}
        papers = [paper, paper]

        result = extract_parameters(wiki, papers, client)
        self.assertEqual(client.chat_json.call_count, 1)  # only the first occurrence called the LLM
        self.assertEqual(len(result), 2)  # both occurrences still contributed params
        self.assertEqual({p["paper_index"] for p in result}, {0, 1})

    def test_different_wiki_content_for_same_paper_is_a_cache_miss(self):
        # Proves the design point: the cache key is the wiki-derived `context`,
        # not paper["full_text"] -- a wiki update must invalidate the cache.
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps([{"name": "p1", "value": 1, "category": "other"}]))
        paper = _paper()

        extract_parameters({"pages": [_page(key_findings=("original finding",))]}, [paper], client)
        self.assertEqual(client.chat_json.call_count, 1)

        extract_parameters({"pages": [_page(key_findings=("updated finding",))]}, [paper], client)
        self.assertEqual(client.chat_json.call_count, 2)  # different wiki content -> real second call


if __name__ == "__main__":
    unittest.main()
