"""
Tests for Story 1.2: callers unwrap Result and raise LLMCallError on Failure.
Covers the two behaviors that matter most: (1) per-item-loop callers (Group A)
must not let one item's failure abort the whole batch, (2) single-shot callers
(Group C) must let LLMCallError propagate uncaught to their own caller.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import Success, Failure, ErrorInfo, LLMCallError
from pipeline.paper_manager import compile_tier2_batch
from pipeline.gap_detector import detect_gaps


class Group_A_BatchResilienceTests(unittest.TestCase):
    def test_one_failed_reference_does_not_abort_the_tier2_batch(self):
        refs = [
            {"tier": 2, "title": "Paper One", "abstract": "A" * 60, "year": 2020},
            {"tier": 2, "title": "Paper Two", "abstract": "B" * 60, "year": 2021},
            {"tier": 2, "title": "Paper Three", "abstract": "C" * 60, "year": 2022},
        ]

        responses = [
            Success('{"title": "Paper One", "contributions": ["x"]}'),
            Failure(ErrorInfo(kind="rate_limit", detail="429")),
            Success('{"title": "Paper Three", "contributions": ["z"]}'),
        ]
        client = MagicMock()
        client.chat_json.side_effect = responses

        wikis = compile_tier2_batch(refs, client)

        self.assertEqual(len(wikis), 3)  # all three refs produced a result, none crashed the batch
        self.assertEqual(wikis[0]["contributions"], ["x"])
        self.assertEqual(wikis[1]["tier"], 3)               # degraded stub, not a crash
        self.assertEqual(wikis[1]["confidence"], "title_only")
        self.assertEqual(wikis[2]["contributions"], ["z"])  # third ref unaffected by second's failure


class Group_C_PropagationTests(unittest.TestCase):
    def test_detect_gaps_lets_llm_call_error_propagate(self):
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="api_error", detail="connection refused"))

        with self.assertRaises(LLMCallError):
            detect_gaps(
                wiki={"pages": [], "cross_links": {}},
                graph={"communities": [], "orphan_concepts": [], "missing_bridges": []},
                context={"domain": "Test", "interest": "General"},
                client=client,
            )


if __name__ == "__main__":
    unittest.main()
