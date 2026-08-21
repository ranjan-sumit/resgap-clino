"""
Tests for B19 fix (2026-08-20): detect_gaps() no longer silently collapses a
JSON-parse failure into an empty gap list indistinguishable from a genuine
"the LLM found zero gaps" result. It retries once (LLM output is
nondeterministic -- live-reproduced: an identical retry recovered a valid
gap list after one parse failure), and raises GapDetectionError explicitly
if both attempts fail to parse, rather than returning [].

See evals/benchmarks/baseline/phase0-findings.md for the real-data finding
that motivated this fix, and its downstream companion fix in
test_proposal_generator_empty_guard.py.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import Success
from pipeline.gap_detector import detect_gaps, GapDetectionError


def _wiki():
    return {
        "pages": [{"title": "Paper One", "contributions": [], "methods": [], "limitations": ["no external validation"],
                    "future_work": [], "evaluated_on": [], "comparison_gap": ""}],
        "cross_links": {},
    }


def _graph():
    return {"communities": [], "orphan_concepts": [], "missing_bridges": []}


_VALID_GAPS_JSON = (
    '[{"title": "Gap One", "description": "desc", "gap_type": "methodology", '
    '"confidence": "high", "evidence": [], "supporting_papers": [], '
    '"missing_connection": "", "why_important": ""}]'
)


class ValidResponseTests(unittest.TestCase):
    def test_valid_json_on_first_try_returns_gaps_without_retry(self):
        client = MagicMock()
        client.chat_json.return_value = Success(_VALID_GAPS_JSON)

        gaps = detect_gaps(_wiki(), _graph(), {"domain": "Healthcare AI"}, client)

        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["title"], "Gap One")
        self.assertEqual(gaps[0]["validation_status"], "pending")
        self.assertEqual(client.chat_json.call_count, 1)

    def test_markdown_fenced_json_parses_without_retry(self):
        client = MagicMock()
        client.chat_json.return_value = Success(f"```json\n{_VALID_GAPS_JSON}\n```")

        gaps = detect_gaps(_wiki(), _graph(), {"domain": "Healthcare AI"}, client)

        self.assertEqual(len(gaps), 1)
        self.assertEqual(client.chat_json.call_count, 1)

    def test_genuine_empty_list_is_not_treated_as_parse_failure(self):
        # A literal `[]` response is a valid, parseable, genuinely-empty
        # result -- must NOT trigger a retry or raise.
        client = MagicMock()
        client.chat_json.return_value = Success("[]")

        gaps = detect_gaps(_wiki(), _graph(), {"domain": "Healthcare AI"}, client)

        self.assertEqual(gaps, [])
        self.assertEqual(client.chat_json.call_count, 1)


class ParseFailureRetryTests(unittest.TestCase):
    def test_malformed_response_retries_once_and_recovers(self):
        client = MagicMock()
        client.chat_json.side_effect = [
            Success("this is not json at all, no brackets"),
            Success(_VALID_GAPS_JSON),
        ]

        gaps = detect_gaps(_wiki(), _graph(), {"domain": "Healthcare AI"}, client)

        self.assertEqual(len(gaps), 1)
        self.assertEqual(client.chat_json.call_count, 2)

    def test_malformed_response_on_both_attempts_raises_GapDetectionError(self):
        client = MagicMock()
        client.chat_json.side_effect = [
            Success("garbage one"),
            Success("garbage two"),
        ]

        with self.assertRaises(GapDetectionError) as ctx:
            detect_gaps(_wiki(), _graph(), {"domain": "Healthcare AI"}, client)

        self.assertEqual(client.chat_json.call_count, 2)
        self.assertIn("garbage two", ctx.exception.raw_response_preview)

    def test_empty_string_response_counts_as_parse_failure_not_genuine_empty(self):
        client = MagicMock()
        client.chat_json.side_effect = [Success(""), Success("")]

        with self.assertRaises(GapDetectionError):
            detect_gaps(_wiki(), _graph(), {"domain": "Healthcare AI"}, client)

        self.assertEqual(client.chat_json.call_count, 2)

    def test_object_instead_of_list_is_a_parse_failure(self):
        # A syntactically valid JSON *object* (not a list) must still count
        # as a parse failure for this stage's purposes, not silently unwrap.
        client = MagicMock()
        client.chat_json.side_effect = [
            Success('{"title": "not a list"}'),
            Success(_VALID_GAPS_JSON),
        ]

        gaps = detect_gaps(_wiki(), _graph(), {"domain": "Healthcare AI"}, client)

        self.assertEqual(len(gaps), 1)
        self.assertEqual(client.chat_json.call_count, 2)


if __name__ == "__main__":
    unittest.main()
