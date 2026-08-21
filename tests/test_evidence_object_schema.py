"""
Tests for Clinova Phase 2, Story 2.1.2: packages/research_schemas/
evidence_object.py's EvidenceObject schema and validate_evidence_dict()
gate used by pipeline/evidence_extractor.py (Story 2.1.4).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packages.research_schemas.evidence_object import (
    EvidenceObject, Provenance, validate_evidence_dict, to_dict, EVIDENCE_TYPES,
)


def _provenance(page=3, section="Limitations"):
    return Provenance(page=page, section=section, text_span=(10, 50))


class EvidenceObjectConstructionTests(unittest.TestCase):
    def test_valid_object_constructs_and_derives_id(self):
        obj = EvidenceObject(
            evidence_type="Limitation", paper_id="paper1",
            text="Analyses were restricted to cohorts of largely European ancestry.",
            provenance=_provenance(), confidence="high",
        )
        self.assertTrue(obj.evidence_id)
        self.assertEqual(len(obj.evidence_id), 64)  # sha256 hex

    def test_same_content_produces_same_evidence_id(self):
        kwargs = dict(evidence_type="Limitation", paper_id="paper1",
                       text="same text", provenance=_provenance(), confidence="high")
        self.assertEqual(EvidenceObject(**kwargs).evidence_id, EvidenceObject(**kwargs).evidence_id)

    def test_different_paper_same_text_produces_different_id(self):
        a = EvidenceObject(evidence_type="Finding", paper_id="paper1", text="x",
                            provenance=_provenance(), confidence="medium")
        b = EvidenceObject(evidence_type="Finding", paper_id="paper2", text="x",
                            provenance=_provenance(), confidence="medium")
        self.assertNotEqual(a.evidence_id, b.evidence_id)

    def test_invalid_evidence_type_raises(self):
        with self.assertRaises(ValueError):
            EvidenceObject(evidence_type="NotARealType", paper_id="p", text="x",
                            provenance=_provenance(), confidence="high")

    def test_invalid_confidence_raises(self):
        with self.assertRaises(ValueError):
            EvidenceObject(evidence_type="Finding", paper_id="p", text="x",
                            provenance=_provenance(), confidence="very high")

    def test_empty_text_raises(self):
        with self.assertRaises(ValueError):
            EvidenceObject(evidence_type="Finding", paper_id="p", text="   ",
                            provenance=_provenance(), confidence="high")

    def test_all_thirteen_evidence_types_are_constructible(self):
        for t in EVIDENCE_TYPES:
            obj = EvidenceObject(evidence_type=t, paper_id="p", text="x",
                                  provenance=_provenance(), confidence="low")
            self.assertEqual(obj.evidence_type, t)
        self.assertEqual(len(EVIDENCE_TYPES), 13)

    def test_provenance_page_can_be_none_honestly(self):
        # Section-only provenance (no Docling page-tagged data available)
        # must be representable, not forced to a fake page number.
        obj = EvidenceObject(evidence_type="Method", paper_id="p", text="x",
                              provenance=Provenance(page=None, section="Methods", text_span=None),
                              confidence="medium")
        self.assertIsNone(obj.provenance.page)


class ToDictTests(unittest.TestCase):
    def test_to_dict_round_trips_all_fields(self):
        obj = EvidenceObject(evidence_type="Result", paper_id="p1", text="finding text",
                              provenance=_provenance(page=5), confidence="high")
        d = to_dict(obj)
        self.assertEqual(d["evidence_type"], "Result")
        self.assertEqual(d["paper_id"], "p1")
        self.assertEqual(d["text"], "finding text")
        self.assertEqual(d["provenance"]["page"], 5)
        self.assertEqual(d["confidence"], "high")
        self.assertEqual(d["evidence_id"], obj.evidence_id)


class ValidateEvidenceDictTests(unittest.TestCase):
    def test_valid_dict_passes(self):
        self.assertTrue(validate_evidence_dict(
            {"evidence_type": "Claim", "confidence": "medium", "text": "a real claim"}
        ))

    def test_missing_text_fails(self):
        self.assertFalse(validate_evidence_dict({"evidence_type": "Claim", "confidence": "medium"}))

    def test_empty_text_fails(self):
        self.assertFalse(validate_evidence_dict(
            {"evidence_type": "Claim", "confidence": "medium", "text": "   "}
        ))

    def test_invalid_evidence_type_fails(self):
        self.assertFalse(validate_evidence_dict(
            {"evidence_type": "MadeUpType", "confidence": "medium", "text": "x"}
        ))

    def test_invalid_confidence_fails(self):
        self.assertFalse(validate_evidence_dict(
            {"evidence_type": "Claim", "confidence": "super-high", "text": "x"}
        ))

    def test_non_dict_input_fails_not_crashes(self):
        self.assertFalse(validate_evidence_dict("not a dict"))
        self.assertFalse(validate_evidence_dict(None))
        self.assertFalse(validate_evidence_dict(["a", "list"]))


if __name__ == "__main__":
    unittest.main()
