"""
Tests for Clinova Phase 1 Stories 1.1.3-1.1.4: pipeline/extraction_reconciler.py
combines independent PyMuPDF and Docling extractions into one canonical
representation with every candidate value retained, and recovers a DOI via
a scoped LLM call only when both deterministic parsers fail to find one.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import Success
from pipeline.extraction_reconciler import reconcile_paper, recover_doi_via_llm


def _pymupdf(full_text="", tables=None):
    return {"full_text": full_text, "char_count": len(full_text), "tables": tables or []}


def _docling(full_text="", tables=None):
    return {"full_text": full_text, "char_count": len(full_text), "tables": tables or []}


class FullTextReconciliationTests(unittest.TestCase):
    def test_prefers_longer_extraction_as_canonical(self):
        result = reconcile_paper(_pymupdf("short"), _docling("a much longer extraction of the same paper"), "p.pdf")

        field = result["fields"]["full_text"]
        self.assertEqual(field["source"], "docling")
        self.assertEqual(field["value"], "a much longer extraction of the same paper")
        # both candidates retained even though pymupdf lost
        self.assertEqual(field["candidates"][0]["source"], "pymupdf")
        self.assertEqual(field["candidates"][0]["char_count"], 5)

    def test_both_empty_gives_low_confidence_and_no_source(self):
        result = reconcile_paper(_pymupdf(""), _docling(""), "p.pdf")

        field = result["fields"]["full_text"]
        self.assertEqual(field["confidence"], "low")
        self.assertEqual(field["source"], "none")

    def test_similar_length_extractions_are_high_confidence(self):
        result = reconcile_paper(_pymupdf("x" * 1000), _docling("x" * 1000), "p.pdf")
        self.assertEqual(result["fields"]["full_text"]["confidence"], "high")

    def test_large_length_divergence_is_medium_confidence(self):
        # docling extracted 10x more content than pymupdf -- real disagreement
        result = reconcile_paper(_pymupdf("x" * 100), _docling("x" * 1000), "p.pdf")
        self.assertEqual(result["fields"]["full_text"]["confidence"], "medium")


class DoiReconciliationTests(unittest.TestCase):
    def test_both_parsers_agree_gives_high_confidence(self):
        text = "Published as 10.1038/s41598-026-35440-6 in Nature."
        result = reconcile_paper(_pymupdf(text), _docling(text), "p.pdf")

        field = result["fields"]["doi"]
        self.assertEqual(field["value"], "10.1038/s41598-026-35440-6")
        self.assertEqual(field["confidence"], "high")
        self.assertEqual(field["source"], "both")
        self.assertFalse(field["needs_llm_recovery"])

    def test_only_one_parser_finds_doi_gives_medium_confidence(self):
        result = reconcile_paper(
            _pymupdf("no doi visible here"),
            _docling("DOI: 10.1016/j.neuroimage.2020.01234"),
            "p.pdf",
        )

        field = result["fields"]["doi"]
        self.assertEqual(field["value"], "10.1016/j.neuroimage.2020.01234")
        self.assertEqual(field["confidence"], "medium")
        self.assertEqual(field["source"], "docling")
        self.assertFalse(field["needs_llm_recovery"])

    def test_pymupdf_longer_candidate_wins_when_disagreeing(self):
        # Symmetric case to the truncation test -- the "prefer longer" rule
        # must not be hardcoded to always favor docling.
        result = reconcile_paper(
            _pymupdf("doi 10.1016/j.neuroimage.2020.117123 full"),
            _docling("doi 10.1016/j.neuroimage.2020.117"),  # truncated
            "p.pdf",
        )
        field = result["fields"]["doi"]
        self.assertEqual(field["value"], "10.1016/j.neuroimage.2020.117123")
        self.assertEqual(field["source"], "pymupdf")
        self.assertEqual(field["confidence"], "medium")

    def test_two_genuinely_different_dois_prefers_earliest_position(self):
        # Live-validated on real data (AuDHD_1.pdf): the paper's own DOI
        # appears in front matter (early), an unrelated OSF data-repository
        # DOI appears in a "Data Availability" statement near the end.
        # Neither is a truncation of the other -- position, not length,
        # is the correct disambiguating signal.
        pymupdf_text = "10.1038/s41598-026-35440-6 " + ("x" * 40000)
        docling_text = ("y" * 47000) + " Scripts available at 10.17605/OSF.IO/DZVMG. " + ("z" * 18000)
        result = reconcile_paper(_pymupdf(pymupdf_text), _docling(docling_text), "p.pdf")

        field = result["fields"]["doi"]
        self.assertEqual(field["value"], "10.1038/s41598-026-35440-6")
        self.assertEqual(field["source"], "pymupdf")
        self.assertEqual(field["confidence"], "medium")
        # both real candidates stay visible, including the rejected one
        doi_values = {c["source"]: c["value"] for c in field["candidates"]}
        self.assertEqual(doi_values["docling"], "10.17605/OSF.IO/DZVMG")

    def test_neither_parser_finds_doi_flags_llm_recovery_needed(self):
        result = reconcile_paper(_pymupdf("nothing here"), _docling("nothing here either"), "p.pdf")

        field = result["fields"]["doi"]
        self.assertIsNone(field["value"])
        self.assertEqual(field["confidence"], "low")
        self.assertTrue(field["needs_llm_recovery"])

    def test_truncated_doi_in_one_source_recovered_from_the_other(self):
        # Direct regression case for the real Phase 0 finding
        # (case-truncated-doi.json): one extraction path truncated the DOI
        # mid-word (the `\b` pattern backtracks off a trailing hyphen with
        # nothing after it, matching only "10.3233/jad"), but the other
        # captured it intact -- reconciliation must prefer the longer,
        # intact candidate rather than silently keeping the truncated one.
        truncated_text = "See ref [12], doi 10.3233/jad-"
        intact_text = "See ref [12], doi 10.3233/jad-219876 for details."
        result = reconcile_paper(_pymupdf(truncated_text), _docling(intact_text), "p.pdf")

        field = result["fields"]["doi"]
        self.assertEqual(field["value"], "10.3233/jad-219876")
        self.assertEqual(field["source"], "docling")
        self.assertEqual(field["confidence"], "medium")  # genuine disagreement, not a clean match
        # both raw candidates stay visible even though one lost
        self.assertEqual(field["candidates"][0]["value"], "10.3233/jad")


class TableReconciliationTests(unittest.TestCase):
    def test_prefers_docling_tables_when_present(self):
        result = reconcile_paper(
            _pymupdf(tables=[{"page": 1, "content": "a", "rows": 2, "cols": 2}]),
            _docling(tables=[{"page": 1, "content": "b", "rows": 3, "cols": 3}]),
            "p.pdf",
        )
        field = result["fields"]["tables"]
        self.assertEqual(field["source"], "docling")
        self.assertEqual(field["value"][0]["content"], "b")
        self.assertEqual(field["candidates"][0]["count"], 1)  # pymupdf candidate still recorded

    def test_falls_back_to_pymupdf_tables_when_docling_found_none(self):
        result = reconcile_paper(
            _pymupdf(tables=[{"page": 1, "content": "a", "rows": 2, "cols": 2}]),
            _docling(tables=[]),
            "p.pdf",
        )
        field = result["fields"]["tables"]
        self.assertEqual(field["source"], "pymupdf")
        self.assertEqual(field["confidence"], "medium")

    def test_no_tables_from_either_parser(self):
        result = reconcile_paper(_pymupdf(), _docling(), "p.pdf")
        field = result["fields"]["tables"]
        self.assertEqual(field["value"], [])
        self.assertEqual(field["confidence"], "low")


class DoiDisambiguationLengthGateTests(unittest.TestCase):
    """Regression cases for the different-DOI disambiguation heuristic.
    Position fractions are measured against each text's OWN length, so
    they are only meaningful when the two extractions are comparable in
    size (the same 0.7 ratio the full_text confidence uses). A heavily
    truncated extraction's fractions are stretched toward 1.0 and must not
    be compared directly against a full extraction's fractions."""

    def test_truncated_pymupdf_unrelated_doi_loses_to_full_docling(self):
        # pymupdf: 1000 chars, unrelated DOI at fraction ~0.9 (abs ~905)
        pymupdf_text = ("p" * 900) + " doi 10.5555/unrelated-doi " + ("p" * 73)
        # docling: 50000 chars, the paper's own DOI at fraction ~0.01 (abs ~505)
        docling_text = ("d" * 500) + " doi 10.1234/true-doi " + ("d" * 49478)

        result = reconcile_paper(_pymupdf(pymupdf_text), _docling(docling_text), "p.pdf")

        field = result["fields"]["doi"]
        self.assertEqual(field["value"], "10.1234/true-doi")
        self.assertEqual(field["source"], "docling")
        self.assertEqual(field["confidence"], "medium")

    def test_comparable_lengths_still_use_position_order(self):
        # Lengths within 0.7 of each other -- the earliest-fraction rule
        # applies unchanged.
        pymupdf_text = "10.1111/own-doi " + ("x" * 4000)
        docling_text = ("y" * 3000) + " 10.2222/other-doi " + ("y" * 1000)

        result = reconcile_paper(_pymupdf(pymupdf_text), _docling(docling_text), "p.pdf")

        field = result["fields"]["doi"]
        self.assertEqual(field["value"], "10.1111/own-doi")
        self.assertEqual(field["source"], "pymupdf")


