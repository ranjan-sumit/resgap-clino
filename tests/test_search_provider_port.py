"""
Tests for Clinova Phase 3, Epic 3.3, Story 3.3.1: packages/contracts/
search_provider.py's SearchProvider port. pipeline/academic_search.py is
NOT modified by this story -- SemanticScholarProvider/ArxivProvider
satisfy SearchProvider structurally (typing.Protocol), proven here
without any real network call. A second, independent, non-academic-API
implementation is checked against the same Protocol to prove the
interface isn't accidentally search-API-specific.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packages.contracts.search_provider import SearchProvider
from pipeline.search_providers import SemanticScholarProvider, ArxivProvider


class SecondIndependentProvider:
    """A minimal, deliberately non-academic-API implementation -- proves
    SearchProvider describes a genuine interface, not just an accidental
    shape both real adapters happen to share."""

    def search(self, query: str, limit: int = 5) -> tuple[list, bool]:
        return ([{"title": f"stub result for {query}"}], True)


class SearchProviderPortTests(unittest.TestCase):
    def test_semantic_scholar_provider_satisfies_the_port(self):
        provider = SemanticScholarProvider(api_key="fake-key")
        self.assertIsInstance(provider, SearchProvider)

    def test_arxiv_provider_satisfies_the_port(self):
        provider = ArxivProvider()
        self.assertIsInstance(provider, SearchProvider)

    def test_a_second_independent_implementation_also_satisfies_the_port(self):
        provider = SecondIndependentProvider()
        self.assertIsInstance(provider, SearchProvider)

    def test_an_object_missing_search_does_not_satisfy_the_port(self):
        class Incomplete:
            def fetch(self, query):  # wrong method name entirely
                return []

        self.assertNotIsInstance(Incomplete(), SearchProvider)

    def test_second_implementation_is_actually_callable_per_the_port_contract(self):
        provider = SecondIndependentProvider()
        results, ok = provider.search("test query")
        self.assertTrue(ok)
        self.assertEqual(results[0]["title"], "stub result for test query")


class AdapterDelegatesToExistingFunctionsTests(unittest.TestCase):
    """Proves the adapters are genuinely thin wrappers -- no new logic,
    same underlying function, same result -- not a reimplementation that
    could silently drift from the already-tested search behavior."""

    @patch("pipeline.search_providers._search_semantic_scholar_with_status")
    def test_semantic_scholar_provider_delegates_with_bound_api_key(self, mock_search):
        mock_search.return_value = ([{"title": "A"}], True)
        provider = SemanticScholarProvider(api_key="my-key")
        results, ok = provider.search("query", limit=3)
        mock_search.assert_called_once_with("query", limit=3, api_key="my-key")
        self.assertEqual(results, [{"title": "A"}])
        self.assertTrue(ok)

    @patch("pipeline.search_providers._search_arxiv_with_status")
    def test_arxiv_provider_delegates(self, mock_search):
        mock_search.return_value = ([], False)
        provider = ArxivProvider()
        results, ok = provider.search("query", limit=2)
        mock_search.assert_called_once_with("query", limit=2)
        self.assertEqual(results, [])
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
