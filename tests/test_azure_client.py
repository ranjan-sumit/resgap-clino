"""
Tests for the Result-type contract on utils/azure_client.py's chat(), chat_json(), and
vision() methods (Story 1.1 — AD-4). Uses stdlib unittest (no test framework existed
in this repo before this story; see project-context.md and the story's Open Questions).
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import (
    AzureOpenAIClient, Success, Failure, ErrorInfo, _classify_error,
    unwrap, LLMCallError,
)


def _chunk(content):
    delta = SimpleNamespace(content=content)
    choice = SimpleNamespace(delta=delta)
    return SimpleNamespace(choices=[choice])


def _fake_stream(*parts):
    return iter([_chunk(p) for p in parts])


class ChatResultTests(unittest.TestCase):
    def setUp(self):
        with patch("utils.azure_client.make_nvidia_client") as self.mock_make_client:
            self.mock_client = self.mock_make_client.return_value
            self.client = AzureOpenAIClient(api_key="fake-key")

    def test_constructor_passes_api_key_to_make_nvidia_client(self):
        self.mock_make_client.assert_called_once_with("fake-key")

    def test_chat_success_returns_success(self):
        self.mock_client.chat.completions.create.return_value = _fake_stream("Hello, ", "world!")
        result = self.client.chat("system", "user")
        self.assertIsInstance(result, Success)
        self.assertEqual(result.value, "Hello, world!")

    @patch("time.sleep", return_value=None)
    def test_chat_rate_limit_exhaustion_returns_failure(self, _sleep):
        self.mock_client.chat.completions.create.side_effect = Exception("429 Too Many Requests")
        result = self.client.chat("system", "user")
        self.assertIsInstance(result, Failure)
        self.assertIsInstance(result.error, ErrorInfo)
        self.assertEqual(result.error.kind, "rate_limit")
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 3)  # initial + 2 retries

    @patch("time.sleep", return_value=None)
    def test_chat_timeout_exhaustion_returns_failure(self, _sleep):
        self.mock_client.chat.completions.create.side_effect = Exception("Request timeout after 120s")
        result = self.client.chat("system", "user")
        self.assertIsInstance(result, Failure)
        self.assertEqual(result.error.kind, "timeout")

    @patch("time.sleep", return_value=None)
    def test_chat_recovers_after_transient_failure(self, _sleep):
        self.mock_client.chat.completions.create.side_effect = [
            Exception("429 Too Many Requests"),
            _fake_stream("recovered"),
        ]
        result = self.client.chat("system", "user")
        self.assertIsInstance(result, Success)
        self.assertEqual(result.value, "recovered")
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 2)

    def test_chat_non_retryable_error_returns_api_error_without_retry(self):
        self.mock_client.chat.completions.create.side_effect = Exception("Connection refused")
        result = self.client.chat("system", "user")
        self.assertIsInstance(result, Failure)
        self.assertEqual(result.error.kind, "api_error")
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 1)  # no retry

    def test_chat_json_success_delegates_to_chat(self):
        self.mock_client.chat.completions.create.return_value = _fake_stream('{"a": 1}')
        result = self.client.chat_json("system", "user")
        self.assertIsInstance(result, Success)
        self.assertEqual(result.value, '{"a": 1}')

    def test_chat_json_failure_delegates_to_chat(self):
        self.mock_client.chat.completions.create.side_effect = Exception("Connection refused")
        result = self.client.chat_json("system", "user")
        self.assertIsInstance(result, Failure)
        self.assertEqual(result.error.kind, "api_error")

    def test_vision_success_returns_success(self):
        self.mock_client.chat.completions.create.return_value = _fake_stream("a cat")
        result = self.client.vision("system", "what is this?", b"fake-image-bytes")
        self.assertIsInstance(result, Success)
        self.assertEqual(result.value, "a cat")

    def test_vision_failure_returns_failure(self):
        self.mock_client.chat.completions.create.side_effect = Exception("model unavailable")
        result = self.client.vision("system", "what is this?", b"fake-image-bytes")
        self.assertIsInstance(result, Failure)
        self.assertEqual(result.error.kind, "api_error")


class ClassifyErrorTests(unittest.TestCase):
    def test_priority_order_rate_limit_before_timeout(self):
        # A message containing both signals must classify as rate_limit (priority order).
        self.assertEqual(_classify_error("timeout: 429 rate limit exceeded"), "rate_limit")

    def test_rate_limit_requires_word_boundary_not_bare_substring(self):
        # "generate"/"moderate" contain "rate" but must NOT classify as rate_limit.
        self.assertEqual(_classify_error("failed to generate response"), "api_error")
        self.assertEqual(_classify_error("content flagged by moderate filter"), "api_error")

    def test_timeout_matches_timed_out_phrasing(self):
        self.assertEqual(_classify_error("connection timed out"), "timeout")


class UnwrapTests(unittest.TestCase):
    def test_unwrap_success_returns_value(self):
        self.assertEqual(unwrap(Success("hello")), "hello")

    def test_unwrap_failure_raises_llm_call_error(self):
        error = ErrorInfo(kind="rate_limit", detail="429 too many requests")
        with self.assertRaises(LLMCallError) as ctx:
            unwrap(Failure(error))
        self.assertIs(ctx.exception.error, error)
        self.assertIn("rate_limit", str(ctx.exception))
        self.assertIn("429 too many requests", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
