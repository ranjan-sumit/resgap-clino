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
        # B22 fix: after the primary model's 3 attempts are exhausted, one
        # more attempt is made on the fallback model (also fails here) --
        # call_count is 4, not 3, because of that new fallback attempt.
        self.mock_client.chat.completions.create.side_effect = Exception("429 Too Many Requests")
        result = self.client.chat("system", "user")
        self.assertIsInstance(result, Failure)
        self.assertIsInstance(result.error, ErrorInfo)
        self.assertEqual(result.error.kind, "rate_limit")
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 4)  # 3 primary + 1 fallback

    @patch("time.sleep", return_value=None)
    def test_chat_falls_back_to_smaller_model_after_primary_exhausted(self, _sleep):
        from utils.azure_client import FALLBACK_MODEL, MASTER_MODEL
        self.mock_client.chat.completions.create.side_effect = [
            Exception("429 Too Many Requests"),  # primary attempt 1
            Exception("429 Too Many Requests"),  # primary attempt 2
            Exception("429 Too Many Requests"),  # primary attempt 3
            _fake_stream("recovered on fallback model"),  # fallback attempt
        ]
        result = self.client.chat("system", "user")
        self.assertIsInstance(result, Success)
        self.assertEqual(result.value, "recovered on fallback model")
        calls = self.mock_client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0].kwargs["model"], MASTER_MODEL)
        self.assertEqual(calls[1].kwargs["model"], MASTER_MODEL)
        self.assertEqual(calls[2].kwargs["model"], MASTER_MODEL)
        self.assertEqual(calls[3].kwargs["model"], FALLBACK_MODEL)

    @patch("time.sleep", return_value=None)
    def test_chat_fallback_attempt_itself_is_not_retried(self, _sleep):
        # The fallback gets exactly one attempt -- if it also fails, chat()
        # must not recurse into retrying the fallback or falling back again.
        self.mock_client.chat.completions.create.side_effect = Exception("429 Too Many Requests")
        result = self.client.chat("system", "user")
        self.assertIsInstance(result, Failure)
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 4)  # not 5, 6, ...

    def test_chat_non_retryable_error_skips_fallback_too(self):
        # api_error (not rate_limit/timeout) fails fast on the primary model
        # -- switching models is unlikely to fix a genuine API/auth error,
        # so the fallback is deliberately not attempted for this kind.
        self.mock_client.chat.completions.create.side_effect = Exception("Connection refused")
        result = self.client.chat("system", "user")
        self.assertIsInstance(result, Failure)
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 1)

    @patch("time.sleep", return_value=None)
    def test_fallback_disabled_when_constructed_with_none(self, _sleep):
        with patch("utils.azure_client.make_nvidia_client") as mock_make:
            mock_client = mock_make.return_value
            client = AzureOpenAIClient(api_key="fake-key", fallback_model=None)
        mock_client.chat.completions.create.side_effect = Exception("429 Too Many Requests")
        result = client.chat("system", "user")
        self.assertIsInstance(result, Failure)
        self.assertEqual(mock_client.chat.completions.create.call_count, 3)  # no 4th fallback attempt

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
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 1)  # api_error: no retry

    @patch("time.sleep", return_value=None)
    def test_vision_retries_on_timeout_then_recovers(self, _sleep):
        # B22 fix: vision() previously had zero retries at all.
        self.mock_client.chat.completions.create.side_effect = [
            Exception("Request timeout after 120s"),
            _fake_stream("a cat", " (recovered)"),
        ]
        result = self.client.vision("system", "what is this?", b"fake-image-bytes")
        self.assertIsInstance(result, Success)
        self.assertEqual(result.value, "a cat (recovered)")
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 2)

    @patch("time.sleep", return_value=None)
    def test_vision_does_not_fall_back_to_a_different_model(self, _sleep):
        # Deliberately narrower than chat()'s fix -- FALLBACK_MODEL's
        # image-input support isn't confirmed, so vision() stays on
        # VISION_MODEL for all retry attempts, never switching models.
        from utils.azure_client import VISION_MODEL
        self.mock_client.chat.completions.create.side_effect = Exception("429 Too Many Requests")
        result = self.client.vision("system", "what is this?", b"fake-image-bytes")
        self.assertIsInstance(result, Failure)
        calls = self.mock_client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 3)  # initial + 2 retries, no 4th fallback attempt
        self.assertTrue(all(c.kwargs["model"] == VISION_MODEL for c in calls))

    def test_vision_uses_vision_model_not_master_model(self):
        # B25 fix regression guard: vision() must stay on VISION_MODEL even
        # though MASTER_MODEL now points at a model without confirmed
        # image-input support (20b) after the B25 master/fallback swap.
        from utils.azure_client import VISION_MODEL, MASTER_MODEL
        self.assertNotEqual(VISION_MODEL, MASTER_MODEL)
        self.mock_client.chat.completions.create.return_value = _fake_stream("a cat")
        self.client.vision("system", "what is this?", b"fake-image-bytes")
        call = self.mock_client.chat.completions.create.call_args_list[0]
        self.assertEqual(call.kwargs["model"], VISION_MODEL)


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
