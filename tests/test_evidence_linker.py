"""
Tests for pipeline/evidence_linker.py (Clinova Phase 4, Epic 4.4's
Scientific Lineage plumbing). Pure functions, no DB/API dependency.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.evidence_linker import build_paper_index, match_evidence_ids, resolve_paper_id


class BuildPaperIndexTests(unittest.TestCase):
    def test_indexes_by_title_and_filename(self):
        wiki = {"pages": [{"source_file": "paper1.pdf", "title": "A Study of Things"}]}
        index = build_paper_index(wiki)
        self.assertEqual(index["a study of things"], "paper1.pdf")
        self.assertEqual(index["paper1.pdf"], "paper1.pdf")

    def test_page_without_source_file_skipped(self):
        wiki = {"pages": [{"title": "No filename"}]}
        index = build_paper_index(wiki)
        self.assertEqual(index, {})

    def test_page_without_title_still_indexes_filename(self):
        wiki = {"pages": [{"source_file": "paper2.pdf"}]}
        index = build_paper_index(wiki)
        self.assertEqual(index["paper2.pdf"], "paper2.pdf")


class ResolvePaperIdTests(unittest.TestCase):
    def setUp(self):
        self.index = {"a study of things": "paper1.pdf", "paper1.pdf": "paper1.pdf"}

    def test_exact_normalized_match(self):
        self.assertEqual(resolve_paper_id("A Study of Things", self.index), "paper1.pdf")

    def test_whitespace_and_case_insensitive(self):
        self.assertEqual(resolve_paper_id("  A STUDY   OF THINGS  ", self.index), "paper1.pdf")

    def test_fuzzy_close_match(self):
        self.assertEqual(resolve_paper_id("A Study of Thing", self.index), "paper1.pdf")

    def test_unrelated_title_returns_none(self):
        self.assertIsNone(resolve_paper_id("Completely Different Topic Entirely", self.index))

    def test_empty_ref_returns_none(self):
        self.assertIsNone(resolve_paper_id("", self.index))

    def test_empty_index_returns_none(self):
        self.assertIsNone(resolve_paper_id("anything", {}))


class MatchEvidenceIdsTests(unittest.TestCase):
    def setUp(self):
        self.evidence_objects = {
            "paper1.pdf": [
                {"evidence_id": "ev1", "text": "The model achieves state of the art accuracy on the benchmark dataset."},
                {"evidence_id": "ev2", "text": "Limitations include a small sample size and lack of external validation."},
            ],
            "paper2.pdf": [
                {"evidence_id": "ev3", "text": "A completely unrelated finding about neuroimaging protocols."},
            ],
        }

    def test_scoped_match_finds_real_evidence(self):
        result = match_evidence_ids(
            "state of the art accuracy on the benchmark dataset",
            "paper1.pdf", self.evidence_objects,
        )
        self.assertIn("ev1", result)
        self.assertNotIn("ev2", result)

    def test_no_match_returns_empty_not_a_guess(self):
        result = match_evidence_ids(
            "something entirely unrelated about cooking recipes",
            "paper1.pdf", self.evidence_objects,
        )
        self.assertEqual(result, [])

    def test_corpus_wide_when_paper_id_not_resolvable(self):
        result = match_evidence_ids(
            "completely unrelated finding about neuroimaging protocols",
            None, self.evidence_objects,
        )
        self.assertIn("ev3", result)

    def test_empty_text_returns_empty(self):
        self.assertEqual(match_evidence_ids("", "paper1.pdf", self.evidence_objects), [])

    def test_empty_evidence_objects_returns_empty(self):
        self.assertEqual(match_evidence_ids("some text here", "paper1.pdf", {}), [])

    def test_respects_max_matches_cap(self):
        many = {"p.pdf": [
            {"evidence_id": f"ev{i}", "text": "shared common overlapping tokens dataset accuracy benchmark"}
            for i in range(10)
        ]}
        result = match_evidence_ids("shared common overlapping tokens dataset accuracy benchmark", "p.pdf", many)
        self.assertLessEqual(len(result), 3)

    def test_unresolvable_paper_id_falls_back_to_corpus_wide(self):
        result = match_evidence_ids(
            "state of the art accuracy on the benchmark dataset",
            "paper-not-in-dict.pdf", self.evidence_objects,
        )
        self.assertIn("ev1", result)


if __name__ == "__main__":
    unittest.main()
