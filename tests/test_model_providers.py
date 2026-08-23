"""
Tests for utils/model_providers.py (Clinova model selector, 2026-08-23).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.model_providers import (
    PROVIDER_REGISTRY, DEFAULT_PROVIDER_KEY, get_provider, build_client,
)
from utils.azure_client import NVIDIA_BASE_URL, MASTER_MODEL, FALLBACK_MODEL


class ProviderRegistryShapeTests(unittest.TestCase):
    def test_all_four_expected_providers_exist(self):
        self.assertEqual(set(PROVIDER_REGISTRY.keys()), {"nvidia", "openai", "gemini", "qwen"})

    def test_default_provider_is_nvidia(self):
        self.assertEqual(DEFAULT_PROVIDER_KEY, "nvidia")

    def test_nvidia_config_matches_existing_production_defaults(self):
        # The whole point of this feature is that NVIDIA's behavior is
        # unchanged -- this locks that in against azure_client.py's own
        # module constants, not a duplicated literal.
        cfg = get_provider("nvidia")
        self.assertEqual(cfg.base_url, NVIDIA_BASE_URL)
        self.assertEqual(cfg.default_model, MASTER_MODEL)
        self.assertEqual(cfg.fallback_model, FALLBACK_MODEL)

    def test_only_nvidia_is_marked_verified_live(self):
        self.assertTrue(PROVIDER_REGISTRY["nvidia"].verified_live)
        for key in ("openai", "gemini", "qwen"):
            self.assertFalse(PROVIDER_REGISTRY[key].verified_live, f"{key} should be verified_live=False")

    def test_nvidia_known_models_include_deepseek_and_kimi(self):
        models = PROVIDER_REGISTRY["nvidia"].known_models
        self.assertTrue(any("deepseek" in m for m in models))
        self.assertTrue(any("kimi" in m for m in models))

    def test_every_provider_has_at_least_one_known_model(self):
        for key, cfg in PROVIDER_REGISTRY.items():
            self.assertGreater(len(cfg.known_models), 0, f"{key} has no known_models")

    def test_every_provider_default_model_is_in_its_known_models(self):
        for key, cfg in PROVIDER_REGISTRY.items():
            self.assertIn(cfg.default_model, cfg.known_models, f"{key}'s default_model not in known_models")

    def test_every_provider_has_a_distinct_api_key_env_var(self):
        env_vars = [cfg.api_key_env for cfg in PROVIDER_REGISTRY.values()]
        self.assertEqual(len(env_vars), len(set(env_vars)))


class GetProviderTests(unittest.TestCase):
    def test_known_provider_returns_config(self):
        cfg = get_provider("openai")
        self.assertEqual(cfg.key, "openai")

    def test_unknown_provider_raises_value_error(self):
        with self.assertRaises(ValueError):
            get_provider("not_a_real_provider")


class BuildClientTests(unittest.TestCase):
    @patch("utils.azure_client.make_nvidia_client")
    def test_nvidia_default_model_matches_current_production_behavior(self, mock_make):
        client = build_client("nvidia", "fake-key")
        self.assertEqual(client.model, MASTER_MODEL)
        self.assertEqual(client.fallback_model, FALLBACK_MODEL)

    @patch("utils.azure_client.make_nvidia_client")
    def test_nvidia_custom_model_override(self, mock_make):
        client = build_client("nvidia", "fake-key", model="deepseek-ai/deepseek-v4-flash-0731")
        self.assertEqual(client.model, "deepseek-ai/deepseek-v4-flash-0731")

    @patch("utils.azure_client.OpenAI")
    def test_openai_provider_uses_its_own_base_url_and_default_model(self, mock_openai_cls):
        client = build_client("openai", "fake-key")
        mock_openai_cls.assert_called_once_with(
            base_url="https://api.openai.com/v1", api_key="fake-key",
        )
        self.assertEqual(client.model, "gpt-5.6-luna")
        self.assertEqual(client.fallback_model, "gpt-5.6-terra")

    @patch("utils.azure_client.OpenAI")
    def test_gemini_provider_uses_its_own_base_url(self, mock_openai_cls):
        build_client("gemini", "fake-key")
        mock_openai_cls.assert_called_once_with(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/", api_key="fake-key",
        )

    @patch("utils.azure_client.OpenAI")
    def test_qwen_provider_has_no_fallback_model(self, mock_openai_cls):
        client = build_client("qwen", "fake-key")
        self.assertIsNone(client.fallback_model)

    def test_unknown_provider_raises_before_constructing_anything(self):
        with self.assertRaises(ValueError):
            build_client("not_a_real_provider", "fake-key")


if __name__ == "__main__":
    unittest.main()
