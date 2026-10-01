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

    def test_default_model_and_base_url_are_nvidia(self):
        from utils.azure_client import MASTER_MODEL, NVIDIA_BASE_URL, FALLBACK_MODEL
        self.assertEqual(self.client.model, MASTER_MODEL)
        self.assertEqual(self.client.fallback_model, FALLBACK_MODEL)

    def test_custom_base_url_and_model_are_used(self):
        with patch("utils.azure_client.OpenAI") as mock_openai_cls:
            client = AzureOpenAIClient(
                api_key="other-key", base_url="https://api.openai.com/v1", model="gpt-5.6-luna",
            )
        mock_openai_cls.assert_called_once_with(base_url="https://api.openai.com/v1", api_key="other-key")
        self.assertEqual(client.model, "gpt-5.6-luna")

    def test_non_nvidia_base_url_defaults_fallback_to_none(self):
        # A caller not explicitly passing fallback_model, on a non-NVIDIA
        # base_url, must not inherit NVIDIA's FALLBACK_MODEL string --
        # that model doesn't exist in a different provider's catalog.
        with patch("utils.azure_client.OpenAI"):
            client = AzureOpenAIClient(api_key="k", base_url="https://api.openai.com/v1", model="gpt-5.6-luna")
        self.assertIsNone(client.fallback_model)

    def test_non_nvidia_base_url_respects_explicit_fallback_model(self):
        with patch("utils.azure_client.OpenAI"):
            client = AzureOpenAIClient(
                api_key="k", base_url="https://api.openai.com/v1", model="gpt-5.6-luna",
                fallback_model="gpt-5.6-terra",
            )
        self.assertEqual(client.fallback_model, "gpt-5.6-terra")

    def test_chat_success_returns_success(self):
        self.mock_client.chat.completions.create.return_value = _fake_stream("Hello, ", "world!")
        result = self.client.chat("system", "user")
        self.assertIsInstance(result, Success)
        self.assertEqual(result.value, "Hello, world!")

    def test_default_timeout_is_120_when_not_overridden(self):
        # Epic 3.6: timeout_seconds is now a real per-call override -- this
        # locks in that omitting it preserves the exact prior hardcoded
        # default, so every pre-Epic-3.6 caller's behavior is unchanged.
        self.mock_client.chat.completions.create.return_value = _fake_stream("ok")
        self.client.chat("system", "user")
        call = self.mock_client.chat.completions.create.call_args
        self.assertEqual(call.kwargs["timeout"], 120)

    def test_timeout_seconds_override_is_passed_through(self):
        self.mock_client.chat.completions.create.return_value = _fake_stream("ok")
        self.client.chat("system", "user", timeout_seconds=30)
        call = self.mock_client.chat.completions.create.call_args
        self.assertEqual(call.kwargs["timeout"], 30)

    @patch("time.sleep", return_value=None)
    def test_max_retries_override_is_respected(self, _sleep):
        # Default is 2 retries + 1 fallback attempt = 4 total. An explicit
        # max_retries=0 should mean 1 primary attempt + 1 fallback attempt,
        # no retries at all on the primary model.
        self.mock_client.chat.completions.create.side_effect = Exception("429 Too Many Requests")
        result = self.client.chat("system", "user", max_retries=0)
        self.assertIsInstance(result, Failure)
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 2)  # 1 primary + 1 fallback

    def test_chat_json_passes_through_timeout_and_retries(self):
        self.mock_client.chat.completions.create.return_value = _fake_stream('{"a": 1}')
        self.client.chat_json("system", "user", timeout_seconds=45, max_retries=1)
        call = self.mock_client.chat.completions.create.call_args
        self.assertEqual(call.kwargs["timeout"], 45)

    def test_deadline_is_enforced_mid_stream_not_just_passed_to_the_sdk(self):
        # Real bug found live (2026-08-22): the openai SDK's `timeout=`
        # kwarg does NOT reliably bound total streaming duration -- a real
        # call with timeout_seconds=1 completed successfully in 47.3s,
        # because NVIDIA NIM's periodic chunks each individually complete
        # under httpx's own per-read timeout. Simulates that shape here: a
        # generator that yields chunks slowly enough to cross a short
        # deadline between them, with no single read taking long -- the
        # loop-level deadline check (not the SDK timeout=) must catch it.
        import time as time_module

        # Real chunk objects with a real time.sleep between yields, so the
        # deadline is crossed BETWEEN chunks, not during a single read.
        def gen():
            c1 = list(_fake_stream("first chunk "))[0]
            yield c1
            time_module.sleep(0.05)
            c2 = list(_fake_stream("second chunk"))[0]
            yield c2

        # fallback_model=None: a fallback retry would consume the same
        # (already-exhausted) generator and mask the real assertion behind
        # an unrelated empty-stream Success -- irrelevant to what this test
        # checks, so disabled here the same way the live reproduction was.
        with patch("utils.azure_client.make_nvidia_client") as mock_make:
            mock_client = mock_make.return_value
            client = AzureOpenAIClient(api_key="fake-key", fallback_model=None)
        mock_client.chat.completions.create.return_value = gen()
        result = client.chat("system", "user", timeout_seconds=0, max_retries=0)
        self.assertIsInstance(result, Failure)
        self.assertEqual(result.error.kind, "timeout")

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

    def test_deadline_is_computed_before_create_is_invoked(self):
        # create() itself can block up to TIMEOUT_SECS waiting for response
        # headers -- the wall-clock deadline must start before create() is
        # called, or the effective per-call timeout is up to 2x TIMEOUT_SECS.
        import time as time_module
        events = []

        def fake_monotonic():
            events.append("monotonic")
            return 1000.0

        def fake_create(*args, **kwargs):
            events.append("create")
            return _fake_stream("ok")

        self.mock_client.chat.completions.create.side_effect = fake_create
        with patch.object(time_module, "monotonic", fake_monotonic):
            result = self.client.chat("system", "user")
        self.assertIsInstance(result, Success)
        # First monotonic read is the deadline computation; create() must
        # come after it (the later monotonic reads are the stream loop's
        # per-chunk deadline checks).
        self.assertEqual(events[0], "monotonic")
        self.assertEqual(events[1], "create")

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
