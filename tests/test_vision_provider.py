"""
Vision is per-provider: VISION_MODEL is an NVIDIA NIM model ID, so it must only
be sent to the NVIDIA endpoint. Before this, selecting Gemini and ticking the
vision option sent `meta/llama-3.2-11b-vision-instruct` to Google's API, which
fails for every page.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import AzureOpenAIClient, VISION_MODEL, Failure
from utils.model_providers import PROVIDER_REGISTRY, build_client


class VisionModelSelectionTests(unittest.TestCase):
    @patch("utils.azure_client.make_nvidia_client")
    def test_nvidia_defaults_to_the_nvidia_vision_model(self, _mock):
        self.assertEqual(AzureOpenAIClient(api_key="k").vision_model, VISION_MODEL)

    @patch("utils.azure_client.OpenAI")
    def test_other_base_url_has_no_vision_model_by_default(self, _mock):
        c = AzureOpenAIClient(api_key="k", base_url="https://example.test/v1", model="m")
        self.assertIsNone(c.vision_model)

    @patch("utils.azure_client.OpenAI")
    def test_explicit_vision_model_is_honoured(self, _mock):
        c = AzureOpenAIClient(api_key="k", base_url="https://example.test/v1", model="m",
                              vision_model="some-vlm")
        self.assertEqual(c.vision_model, "some-vlm")

    @patch("utils.azure_client.OpenAI")
    def test_no_vision_model_fails_cleanly_without_calling_the_api(self, mock_openai):
        c = AzureOpenAIClient(api_key="k", base_url="https://example.test/v1", model="m")
        result = c.vision("system", "what is this?", b"img")
        self.assertIsInstance(result, Failure)
        self.assertEqual(result.error.kind, "unsupported")
        mock_openai.return_value.chat.completions.create.assert_not_called()

    @patch("utils.azure_client._collect_stream", return_value="a chart")
    @patch("utils.azure_client.OpenAI")
    def test_vision_call_uses_the_clients_vision_model(self, mock_openai, _collect):
        c = AzureOpenAIClient(api_key="k", base_url="https://example.test/v1", model="text-model",
                              vision_model="some-vlm")
        c.vision("system", "what is this?", b"img")
        self.assertEqual(mock_openai.return_value.chat.completions.create.call_args.kwargs["model"],
                         "some-vlm")


class ProviderRegistryVisionTests(unittest.TestCase):
    def test_registry_vision_models(self):
        self.assertEqual(PROVIDER_REGISTRY["nvidia"].vision_model, VISION_MODEL)
        self.assertTrue(PROVIDER_REGISTRY["gemini"].vision_model)
        self.assertIsNone(PROVIDER_REGISTRY["openai"].vision_model)   # unverified -> hidden in the UI
        self.assertIsNone(PROVIDER_REGISTRY["qwen"].vision_model)

    @patch("utils.azure_client.OpenAI")
    def test_build_client_passes_the_providers_vision_model(self, _mock):
        self.assertEqual(build_client("gemini", "k").vision_model, PROVIDER_REGISTRY["gemini"].vision_model)
        self.assertIsNone(build_client("openai", "k").vision_model)


if __name__ == "__main__":
    unittest.main()
