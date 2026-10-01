"""
Regression tests for pipeline/discovery_engine.py's failure handling.

A paper whose fingerprint LLM call failed (or returned an unparseable
response) used to produce an untagged stub
{"paper_title": ..., "unique_contribution": "Could not extract"} that was
fed verbatim into cross-paper combination and hypothesis generation,
counted in stats["papers_fingerprinted"], and indistinguishable from a
real fingerprint. Stubs are now tagged with "_extract_failed", excluded
from combination/hypothesis generation, and counted separately in stats.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import Success, Failure, ErrorInfo
from pipeline.discovery_engine import extract_paper_fingerprints, run_discovery_engine


def _wiki_two_pages():
    return {"pages": [
        {"title": "Paper One", "contributions": ["contribution one"]},
        {"title": "Paper Two", "contributions": ["contribution two"]},
    ]}


class FingerprintStubTaggingTests(unittest.TestCase):
    def test_llm_failure_produces_tagged_stub_not_a_silent_fingerprint(self):
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="rate_limit", detail="429"))

        fps = extract_paper_fingerprints(_wiki_two_pages(), client)

        self.assertEqual(len(fps), 2)
        for fp in fps:
            self.assertTrue(fp.get("_extract_failed"))
            self.assertEqual(fp["unique_contribution"], "Could not extract")

    def test_unexpected_non_llm_error_also_produces_tagged_stub(self):
        # Only LLMCallError used to be caught -- any client/parser failure
        # must degrade to the stub, never abort the loop.
        client = MagicMock()
        client.chat_json.side_effect = ValueError("unexpected client failure")

        fps = extract_paper_fingerprints(_wiki_two_pages(), client)

        self.assertEqual(len(fps), 2)
        self.assertTrue(all(fp.get("_extract_failed") for fp in fps))

    def test_empty_parse_produces_tagged_stub(self):
        client = MagicMock()
        client.chat_json.return_value = Success("not json at all")

        fps = extract_paper_fingerprints(_wiki_two_pages(), client)

        self.assertTrue(all(fp.get("_extract_failed") for fp in fps))


class RunDiscoveryEngineFailureStatsTests(unittest.TestCase):
    def _client_with_one_failure(self):
        client = MagicMock()
        client.chat_json.side_effect = [
            Failure(ErrorInfo(kind="rate_limit", detail="429")),   # Paper One fingerprint
            Success(json.dumps({"paper_title": "Paper Two",
                                "unique_contribution": "Found something unique"})),  # Paper Two
            Success("[]"),   # hypotheses (combinations short-circuit: <2 usable)
        ]
        return client

    def test_failed_fingerprints_excluded_from_generation_and_counted_separately(self):
        client = self._client_with_one_failure()

        result = run_discovery_engine(_wiki_two_pages(), params=[], context={}, client=client)

        self.assertEqual(result["stats"]["papers_fingerprinted"], 1)
        self.assertEqual(result["stats"]["papers_fingerprint_failed"], 1)
        self.assertIn("combinations_found", result["stats"])
        self.assertIn("hypotheses_generated", result["stats"])

        # The raw list still carries the stub, but visibly tagged.
        self.assertTrue(result["fingerprints"][0].get("_extract_failed"))
        self.assertFalse(result["fingerprints"][1].get("_extract_failed"))

    def test_stub_never_reaches_the_hypothesis_prompt(self):
        client = self._client_with_one_failure()

        run_discovery_engine(_wiki_two_pages(), params=[], context={}, client=client)

        hypo_calls = [c for c in client.chat_json.call_args_list
                      if c.kwargs.get("max_tokens") == 5000]
        self.assertEqual(len(hypo_calls), 1)
        self.assertNotIn("Could not extract", hypo_calls[0].args[1])


if __name__ == "__main__":
    unittest.main()
