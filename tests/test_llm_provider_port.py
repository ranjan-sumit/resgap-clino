"""
Tests for Clinova Phase 1, Epic 1.4, Story 1.4.1: packages/contracts/
llm_provider.py's LLMProvider port. utils/azure_client.py is NOT modified
by this story -- AzureOpenAIClient satisfies LLMProvider structurally
(typing.Protocol), which this test proves without touching that file or
making any real network call. A second, independent, non-NVIDIA
implementation is checked against the same Protocol to prove the
interface isn't accidentally NVIDIA-specific.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packages.contracts.llm_provider import LLMProvider
from utils.azure_client import AzureOpenAIClient, Success, Result


class SecondIndependentProvider:
    """A minimal, deliberately non-NVIDIA implementation -- proves
    LLMProvider describes a genuine interface, not just AzureOpenAIClient's
    accidental shape. Not used anywhere in the real pipeline; exists only
    to demonstrate the port generalizes (04-ai-research-architecture.md
    §1's future-provider-swap requirement)."""

    def chat(self, system: str, user: str,
             temperature: float = 0.3, max_tokens: int = 4096) -> "Result[str]":
        return Success(f"echo: {user}")

    def chat_json(self, system: str, user: str, max_tokens: int = 4096) -> "Result[str]":
        return Success("{}")

    def vision(self, system: str, user_text: str,
               image_bytes: bytes, max_tokens: int = 2048) -> "Result[str]":
        return Success("no image support")


class LLMProviderPortTests(unittest.TestCase):
    def test_azure_openai_client_satisfies_llm_provider_unmodified(self):
        # No changes to utils/azure_client.py were made for this story --
        # this proves the existing class already satisfies the port
        # structurally, without needing to inherit from it.
        client = AzureOpenAIClient(api_key="fake-key-for-structural-check-only")
        self.assertIsInstance(client, LLMProvider)

    def test_a_second_independent_implementation_also_satisfies_the_port(self):
        # Proves LLMProvider describes a real, swappable interface -- not
        # an NVIDIA-specific shape that happens to match one class.
        provider = SecondIndependentProvider()
        self.assertIsInstance(provider, LLMProvider)

    def test_an_object_missing_a_method_does_not_satisfy_the_port(self):
        class Incomplete:
            def chat(self, system, user, temperature=0.3, max_tokens=4096):
                return Success("x")
            # chat_json and vision deliberately missing

        self.assertNotIsInstance(Incomplete(), LLMProvider)

    def test_second_implementation_is_actually_callable_per_the_port_contract(self):
        provider = SecondIndependentProvider()
        result = provider.chat("sys", "hello")
        self.assertIsInstance(result, Success)
        self.assertEqual(result.value, "echo: hello")


if __name__ == "__main__":
    unittest.main()
