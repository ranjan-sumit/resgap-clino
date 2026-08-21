"""
Tests for Clinova Phase 2, Epic 2.1, Stories 2.1.3-2.1.4:
pipeline/evidence_extractor.py.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import Success, Failure, ErrorInfo
from pipeline.evidence_extractor import (
    extract_deterministic_evidence, extract_llm_evidence, extract_evidence,
    extract_evidence_cached, _build_section_map, _resolve_provenance,
)


def _wiki_page(**overrides):
    base = {
        "title": "AuDHD Brain Charting",
        "contributions": ["Introduces normative centile scores for AuDHD"],
        "methods": ["Binary logistic regression"],
        "datasets": ["UK Biobank imaging cohort"],
        "key_findings": ["Centile scores predict internalising symptoms"],
        "limitations": ["Restricted to European ancestry cohorts"],
        "future_work": ["Prospective longitudinal imaging studies"],
    }
    base.update(overrides)
    return base


def _docling_result(segments):
    return {"text_segments": segments}


class SectionMapTests(unittest.TestCase):
    def test_body_segments_inherit_the_preceding_section_header(self):
        segments = [
            {"text": "Limitations", "page": 4, "label": "section_header"},
            {"text": "Restricted to European ancestry cohorts.", "page": 4, "label": "text"},
            {"text": "Future Work", "page": 5, "label": "section_header"},
            {"text": "Prospective longitudinal imaging studies.", "page": 5, "label": "text"},
        ]
        mapped = _build_section_map(segments)
        self.assertEqual(len(mapped), 2)
        self.assertEqual(mapped[0]["section"], "Limitations")
        self.assertEqual(mapped[0]["page"], 4)
        self.assertEqual(mapped[1]["section"], "Future Work")

    def test_section_headers_themselves_are_excluded_from_output(self):
        segments = [{"text": "Methods", "page": 2, "label": "section_header"}]
        self.assertEqual(_build_section_map(segments), [])

    def test_empty_input_returns_empty(self):
        self.assertEqual(_build_section_map([]), [])
        self.assertEqual(_build_section_map(None), [])


class ResolveProvenanceTests(unittest.TestCase):
    def test_exact_substring_match_resolves_real_page(self):
        mapped = [{"text": "Restricted to European ancestry cohorts, limiting generalizability.",
                   "page": 4, "section": "Limitations"}]
        prov = _resolve_provenance("Restricted to European ancestry cohorts", mapped)
        self.assertEqual(prov.page, 4)
        self.assertEqual(prov.section, "Limitations")

    def test_no_match_gives_honest_none_not_a_guess(self):
        mapped = [{"text": "completely unrelated sentence", "page": 4, "section": "Methods"}]
        prov = _resolve_provenance("Restricted to European ancestry cohorts", mapped)
        self.assertIsNone(prov.page)
        self.assertIsNone(prov.section)

    def test_empty_segments_gives_none(self):
        prov = _resolve_provenance("some quote", [])
        self.assertIsNone(prov.page)

    def test_partial_fragment_match_still_resolves(self):
        # LLM-paraphrased text won't byte-match the source -- an 8-word
        # leading fragment should still find the real segment.
        mapped = [{"text": "the study was restricted to cohorts of largely european ancestry limiting generalizability to other groups",
                   "page": 7, "section": "Limitations"}]
        prov = _resolve_provenance("the study was restricted to cohorts of largely european ancestry", mapped)
        self.assertEqual(prov.page, 7)


class DeterministicExtractionTests(unittest.TestCase):
    def test_each_wiki_field_maps_to_correct_evidence_type(self):
        objects, diag = extract_deterministic_evidence("paper1", _wiki_page())
        types_by_text = {o.text: o.evidence_type for o in objects}
        self.assertEqual(types_by_text["Binary logistic regression"], "Method")
        self.assertEqual(types_by_text["UK Biobank imaging cohort"], "DatasetPopulation")
        self.assertEqual(types_by_text["Centile scores predict internalising symptoms"], "Result")
        self.assertEqual(types_by_text["Restricted to European ancestry cohorts"], "Limitation")
        self.assertEqual(types_by_text["Prospective longitudinal imaging studies"], "FutureWork")
        self.assertEqual(types_by_text["Introduces normative centile scores for AuDHD"], "Claim")

    def test_empty_items_skipped_not_counted_as_attempted(self):
        objects, diag = extract_deterministic_evidence("paper1", _wiki_page(methods=["", "  ", "real method"]))
        method_objs = [o for o in objects if o.evidence_type == "Method"]
        self.assertEqual(len(method_objs), 1)

    def test_missing_wiki_fields_do_not_crash(self):
        objects, diag = extract_deterministic_evidence("paper1", {"title": "x"})
        self.assertEqual(objects, [])
        self.assertEqual(diag["attempted"], 0)

    def test_real_provenance_resolved_when_docling_segments_available(self):
        segments = [
            {"text": "Limitations", "page": 6, "label": "section_header"},
            {"text": "Restricted to European ancestry cohorts, limiting generalizability.",
             "page": 6, "label": "text"},
        ]
        objects, diag = extract_deterministic_evidence(
            "paper1", _wiki_page(), docling_result=_docling_result(segments),
        )
        limitation = next(o for o in objects if o.evidence_type == "Limitation")
        self.assertEqual(limitation.provenance.page, 6)
        self.assertEqual(limitation.provenance.section, "Limitations")
        self.assertEqual(diag["provenance_resolved"], 1)

    def test_no_docling_result_gives_honest_none_page_for_everything(self):
        objects, diag = extract_deterministic_evidence("paper1", _wiki_page(), docling_result=None)
        self.assertTrue(all(o.provenance.page is None for o in objects))
        self.assertEqual(diag["provenance_resolved"], 0)

    def test_diagnostics_counts_are_consistent(self):
        objects, diag = extract_deterministic_evidence("paper1", _wiki_page())
        self.assertEqual(diag["attempted"], diag["accepted"] + diag["rejected"])
        self.assertEqual(diag["accepted"], len(objects))


class LlmEvidenceExtractionTests(unittest.TestCase):
    def test_valid_response_produces_evidence_objects(self):
        client = MagicMock()
        client.chat_json.return_value = Success(
            '[{"evidence_type": "ResearchQuestion", "text": "Does AuDHD have a distinct neural signature?", "confidence": "high"},'
            ' {"evidence_type": "StudyDesign", "text": "Cross-sectional cohort study", "confidence": "medium"}]'
        )
        objects, diag = extract_llm_evidence("paper1", _wiki_page(), None, client)
        self.assertEqual(len(objects), 2)
        self.assertEqual({o.evidence_type for o in objects}, {"ResearchQuestion", "StudyDesign"})
        self.assertEqual(diag["accepted"], 2)
        self.assertFalse(diag["llm_call_failed"])

    def test_llm_call_failure_is_flagged_not_silently_empty(self):
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="rate_limit", detail="429"))
        objects, diag = extract_llm_evidence("paper1", _wiki_page(), None, client)
        self.assertEqual(objects, [])
        self.assertTrue(diag["llm_call_failed"])

    def test_unparseable_response_is_flagged_not_silently_empty(self):
        client = MagicMock()
        client.chat_json.return_value = Success("not json at all")
        objects, diag = extract_llm_evidence("paper1", _wiki_page(), None, client)
        self.assertEqual(objects, [])
        self.assertTrue(diag["llm_call_failed"])

    def test_out_of_scope_evidence_type_in_response_is_rejected(self):
        # The LLM must not smuggle in a Limitation/Method/etc. here --
        # those come from the deterministic path only, to avoid double
        # extraction of the same fact via two different mechanisms.
        client = MagicMock()
        client.chat_json.return_value = Success(
            '[{"evidence_type": "Limitation", "text": "should not appear here", "confidence": "high"}]'
        )
        objects, diag = extract_llm_evidence("paper1", _wiki_page(), None, client)
        self.assertEqual(objects, [])
        self.assertEqual(diag["rejected"], 1)

    def test_missing_confidence_defaults_to_medium(self):
        client = MagicMock()
        client.chat_json.return_value = Success(
            '[{"evidence_type": "Problem", "text": "AuDHD is under-studied"}]'
        )
        objects, diag = extract_llm_evidence("paper1", _wiki_page(), None, client)
        self.assertEqual(objects[0].confidence, "medium")


class CombinedExtractionTests(unittest.TestCase):
    def test_use_llm_false_skips_llm_entirely(self):
        client = MagicMock()
        objects, diag = extract_evidence("paper1", _wiki_page(), client=client, use_llm=False)
        client.chat_json.assert_not_called()
        self.assertIsNone(diag["llm"])
        self.assertGreater(len(objects), 0)  # deterministic half still runs

    def test_client_none_skips_llm_entirely(self):
        objects, diag = extract_evidence("paper1", _wiki_page(), client=None)
        self.assertIsNone(diag["llm"])
        self.assertGreater(len(objects), 0)

    def test_both_halves_combine_when_enabled(self):
        client = MagicMock()
        client.chat_json.return_value = Success(
            '[{"evidence_type": "Problem", "text": "AuDHD is under-studied", "confidence": "high"}]'
        )
        objects, diag = extract_evidence("paper1", _wiki_page(), client=client, use_llm=True)
        self.assertIn("Problem", {o.evidence_type for o in objects})
        self.assertIn("Method", {o.evidence_type for o in objects})
        self.assertIsNotNone(diag["llm"])
        self.assertIsNotNone(diag["deterministic"])


class CachingWrapperTests(unittest.TestCase):
    """Story 2.2.1."""

    @patch("pipeline.evidence_extractor.save_cached_evidence_objects")
    @patch("pipeline.evidence_extractor.get_cached_evidence_objects")
    def test_cache_hit_returns_dicts_without_reextracting(self, mock_get, mock_save):
        cached_dicts = [{"evidence_id": "x", "evidence_type": "Method", "text": "cached"}]
        mock_get.return_value = cached_dicts
        client = MagicMock()

        result, diag, from_cache = extract_evidence_cached("paper1", _wiki_page(), client=client)

        self.assertTrue(from_cache)
        self.assertEqual(result, cached_dicts)
        client.chat_json.assert_not_called()
        mock_save.assert_not_called()

    @patch("pipeline.evidence_extractor.save_cached_evidence_objects")
    @patch("pipeline.evidence_extractor.get_cached_evidence_objects")
    def test_cache_miss_extracts_and_saves_as_dicts(self, mock_get, mock_save):
        mock_get.return_value = None
        client = MagicMock()
        client.chat_json.return_value = Success(
            '[{"evidence_type": "Problem", "text": "AuDHD is under-studied", "confidence": "high"}]'
        )

        result, diag, from_cache = extract_evidence_cached("paper1", _wiki_page(), client=client)

        self.assertFalse(from_cache)
        self.assertGreater(len(result), 0)
        self.assertTrue(all(isinstance(r, dict) for r in result))  # dicts, not EvidenceObject instances
        mock_save.assert_called_once()

    @patch("pipeline.evidence_extractor.save_cached_evidence_objects")
    @patch("pipeline.evidence_extractor.get_cached_evidence_objects")
    def test_llm_call_failure_is_never_cached(self, mock_get, mock_save):
        # AD-2's "never cache a failure" rule -- a transient LLM failure
        # must not permanently freeze a deterministic-only result in place
        # of what should have been a fuller one once the failure clears.
        mock_get.return_value = None
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="rate_limit", detail="429"))

        result, diag, from_cache = extract_evidence_cached("paper1", _wiki_page(), client=client)

        self.assertFalse(from_cache)
        mock_save.assert_not_called()

    @patch("pipeline.evidence_extractor.save_cached_evidence_objects")
    @patch("pipeline.evidence_extractor.get_cached_evidence_objects")
    def test_deterministic_only_mode_is_still_cached(self, mock_get, mock_save):
        # No LLM half at all (use_llm=False) -- not a "failure", a
        # legitimate deterministic-only result, so it IS cached.
        mock_get.return_value = None

        result, diag, from_cache = extract_evidence_cached("paper1", _wiki_page(), use_llm=False)

        mock_save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
