"""
Tests for packages/research_schemas/gap_identity.py (Clinova Phase 4,
Epic 4.4's Scientific Lineage plumbing). No DB/API dependency -- pure
functions.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packages.research_schemas.gap_identity import attach_gap_identity, compute_gap_id


class ComputeGapIdTests(unittest.TestCase):
    def test_deterministic_same_inputs_same_id(self):
        a = compute_gap_id("semantic", None, "Title", "Description")
        b = compute_gap_id("semantic", None, "Title", "Description")
        self.assertEqual(a, b)

    def test_different_title_different_id(self):
        a = compute_gap_id("semantic", None, "Title A", "Description")
        b = compute_gap_id("semantic", None, "Title B", "Description")
        self.assertNotEqual(a, b)

    def test_none_pattern_id_does_not_crash(self):
        self.assertTrue(compute_gap_id("deterministic", None, "T", "D"))

    def test_missing_fields_handled(self):
        self.assertTrue(compute_gap_id(None, None, None, None))


class AttachGapIdentityTests(unittest.TestCase):
    def test_sets_all_expected_fields(self):
        gap = {"source": "semantic", "title": "T", "description": "D"}
        attach_gap_identity(gap)
        self.assertIn("gap_id", gap)
        self.assertEqual(gap["gap_identity_version"], 1)
        self.assertEqual(gap["evidence_basis"], "positive_evidence")
        self.assertEqual(gap["motivating_evidence_ids"], [])
        self.assertEqual(gap["motivating_relationship_ids"], [])
        self.assertEqual(gap["motivating_entity_ids"], [])

    def test_idempotent_gap_id_unchanged_on_second_call(self):
        gap = {"source": "semantic", "title": "T", "description": "D"}
        attach_gap_identity(gap)
        first_id = gap["gap_id"]
        attach_gap_identity(gap)
        self.assertEqual(gap["gap_id"], first_id)

    def test_gap_id_unchanged_after_confidence_mutation(self):
        """The critical regression this module exists to prevent: gap_id
        must survive apply_graph_quality_to_gaps()-style downstream
        mutation of confidence."""
        gap = {"source": "graph_structural", "title": "T", "description": "D", "confidence": "high"}
        attach_gap_identity(gap)
        first_id = gap["gap_id"]
        gap["confidence"] = "low"  # simulates apply_graph_quality_to_gaps()
        self.assertEqual(compute_gap_id(gap["source"], gap.get("pattern_id"), gap["title"], gap["description"]), first_id)

    def test_gap_id_unchanged_after_validation_status_mutation(self):
        """Simulates validate_gaps() mutating validation_status/
        existing_papers/validation_reasoning in place."""
        gap = {"source": "semantic", "title": "T", "description": "D"}
        attach_gap_identity(gap)
        first_id = gap["gap_id"]
        gap["validation_status"] = "open"
        gap["existing_papers"] = ["some paper"]
        gap["validation_reasoning"] = "reasoning"
        self.assertEqual(gap["gap_id"], first_id)

    def test_custom_evidence_basis(self):
        gap = {"source": "graph_structural", "title": "T", "description": "D"}
        attach_gap_identity(gap, evidence_basis="absence_of_evidence")
        self.assertEqual(gap["evidence_basis"], "absence_of_evidence")

    def test_does_not_overwrite_existing_motivating_ids(self):
        gap = {"source": "semantic", "title": "T", "description": "D",
               "motivating_evidence_ids": ["ev1"]}
        attach_gap_identity(gap)
        self.assertEqual(gap["motivating_evidence_ids"], ["ev1"])

    def test_returns_the_same_gap_dict(self):
        gap = {"source": "semantic", "title": "T", "description": "D"}
        result = attach_gap_identity(gap)
        self.assertIs(result, gap)


if __name__ == "__main__":
    unittest.main()
