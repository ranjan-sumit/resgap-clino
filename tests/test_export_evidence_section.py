"""
Tests for Clinova Phase 2, Story 2.2.2: utils/export.py's
to_enterprise_html_report() cites Evidence Objects with their real
provenance, additive to the existing wiki-text-based report content.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.export import to_enterprise_html_report, _evidence_rows


def _base_results(evidence_objects=None):
    return {
        "papers": [{"filename": "p1.pdf", "wiki": {"title": "T", "contributions": [], "limitations": []}}],
        "ref_papers": [], "graph": {"stats": {}, "diagnostics": {}},
        "gaps": [], "proposals": [], "pipeline_trace": [], "ref_diagnostics": {},
        "evidence_objects": evidence_objects,
    }


def _narrative():
    return {"executive_summary": [], "research_objective": "", "corpus_overview": "",
            "knowledge_graph_summary": "", "risk_and_limitations": [], "closing_recommendation": ""}


class EvidenceRowsTests(unittest.TestCase):
    def test_page_and_section_both_present(self):
        rows = _evidence_rows({"p1.pdf": [
            {"evidence_type": "Limitation", "text": "Restricted to European cohorts",
             "provenance": {"page": 4, "section": "Limitations"}, "confidence": "medium"},
        ]})
        self.assertIn("p.4 (Limitations)", rows)
        self.assertIn("Restricted to European cohorts", rows)

    def test_no_page_resolved_shows_dash_honestly(self):
        rows = _evidence_rows({"p1.pdf": [
            {"evidence_type": "Method", "text": "Logistic regression",
             "provenance": {"page": None, "section": None}, "confidence": "medium"},
        ]})
        self.assertIn("<td>—</td>", rows)

    def test_empty_dict_gives_empty_rows(self):
        self.assertEqual(_evidence_rows({}), "")
        self.assertEqual(_evidence_rows(None), "")


class ReportIntegrationTests(unittest.TestCase):
    def test_report_renders_without_crashing_when_no_evidence_present(self):
        # Pre-existing reports (no evidence_objects key, or Quality Engine
        # never ran) must still render -- purely additive, not required.
        html = to_enterprise_html_report(_base_results(evidence_objects=None), {}, narrative=_narrative())
        self.assertIn("<html>", html)
        self.assertNotIn("<h2>Evidence</h2>", html)  # section omitted entirely when nothing to show

    def test_report_includes_evidence_section_when_present(self):
        evidence = {"p1.pdf": [
            {"evidence_type": "Result", "text": "ADHD traits predict internalising symptoms",
             "provenance": {"page": 3, "section": "Results"}, "confidence": "high"},
        ]}
        html = to_enterprise_html_report(_base_results(evidence_objects=evidence), {}, narrative=_narrative())
        self.assertIn("<h2>Evidence</h2>", html)
        self.assertIn("ADHD traits predict internalising symptoms", html)
        self.assertIn("p.3 (Results)", html)

    def test_evidence_text_is_html_escaped(self):
        evidence = {"p1.pdf": [
            {"evidence_type": "Claim", "text": "<script>alert(1)</script>",
             "provenance": {"page": None, "section": None}, "confidence": "low"},
        ]}
        html = to_enterprise_html_report(_base_results(evidence_objects=evidence), {}, narrative=_narrative())
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
