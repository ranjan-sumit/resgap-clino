"""
Tests for pipeline/relevance_ranking.py (Clinova Phase 3, Epic 3.5).
Mocked HTTP/OpenAI client -- no live NVIDIA API needed for this suite,
matching this codebase's existing convention for external-service modules
(pipeline/graph_persistence.py's tests use the same approach).
"""
import unittest
from unittest.mock import patch, MagicMock

from pipeline.relevance_ranking import embed_texts, rerank_candidates, RERANK_URL, RERANK_MODEL


class EmbedTextsTests(unittest.TestCase):
    def test_empty_input_returns_empty_without_a_call(self):
        self.assertEqual(embed_texts([], api_key="x"), [])

    @patch("pipeline.relevance_ranking.OpenAI")
    def test_passes_input_type_via_extra_body(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[0.1, 0.2]), MagicMock(embedding=[0.3, 0.4])]
        )
        result = embed_texts(["a", "b"], api_key="x", input_type="query")
        self.assertEqual(result, [[0.1, 0.2], [0.3, 0.4]])
        _, kwargs = mock_client.embeddings.create.call_args
        self.assertEqual(kwargs["extra_body"], {"input_type": "query"})
        self.assertEqual(kwargs["input"], ["a", "b"])

    @patch("pipeline.relevance_ranking.OpenAI")
    def test_default_input_type_is_passage(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.embeddings.create.return_value = MagicMock(data=[MagicMock(embedding=[0.1])])
        embed_texts(["doc"], api_key="x")
        _, kwargs = mock_client.embeddings.create.call_args
        self.assertEqual(kwargs["extra_body"], {"input_type": "passage"})


class RerankCandidatesTests(unittest.TestCase):
    def test_empty_passages_returns_empty_without_a_call(self):
        self.assertEqual(rerank_candidates("query", [], api_key="x"), [])

    def test_empty_query_returns_empty_without_a_call(self):
        self.assertEqual(rerank_candidates("", ["a passage"], api_key="x"), [])

    @patch("pipeline.relevance_ranking.requests.post")
    def test_posts_to_the_correct_url_and_model(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"rankings": [{"index": 0, "logit": 1.5}]},
        )
        mock_post.return_value.raise_for_status.return_value = None
        rerank_candidates("query text", ["passage text"], api_key="secret")
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], RERANK_URL)
        self.assertEqual(kwargs["json"]["model"], RERANK_MODEL)
        self.assertEqual(kwargs["json"]["query"], {"text": "query text"})
        self.assertEqual(kwargs["json"]["passages"], [{"text": "passage text"}])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")

    @patch("pipeline.relevance_ranking.requests.post")
    def test_maps_rankings_response_to_index_score_dicts(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"rankings": [
                {"index": 2, "logit": 5.0},
                {"index": 0, "logit": 1.0},
                {"index": 1, "logit": -3.0},
            ]},
        )
        mock_post.return_value.raise_for_status.return_value = None
        result = rerank_candidates("q", ["a", "b", "c"], api_key="x")
        self.assertEqual(result, [
            {"index": 2, "score": 5.0},
            {"index": 0, "score": 1.0},
            {"index": 1, "score": -3.0},
        ])

    @patch("pipeline.relevance_ranking.requests.post")
    def test_http_error_raises_not_swallowed(self, mock_post):
        import requests
        mock_post.return_value = MagicMock(status_code=500)
        mock_post.return_value.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
        with self.assertRaises(requests.exceptions.HTTPError):
            rerank_candidates("q", ["a"], api_key="x")


if __name__ == "__main__":
    unittest.main()