class DoiLlmRecoveryTests(unittest.TestCase):
    def test_recovery_skipped_when_doi_already_resolved(self):
        text = "10.1038/s41598-026-35440-6"
        result = reconcile_paper(_pymupdf(text), _docling(text), "p.pdf")
        client = MagicMock()

        recovered = recover_doi_via_llm(result, client)

        client.chat.assert_not_called()
        self.assertEqual(recovered["fields"]["doi"]["source"], "both")

    def test_recovery_succeeds_with_valid_doi_response(self):
        result = reconcile_paper(_pymupdf("no doi text"), _docling("no doi text"), "p.pdf")
        client = MagicMock()
        client.chat.return_value = Success("10.1234/recovered.doi")

        recovered = recover_doi_via_llm(result, client)

        field = recovered["fields"]["doi"]
        self.assertEqual(field["value"], "10.1234/recovered.doi")
        self.assertEqual(field["source"], "llm_recovery")
        self.assertFalse(field["needs_llm_recovery"])
        client.chat.assert_called_once()

    def test_recovery_handles_none_response_leaves_unresolved(self):
        result = reconcile_paper(_pymupdf("no doi text"), _docling("no doi text"), "p.pdf")
        client = MagicMock()
        client.chat.return_value = Success("NONE")

        recovered = recover_doi_via_llm(result, client)

        field = recovered["fields"]["doi"]
        self.assertIsNone(field["value"])
        self.assertTrue(field["needs_llm_recovery"])

    def test_recovery_rejects_malformed_llm_response(self):
        # LLM ignores the instruction and returns prose instead of a DOI or
        # NONE -- must not corrupt the field with garbage.
        result = reconcile_paper(_pymupdf("no doi text"), _docling("no doi text"), "p.pdf")
        client = MagicMock()
        client.chat.return_value = Success("I could not find a DOI in this text.")

        recovered = recover_doi_via_llm(result, client)

        field = recovered["fields"]["doi"]
        self.assertIsNone(field["value"])
        self.assertTrue(field["needs_llm_recovery"])

    def test_recovery_skipped_when_no_text_to_recover_from(self):
        result = reconcile_paper(_pymupdf(""), _docling(""), "p.pdf")
        client = MagicMock()

        recover_doi_via_llm(result, client)

        client.chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
