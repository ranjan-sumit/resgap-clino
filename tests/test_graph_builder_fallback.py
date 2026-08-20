"""
Tests for Story 1.3: build_knowledge_graph distinguishes an LLM call failure
from a genuine empty extraction, recording a distinct diagnostics.fallback_reason
for each rather than collapsing both into one generic message. Also verifies
community detection (a second, independent LLM call) can never crash the
function uncaught, on any path.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import Success, Failure, ErrorInfo
from pipeline.graph_builder import build_knowledge_graph


def _wiki(key_concepts=("x",)):
    return {
        "pages": [{"title": "Paper One", "key_concepts": list(key_concepts), "methods": [], "limitations": [],
                    "future_work": [], "datasets": [], "key_findings": [], "evaluated_on": []}],
        "cross_links": {},
    }


_ENTITY_JSON = (
    '{"entities": [{"id": "e1", "name": "Entity One", "type": "concept", '
    '"papers": ["Paper One"], "importance": "high"}], "relationships": []}'
)
_COMMUNITY_JSON = '[{"id": "c1", "theme": "Theme One", "entities": ["e1"], "summary": "s", "gap_signal": "g"}]'


class LLMCallFailureTests(unittest.TestCase):
    def test_llm_call_failure_produces_distinct_fallback_reason_and_kind(self):
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="rate_limit", detail="429 too many requests"))

        result = build_knowledge_graph(_wiki(), client)

        self.assertTrue(result["diagnostics"]["used_fallback"])
        self.assertEqual(result["diagnostics"]["fallback_reason"], "LLM call failed: 429 too many requests")
        self.assertEqual(result["diagnostics"]["fallback_kind"], "rate_limit")
        self.assertEqual(result["diagnostics"]["llm_entities"], 0)
        self.assertEqual(result["diagnostics"]["llm_relationships"], 0)
        # still returns a usable fallback graph, not a crash
        self.assertGreater(len(result["entities"]), 0)

    def test_llm_call_failure_reason_formats_for_every_error_kind(self):
        for kind in ("timeout", "api_error"):
            with self.subTest(kind=kind):
                client = MagicMock()
                client.chat_json.return_value = Failure(ErrorInfo(kind=kind, detail=f"{kind} detail"))
                result = build_knowledge_graph(_wiki(), client)
                self.assertEqual(result["diagnostics"]["fallback_kind"], kind)
                self.assertIn(f"{kind} detail", result["diagnostics"]["fallback_reason"])

    def test_community_detection_failure_after_extraction_failure_does_not_crash(self):
        # B13 fix (review pass): community detection is attempted even after
        # extraction failed (not pre-emptively skipped), but its own failure
        # must still be caught, not propagate uncaught.
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="rate_limit", detail="429"))

        result = build_knowledge_graph(_wiki(), client)

        self.assertEqual(client.chat_json.call_count, 2)  # extraction + community detection, both attempted
        self.assertEqual(result["communities"], [])  # second failure degrades gracefully, no crash

    def test_llm_call_failure_with_empty_wiki_still_returns_sane_result(self):
        # Boundary case: fallback graph from a wiki with nothing extractable
        # beyond the paper itself (_fallback_graph_from_wiki always adds a
        # "domain" entity for the paper title, even with no other fields).
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="api_error", detail="down"))

        result = build_knowledge_graph(_wiki(key_concepts=[]), client)

        self.assertTrue(result["diagnostics"]["used_fallback"])
        self.assertEqual(len(result["entities"]), 1)
        self.assertEqual(result["entities"][0]["type"], "domain")
        self.assertEqual(result["communities"], [])
        self.assertEqual(result["stats"]["entity_count"], 1)


class GenuineEmptyExtractionTests(unittest.TestCase):
    def test_genuine_empty_extraction_keeps_existing_reason(self):
        client = MagicMock()
        client.chat_json.return_value = Success('{"entities": [], "relationships": []}')

        result = build_knowledge_graph(_wiki(), client)

        self.assertTrue(result["diagnostics"]["used_fallback"])
        self.assertEqual(result["diagnostics"]["fallback_reason"], "LLM graph extraction returned no entities.")
        self.assertNotIn("fallback_kind", result["diagnostics"])  # only set on the LLMCallError path

    def test_genuine_empty_extraction_still_attempts_community_detection(self):
        # Regression guard: the LLM-failure path's community-detection
        # protection must not accidentally suppress it on this path too.
        client = MagicMock()
        client.chat_json.side_effect = [
            Success('{"entities": [], "relationships": []}'),  # extraction: genuinely empty
            Success(_COMMUNITY_JSON),                          # community detection on the fallback graph
        ]

        result = build_knowledge_graph(_wiki(), client)

        self.assertEqual(client.chat_json.call_count, 2)
        self.assertEqual(len(result["communities"]), 1)
        self.assertEqual(result["communities"][0]["theme"], "Theme One")


class SuccessfulExtractionTests(unittest.TestCase):
    def test_successful_extraction_does_not_set_fallback_reason(self):
        client = MagicMock()
        client.chat_json.side_effect = [Success(_ENTITY_JSON), Success(_COMMUNITY_JSON)]

        result = build_knowledge_graph(_wiki(), client)

        self.assertFalse(result["diagnostics"]["used_fallback"])
        self.assertNotIn("fallback_reason", result["diagnostics"])
        self.assertNotIn("fallback_kind", result["diagnostics"])
        self.assertEqual(len(result["communities"]), 1)

    def test_community_detection_failure_after_successful_extraction_does_not_crash(self):
        # This is the case both independent reviewers flagged: extraction
        # succeeds, but the separate community-detection call fails on its
        # own (e.g. a rate limit that starts mid-run) — must not crash.
        client = MagicMock()
        client.chat_json.side_effect = [
            Success(_ENTITY_JSON),
            Failure(ErrorInfo(kind="rate_limit", detail="429 mid-run")),
        ]

        result = build_knowledge_graph(_wiki(), client)

        self.assertFalse(result["diagnostics"]["used_fallback"])  # extraction itself succeeded
        self.assertEqual(result["communities"], [])               # community detection degraded gracefully


if __name__ == "__main__":
    unittest.main()
