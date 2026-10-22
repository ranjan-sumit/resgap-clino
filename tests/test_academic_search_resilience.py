"""
Tests for Story 2.5: _search_semantic_scholar/_search_arxiv raise on a
non-2xx response and retry with tenacity (exponential backoff + jitter)
before finally falling back to an empty result -- retrying only genuinely
transient conditions (network errors, 429, 5xx), never a permanent 4xx
client error. Semantic Scholar calls carry an optional x-api-key header.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import academic_search
from pipeline.academic_search import _search_semantic_scholar, _search_arxiv


class _FakeResponse:
    def __init__(self, status_code, json_data=None, text_data=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text_data

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            err = requests.exceptions.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err

    def json(self):
        return self._json_data


_SS_SUCCESS_JSON = {"data": [{"title": "A Paper", "year": 2020, "abstract": "abc", "citationCount": 5, "authors": []}]}

_ARXIV_ENTRY = """<entry><title>A Paper</title><published>2020-01-01T00:00:00Z</published>
<summary>An abstract.</summary></entry>"""


class SemanticScholarResilienceTests(unittest.TestCase):
    def test_retries_on_429_then_succeeds(self):
        with patch("pipeline.academic_search.requests.get") as mock_get, \
             patch("pipeline.academic_search.time.sleep"):
            mock_get.side_effect = [_FakeResponse(429), _FakeResponse(429), _FakeResponse(200, _SS_SUCCESS_JSON)]
            results = _search_semantic_scholar("query", limit=5)
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "A Paper")

    def test_persistent_429_falls_back_to_empty_list(self):
        with patch("pipeline.academic_search.requests.get") as mock_get, \
             patch("pipeline.academic_search.time.sleep"):
            mock_get.return_value = _FakeResponse(429)
            results = _search_semantic_scholar("query", limit=5)
        self.assertEqual(results, [])
        self.assertGreater(mock_get.call_count, 1)  # actually retried, not just failed once

    def test_404_does_not_retry(self):
        with patch("pipeline.academic_search.requests.get") as mock_get, \
             patch("pipeline.academic_search.time.sleep"):
            mock_get.return_value = _FakeResponse(404)
            results = _search_semantic_scholar("query", limit=5)
        self.assertEqual(results, [])
        self.assertEqual(mock_get.call_count, 1)  # permanent client error -- no retry

    def test_api_key_sent_as_header_when_provided(self):
        with patch("pipeline.academic_search.requests.get") as mock_get, \
             patch("pipeline.academic_search.time.sleep"):
            mock_get.return_value = _FakeResponse(200, _SS_SUCCESS_JSON)
            _search_semantic_scholar("query", limit=5, api_key="my-ss-key")
        self.assertEqual(mock_get.call_args.kwargs["headers"], {"x-api-key": "my-ss-key"})

    def test_no_api_key_header_when_not_provided(self):
        with patch("pipeline.academic_search.requests.get") as mock_get, \
             patch("pipeline.academic_search.time.sleep"):
            mock_get.return_value = _FakeResponse(200, _SS_SUCCESS_JSON)
            _search_semantic_scholar("query", limit=5)
        self.assertEqual(mock_get.call_args.kwargs["headers"], {})


class ArxivResilienceTests(unittest.TestCase):
    def test_retries_on_429_then_succeeds(self):
        with patch("pipeline.academic_search.requests.get") as mock_get, \
             patch("pipeline.academic_search.time.sleep"):
            mock_get.side_effect = [_FakeResponse(429), _FakeResponse(200, text_data=_ARXIV_ENTRY)]
            results = _search_arxiv("query", limit=3)
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "A Paper")

    def test_persistent_failure_falls_back_to_empty_list(self):
        with patch("pipeline.academic_search.requests.get") as mock_get, \
             patch("pipeline.academic_search.time.sleep"):
            mock_get.return_value = _FakeResponse(500)
            results = _search_arxiv("query", limit=3)
        self.assertEqual(results, [])
        self.assertGreater(mock_get.call_count, 1)

    def test_404_does_not_retry(self):
        with patch("pipeline.academic_search.requests.get") as mock_get, \
             patch("pipeline.academic_search.time.sleep"):
            mock_get.return_value = _FakeResponse(404)
            results = _search_arxiv("query", limit=3)
        self.assertEqual(results, [])
        self.assertEqual(mock_get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
