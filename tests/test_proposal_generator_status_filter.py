"""
Regression tests for generate_proposals()'s actionable-gap fallback: it now
widens to all gaps only when every gap is explicitly marked "solved". Gaps
with a missing/unknown validation_status must not silently pull non-open,
non-partial gaps into the proposal prompt.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import Success
from pipeline.proposal_generator import generate_proposals


def _wiki():
    return {"pages": [{"title": "Paper One", "methods": [], "datasets": [], "contributions": []}]}


_VALID_PROPOSAL_JSON = (
    '[{"title": "Proposal One", "problem_statement": "p", "methodology": "m", '
    '"novelty": "n", "builds_on": [], "addresses_gap": "Gap One", '
    '"expected_contribution": "c", "suggested_experiments": [], '
    '"potential_datasets": [], "confidence": "medium", '
    '"effort_estimate": "short (1-3 months)", "risk": "low"}]'
)


class UnknownStatusGapTests(unittest.TestCase):
    def test_mixed_open_and_unknown_only_sends_open_gaps_to_llm(self):
        client = MagicMock()
        client.chat_json.return_value = Success(_VALID_PROPOSAL_JSON)
        gaps = [
            {"title": "Open Gap", "description": "d", "validation_status": "open"},
            {"title": "Partial Gap", "description": "d", "validation_status": "partial"},
            {"title": "Mystery Gap", "description": "d", "validation_status": "unknown"},
            {"title": "No Status Gap", "description": "d"},
        ]

        proposals = generate_proposals(gaps, _wiki(), {"domain": "Healthcare AI"}, client)

        client.chat_json.assert_called_once()
        user_prompt = client.chat_json.call_args[0][1]
        self.assertIn("Open Gap", user_prompt)
        self.assertIn("Partial Gap", user_prompt)
        self.assertNotIn("Mystery Gap", user_prompt)
        self.assertNotIn("No Status Gap", user_prompt)
        self.assertEqual(len(proposals), 1)

    def test_all_unknown_status_returns_empty_without_calling_llm(self):
        # No open/partial gap exists and not every gap is solved -- there is
        # nothing actionable to propose, and calling the LLM with an empty
        # gap list is exactly the fabrication path the B19 guard blocks.
        client = MagicMock()
        gaps = [{"title": "Mystery Gap", "description": "d", "validation_status": "unknown"}]

        proposals = generate_proposals(gaps, _wiki(), {"domain": "Healthcare AI"}, client)

        self.assertEqual(proposals, [])
        client.chat_json.assert_not_called()


class AllSolvedFallbackTests(unittest.TestCase):
    def test_all_solved_still_falls_back_to_all_gaps(self):
        client = MagicMock()
        client.chat_json.return_value = Success(_VALID_PROPOSAL_JSON)
        gaps = [
            {"title": "Solved One", "description": "d", "validation_status": "solved"},
            {"title": "Solved Two", "description": "d", "validation_status": "solved"},
        ]

        proposals = generate_proposals(gaps, _wiki(), {"domain": "Healthcare AI"}, client)

        client.chat_json.assert_called_once()
        user_prompt = client.chat_json.call_args[0][1]
        self.assertIn("Solved One", user_prompt)
        self.assertIn("Solved Two", user_prompt)
        self.assertEqual(len(proposals), 1)


if __name__ == "__main__":
    unittest.main()
