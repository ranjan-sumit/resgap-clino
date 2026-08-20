"""
Tests for Story 2.6: _search_arxiv groups the gap's search terms as
explicit AND-joined arXiv field terms (all:term1 AND all:term2 ...),
not a single unquoted, space-separated blob (which arXiv parses as an
OR across individual words) and not a single quoted phrase (which would
return zero results for the realistic, non-phrase-shaped queries this
codebase actually builds).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from requests.models import PreparedRequest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.academic_search import ARXIV_BASE, _build_arxiv_query, _build_search_query, _search_arxiv, _truncate_at_word_boundary


class _FakeResponse:
    def __init__(self, status_code=200, text_data=""):
        self.status_code = status_code
        self.text = text_data

    def raise_for_status(self):
        pass


class BuildArxivQueryTests(unittest.TestCase):
    def test_multi_concept_query_is_and_joined(self):
        result = _build_arxiv_query("Mendelian Randomization ADHD brain structure")
        self.assertEqual(
            result,
            "all:Mendelian AND all:Randomization AND all:ADHD AND all:brain AND all:structure",
        )

    def test_single_word_query_has_no_dangling_and(self):
        self.assertEqual(_build_arxiv_query("electron"), "all:electron")

    def test_empty_query_does_not_crash(self):
        self.assertEqual(_build_arxiv_query(""), "all:")

    def test_whitespace_only_query_does_not_crash(self):
        self.assertEqual(_build_arxiv_query("   "), "all:")

    def test_reserved_characters_are_stripped_from_terms(self):
        # A gap title like 'Gap: (LLMs) reasoning' must not let ':', '(',
        # ')' corrupt the query structure (review finding).
        result = _build_arxiv_query('Gap: (LLMs) "reasoning"')
        self.assertEqual(result, "all:Gap AND all:LLMs AND all:reasoning")

    def test_literal_boolean_operator_words_are_dropped(self):
        # A term that is itself "AND"/"OR"/"NOT" must not corrupt the
        # boolean structure of the constructed query (review finding).
        result = _build_arxiv_query("machine learning AND deep learning")
        self.assertEqual(result, "all:machine AND all:learning AND all:deep AND all:learning")

    def test_term_that_is_only_reserved_characters_is_dropped_entirely(self):
        result = _build_arxiv_query('genomics ( ) data')
        self.assertEqual(result, "all:genomics AND all:data")


class SearchArxivQueryConstructionTests(unittest.TestCase):
    def test_search_query_param_is_and_joined(self):
        with patch("pipeline.academic_search.requests.get") as mock_get, \
             patch("pipeline.academic_search.time.sleep"):
            mock_get.return_value = _FakeResponse(200, text_data="")
            _search_arxiv("Mendelian Randomization ADHD")
        sent_query = mock_get.call_args.kwargs["params"]["search_query"]
        self.assertEqual(sent_query, "all:Mendelian AND all:Randomization AND all:ADHD")

    def test_no_double_encoding_in_the_real_prepared_request_url(self):
        # Review fix: the previous version of this test only inspected the
        # pre-request Python string (which can never contain "%" by
        # construction) -- a tautology. This builds a REAL requests
        # PreparedRequest, the same machinery `requests.get` uses, and
        # inspects the actual encoded URL that would be sent over the wire.
        query = _build_arxiv_query("COVID 19 outcomes")
        req = PreparedRequest()
        req.prepare_url(ARXIV_BASE, {"search_query": query})
        self.assertNotIn("%2520", req.url)  # would only appear if double-encoded
        self.assertIn("all%3ACOVID", req.url)  # confirms single, real encoding occurred

    def test_non_string_query_does_not_raise_and_falls_back_to_empty_list(self):
        with patch("pipeline.academic_search.requests.get") as mock_get, \
             patch("pipeline.academic_search.time.sleep"):
            results = _search_arxiv(None)  # type: ignore[arg-type]
        self.assertEqual(results, [])
        mock_get.assert_not_called()


class TruncateAtWordBoundaryTests(unittest.TestCase):
    def test_short_text_is_unchanged(self):
        self.assertEqual(_truncate_at_word_boundary("short text", 120), "short text")

    def test_long_text_truncates_at_the_last_space_not_mid_word(self):
        text = "Mendelian Randomization ADHD brain structural connectivity analysis methods"
        result = _truncate_at_word_boundary(text, 40)
        self.assertLessEqual(len(result), 40)
        self.assertTrue(text.startswith(result))
        # The character immediately after the truncated result, in the
        # original text, must be a space (or the end of the string) --
        # never mid-word.
        self.assertTrue(len(result) == len(text) or text[len(result)] == " ")

    def test_truncation_with_no_space_falls_back_to_raw_slice(self):
        # A single unbroken "word" longer than max_len has no space to
        # truncate at -- must still return something, not crash or return
        # empty.
        result = _truncate_at_word_boundary("a" * 200, 40)
        self.assertEqual(len(result), 40)

    def test_build_search_query_does_not_produce_a_mandatory_partial_term(self):
        # Integration-level proof: a long gap title/description must not
        # produce a _build_arxiv_query output with a mangled trailing term.
        gap = {
            "title": "Mendelian Randomization ADHD brain structural connectivity",
            "description": "A" * 200,
        }
        query = _build_search_query(gap)
        arxiv_query = _build_arxiv_query(query)
        # Every AND-joined term must be a real whitespace-delimited word
        # from the original query, not a character-sliced fragment of one.
        original_words = set(query.split())
        for clause in arxiv_query.split(" AND "):
            term = clause.removeprefix("all:")
            self.assertIn(term, original_words)


if __name__ == "__main__":
    unittest.main()
