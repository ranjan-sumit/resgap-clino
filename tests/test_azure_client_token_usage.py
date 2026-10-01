"""
Tests for Clinova Phase 4, Epic 4.3 token instrumentation in
utils/azure_client.py: stream_options={"include_usage": True} is only
requested when a caller supplies a TokenMeter, usage is captured before
the existing chunk-skip, and a provider that rejects stream_options
degrades once (not counted against the retry budget) rather than failing
the whole call.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import AzureOpenAIClient, Success, _STREAM_OPTIONS_SUPPORT
from utils.token_meter import TokenMeter


def _chunk(content):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


def _usage_chunk(prompt_tokens=10, completion_tokens=5, total_tokens=15):
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                               total_tokens=total_tokens),
    )


def _fake_stream_with_usage(*parts, **usage_kwargs):
    return iter([_chunk(p) for p in parts] + [_usage_chunk(**usage_kwargs)])


class TokenUsageInstrumentationTests(unittest.TestCase):
    def setUp(self):
        # Isolate the module-level support cache per test -- shared global
        # state across test methods would make earlier tests' outcomes
        # leak into later ones (e.g. a "rejected" mark persisting).
        self._support_patcher = patch.dict("utils.azure_client._STREAM_OPTIONS_SUPPORT", {}, clear=True)
        self._support_patcher.start()
        with patch("utils.azure_client.make_nvidia_client") as mock_make_client:
            self.mock_client = mock_make_client.return_value
            self.client_no_meter = AzureOpenAIClient(api_key="fake-key")
            self.client_with_meter = AzureOpenAIClient(api_key="fake-key", token_meter=TokenMeter())
            # Both clients share the same mocked underlying OpenAI client
            # object here (make_nvidia_client mocked once per `with`) --
            # re-point client_with_meter's .client to the same mock.
            self.client_with_meter.client = self.mock_client

    def tearDown(self):
        self._support_patcher.stop()

    def test_no_token_meter_does_not_request_stream_options(self):
        self.mock_client.chat.completions.create.return_value = _fake_stream_with_usage("hi")
        self.client_no_meter.chat("system", "user")
        call_kwargs = self.mock_client.chat.completions.create.call_args.kwargs
        self.assertNotIn("stream_options", call_kwargs)

    def test_token_meter_requests_stream_options_and_records_usage(self):
        self.mock_client.chat.completions.create.return_value = _fake_stream_with_usage("hi", total_tokens=42)
        self.client_with_meter.set_stage("Stage 2 — LLM Wiki")
        result = self.client_with_meter.chat("system", "user")
        self.assertIsInstance(result, Success)
        self.assertEqual(result.value, "hi")

        call_kwargs = self.mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["stream_options"], {"include_usage": True})

        manifest = self.client_with_meter.token_meter.to_manifest_dict()
        self.assertEqual(manifest["total"], 42)
        self.assertEqual(manifest["by_stage"], {"Stage 2 — LLM Wiki": 42})

    def test_stream_with_no_usage_chunk_records_nothing(self):
        """A provider that accepts stream_options but never actually sends
        a usage chunk (or an older SDK stub) must not fabricate a usage
        record."""
        self.mock_client.chat.completions.create.return_value = iter([_chunk("hi")])
        self.client_with_meter.chat("system", "user")
        self.assertIsNone(self.client_with_meter.token_meter.to_manifest_dict())

    def test_stream_options_rejection_degrades_once_and_still_succeeds(self):
        # First call raises a stream_options-specific error; the client's
        # internal recursive retry (not counted against MAX_RETRIES) omits
        # stream_options and the (mocked) second attempt succeeds.
        self.mock_client.chat.completions.create.side_effect = [
            Exception("400 Bad Request: Unrecognized request argument supplied: stream_options"),
            _fake_stream_with_usage("hi"),
        ]
        result = self.client_with_meter.chat("system", "user")
        self.assertIsInstance(result, Success)
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 2)
        # Marked unsupported for this base_url -- a subsequent call must
        # not request stream_options again.
        from utils.azure_client import NVIDIA_BASE_URL
        self.assertFalse(_STREAM_OPTIONS_SUPPORT[NVIDIA_BASE_URL])

        self.mock_client.chat.completions.create.side_effect = None
        self.mock_client.chat.completions.create.return_value = _fake_stream_with_usage("again")
        self.client_with_meter.chat("system", "user")
        second_call_kwargs = self.mock_client.chat.completions.create.call_args.kwargs
        self.assertNotIn("stream_options", second_call_kwargs)

    def test_stream_options_rejection_does_not_consume_retry_budget(self):
        # A stream_options rejection followed by a genuine rate-limit
        # error must still get the FULL normal retry budget -- the
        # degrade-and-retry step must not eat into MAX_RETRIES.
        self.mock_client.chat.completions.create.side_effect = [
            Exception("400 Bad Request: stream_options not supported"),
            Exception("429 Too Many Requests"),
            Exception("429 Too Many Requests"),
            _fake_stream_with_usage("recovered"),
        ]
        with patch("time.sleep"):
            result = self.client_with_meter.chat("system", "user", max_retries=2)
        self.assertIsInstance(result, Success)
        self.assertEqual(result.value, "recovered")


class VisionTokenUsageTests(unittest.TestCase):
    """vision() now honors the same token-instrumentation contract as
    chat(): stream_options is only requested when a TokenMeter is present,
    captured usage is recorded (attributed to VISION_MODEL, not the text
    master model), and a provider that rejects stream_options degrades
    once to an unmetered -- never fabricated -- call."""

    def setUp(self):
        self._support_patcher = patch.dict("utils.azure_client._STREAM_OPTIONS_SUPPORT", {}, clear=True)
        self._support_patcher.start()
        self.addCleanup(self._support_patcher.stop)
        with patch("utils.azure_client.make_nvidia_client") as mock_make_client:
            self.mock_client = mock_make_client.return_value
            self.client_no_meter = AzureOpenAIClient(api_key="fake-key")
            self.client_with_meter = AzureOpenAIClient(api_key="fake-key", token_meter=TokenMeter())
            self.client_with_meter.client = self.mock_client

    def test_no_token_meter_does_not_request_stream_options(self):
        self.mock_client.chat.completions.create.return_value = _fake_stream_with_usage("a cat")
        result = self.client_no_meter.vision("system", "what is this?", b"img")
        self.assertIsInstance(result, Success)
        call_kwargs = self.mock_client.chat.completions.create.call_args.kwargs
        self.assertNotIn("stream_options", call_kwargs)

    def test_token_meter_requests_stream_options_and_records_usage(self):
        from utils.azure_client import VISION_MODEL
        self.mock_client.chat.completions.create.return_value = \
            _fake_stream_with_usage("a cat", total_tokens=42)
        self.client_with_meter.set_stage("Stage 1 — PDF Parse")
        result = self.client_with_meter.vision("system", "what is this?", b"img")
        self.assertIsInstance(result, Success)

        call_kwargs = self.mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["stream_options"], {"include_usage": True})
        self.assertEqual(call_kwargs["model"], VISION_MODEL)

        manifest = self.client_with_meter.token_meter.to_manifest_dict()
        self.assertEqual(manifest["total"], 42)
        self.assertEqual(manifest["by_model"], {VISION_MODEL: 42})
        self.assertEqual(manifest["by_stage"], {"Stage 1 — PDF Parse": 42})

    def test_stream_options_rejection_degrades_once_and_stays_unmetered(self):
        # First call raises a stream_options-specific error; vision()
        # retries once without stream_options (not counted against
        # MAX_RETRIES) and succeeds -- with token_usage honestly absent,
        # not estimated.
        self.mock_client.chat.completions.create.side_effect = [
            Exception("400 Bad Request: Unrecognized request argument supplied: stream_options"),
            _fake_stream_with_usage("a cat"),
        ]
        result = self.client_with_meter.vision("system", "what is this?", b"img")
        self.assertIsInstance(result, Success)
        self.assertEqual(self.mock_client.chat.completions.create.call_count, 2)

        from utils.azure_client import NVIDIA_BASE_URL
        self.assertFalse(_STREAM_OPTIONS_SUPPORT[NVIDIA_BASE_URL])
        self.assertIsNone(self.client_with_meter.token_meter.to_manifest_dict())

        self.mock_client.chat.completions.create.side_effect = None
        self.mock_client.chat.completions.create.return_value = _fake_stream_with_usage("a cat")
        self.client_with_meter.vision("system", "what is this?", b"img")
        second_call_kwargs = self.mock_client.chat.completions.create.call_args.kwargs
        self.assertNotIn("stream_options", second_call_kwargs)


if __name__ == "__main__":
    unittest.main()
