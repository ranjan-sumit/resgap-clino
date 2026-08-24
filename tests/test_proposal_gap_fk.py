"""
Tests for Clinova Phase 4, Epic 4.4's Scientific Lineage plumbing in
pipeline/proposal_generator.py: _resolve_addresses_gap() turns the LLM's
free-text/copied gap reference into a validated addresses_gap_id, via
three-way resolution (exact gap_ref -> title match -> honest unresolved).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import Success
from pipeline.proposal_generator import generate_proposals, _resolve_addresses_gap


def _wiki():
    return {"pages": [{"title": "Paper One", "methods": [], "datasets": [], "contributions": []}]}


class ResolveAddressesGapUnitTests(unittest.TestCase):
    def test_exact_gap_ref_match(self):
        gaps = [{"gap_id": "abc123def4567890", "title": "Gap One"}]
        proposals = [{"addresses_gap_ref": "abc123def456", "addresses_gap": "something else entirely"}]
        _resolve_addresses_gap(proposals, gaps)
        self.assertEqual(proposals[0]["addresses_gap_id"], "abc123def4567890")
        self.assertEqual(proposals[0]["addresses_gap_id_resolution"], "llm_exact")

    def test_title_exact_match_when_ref_missing(self):
        gaps = [{"gap_id": "gap-id-1", "title": "Gap One"}]
        proposals = [{"addresses_gap": "Gap One"}]
        _resolve_addresses_gap(proposals, gaps)
        self.assertEqual(proposals[0]["addresses_gap_id"], "gap-id-1")
        self.assertEqual(proposals[0]["addresses_gap_id_resolution"], "title_match")

    def test_title_fuzzy_match(self):
        gaps = [{"gap_id": "gap-id-1", "title": "Missing calibration assessment in this corpus"}]
        proposals = [{"addresses_gap": "Missing calibration assessment"}]
        _resolve_addresses_gap(proposals, gaps)
        self.assertEqual(proposals[0]["addresses_gap_id"], "gap-id-1")
        self.assertEqual(proposals[0]["addresses_gap_id_resolution"], "title_match")

    def test_unrelated_reference_is_honestly_unresolved(self):
        gaps = [{"gap_id": "gap-id-1", "title": "Gap One"}]
        proposals = [{"addresses_gap": "Something totally unrelated and different"}]
        _resolve_addresses_gap(proposals, gaps)
        self.assertIsNone(proposals[0]["addresses_gap_id"])
        self.assertEqual(proposals[0]["addresses_gap_id_resolution"], "unresolved")

    def test_bad_gap_ref_falls_back_to_title_match(self):
        gaps = [{"gap_id": "gap-id-1", "title": "Gap One"}]
        proposals = [{"addresses_gap_ref": "totally-wrong", "addresses_gap": "Gap One"}]
        _resolve_addresses_gap(proposals, gaps)
        self.assertEqual(proposals[0]["addresses_gap_id"], "gap-id-1")
        self.assertEqual(proposals[0]["addresses_gap_id_resolution"], "title_match")

    def test_no_gaps_at_all_is_unresolved_not_a_crash(self):
        proposals = [{"addresses_gap": "Gap One"}]
        _resolve_addresses_gap(proposals, [])
        self.assertIsNone(proposals[0]["addresses_gap_id"])
        self.assertEqual(proposals[0]["addresses_gap_id_resolution"], "unresolved")


class GenerateProposalsIntegrationTests(unittest.TestCase):
    def test_end_to_end_resolves_via_title_match_without_llm_supplying_ref(self):
        """The exact regression case from the plan: a mock response that
        supplies addresses_gap (title text) but not addresses_gap_ref must
        still resolve, landing in the title_match branch."""
        client = MagicMock()
        proposal_json = (
            '[{"title": "P", "problem_statement": "p", "methodology": "m", '
            '"novelty": "n", "builds_on": [], "addresses_gap": "Gap One", '
            '"expected_contribution": "c", "suggested_experiments": [], '
            '"potential_datasets": [], "confidence": "medium", '
            '"effort_estimate": "short (1-3 months)", "risk": "low"}]'
        )
        client.chat_json.return_value = Success(proposal_json)
        gaps = [{"gap_id": "real-gap-id-1", "title": "Gap One", "description": "d", "validation_status": "open"}]

        proposals = generate_proposals(gaps, _wiki(), {"domain": "Healthcare AI"}, client)

        self.assertEqual(proposals[0]["addresses_gap_id"], "real-gap-id-1")
        self.assertEqual(proposals[0]["addresses_gap_id_resolution"], "title_match")


if __name__ == "__main__":
    unittest.main()
