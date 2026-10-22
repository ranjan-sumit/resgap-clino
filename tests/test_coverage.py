"""paper_coverage: every paper must visibly make it through every stage."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.coverage import paper_coverage, _is_paper


def results(**over):
    base = {
        "papers": [{"filename": "a.pdf", "wiki": {"title": "Airway chip paper for cystic fibrosis", "key_findings": ["f"], "methods": ["m"]}},
                   {"filename": "b.pdf", "wiki": {"title": "A global survey of CF researchers", "key_findings": ["f"]}}],
        "evidence_objects": {"a.pdf": [{"provenance": {"quote": "q"}}, {"provenance": {"quote": None}}],
                             "b.pdf": [{"provenance": {"quote": "q"}}]},
        "paper_profiles": {"a.pdf": {"study_type": "in_vitro_or_lab"}, "b.pdf": {"study_type": "survey_or_questionnaire"}},
        "graph": {"entities": [{"papers": ["Airway chip paper for cystic fibrosis"]},
                               {"papers": ["a.pdf", "A global survey of CF researchers"]}]},
        "gaps": [{"gap_id": "g1", "supporting_papers": ["Airway chip paper for cystic fibrosis"]}],
        "proposals": [{"addresses_gap_id": "g1", "builds_on": []}],
    }
    base.update(over)
    return base


class CoverageTests(unittest.TestCase):
    def test_a_fully_processed_corpus_is_all_ok(self):
        rows = paper_coverage(results())
        self.assertEqual([r["status"] for r in rows], ["ok", "ok"])
        a = rows[0]
        self.assertEqual((a["wiki_items"], a["evidence"], a["quoted"], a["entities"], a["gaps"], a["proposals"]),
                         (2, 2, 1, 2, 1, 1))
        self.assertEqual(a["study_type"], "in_vitro_or_lab")

    def test_papers_are_matched_by_filename_or_title(self):
        rows = paper_coverage(results())
        self.assertEqual(rows[1]["entities"], 1)           # matched through its title in one entity

    def test_an_empty_wiki_page_is_flagged(self):
        r = results()
        r["papers"][1]["wiki"] = {"title": "A global survey of CF researchers"}
        row = paper_coverage(r)[1]
        self.assertEqual(row["status"], "check")
        self.assertIn("empty wiki page", row["problems"])

    def test_missing_evidence_and_unquoted_evidence_are_flagged_differently(self):
        r = results()
        r["evidence_objects"]["b.pdf"] = []
        self.assertIn("no evidence extracted", paper_coverage(r)[1]["problems"])
        r["evidence_objects"]["b.pdf"] = [{"provenance": {"quote": None}}]
        self.assertIn("evidence has no verified quotes", paper_coverage(r)[1]["problems"])

    def test_a_paper_with_no_graph_entities_is_flagged(self):
        r = results(graph={"entities": [{"papers": ["Airway chip paper for cystic fibrosis"]}]})
        self.assertIn("no graph entities", paper_coverage(r)[1]["problems"])

    def test_empty_results_give_no_rows(self):
        self.assertEqual(paper_coverage({}), [])

    def test_matching_is_not_fooled_by_short_or_empty_names(self):
        self.assertFalse(_is_paper("", "a.pdf", "Title"))
        self.assertFalse(_is_paper("CF", "a.pdf", "Cystic fibrosis airway chip"))   # too short to count as a substring match
        self.assertTrue(_is_paper("Cystic fibrosis airway chip", "a.pdf", "Cystic fibrosis airway chip"))
        self.assertTrue(_is_paper("A.PDF", "a.pdf", "x"))


if __name__ == "__main__":
    unittest.main()
