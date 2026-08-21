"""
Tests for B19 fix (2026-08-20): generate_proposals() must never call the LLM
with an empty `gaps` list. Before this fix, an empty list flowed straight
into the prompt ("Validated Research Gaps: []") and the LLM fabricated
plausible-sounding proposals anyway -- live-reproduced on a real 3-paper
corpus (see evals/benchmarks/baseline/phase0-findings.md,
zero-gap-silent-fabrication finding). This is the companion fix to
test_gap_detector_parse_retry.py's retry/raise behavior.
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


class EmptyGapsGuardTests(unittest.TestCase):
    def test_empty_gaps_returns_empty_list_without_calling_llm(self):
        client = MagicMock()

        proposals = generate_proposals([], _wiki(), {"domain": "Healthcare AI"}, client)

        self.assertEqual(proposals, [])
        client.chat_json.assert_not_called()


class NonEmptyGapsRegressionTests(unittest.TestCase):
    def test_open_gap_still_generates_proposals_as_before(self):
        client = MagicMock()
        client.chat_json.return_value = Success(_VALID_PROPOSAL_JSON)
        gaps = [{"title": "Gap One", "description": "d", "validation_status": "open"}]

        proposals = generate_proposals(gaps, _wiki(), {"domain": "Healthcare AI"}, client)

        self.assertEqual(len(proposals), 1)
        client.chat_json.assert_called_once()

    def test_all_solved_gaps_still_falls_back_to_using_all_gaps(self):
        # Regression guard: this pre-existing branch (non-empty `gaps`, but
        # none are open/partial) is unaffected by the B19 guard, which only
        # triggers on a genuinely empty input list.
        client = MagicMock()
        client.chat_json.return_value = Success(_VALID_PROPOSAL_JSON)
        gaps = [{"title": "Gap One", "description": "d", "validation_status": "solved"}]

        proposals = generate_proposals(gaps, _wiki(), {"domain": "Healthcare AI"}, client)

        self.assertEqual(len(proposals), 1)
        client.chat_json.assert_called_once()


if __name__ == "__main__":
    unittest.main()
