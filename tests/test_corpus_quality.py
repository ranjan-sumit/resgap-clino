"""
Tests for Clinova Phase 1 Epic 1.2: pipeline/corpus_quality.py scores each
paper's extraction completeness against the 16-field scientific checklist,
aggregates the corpus-level reference-resolution funnel, and enforces a
PASS/DEGRADED/FAIL quality gate before gap analysis is allowed to proceed.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.corpus_quality import (
    score_paper_completeness, compute_corpus_quality, enforce_quality_gate,
    QualityGateBlockedError, FIELD_CHECKLIST,
)


def _wiki_page(**overrides):
    base = {
        "title": "A Real Paper Title", "source_file": "paper.pdf",
        "methods": ["method A"], "datasets": ["dataset X"],
        "key_findings": ["finding 1"], "limitations": ["limitation 1"],
        "future_work": ["future direction 1"],
    }
    base.update(overrides)
    return base


def _reconciled(doi_value="10.1234/example", tables=None):
    return {
        "fields": {
            "doi": {"value": doi_value, "confidence": "high" if doi_value else "low", "source": "both"},
            "tables": {"value": tables or [], "confidence": "high" if tables else "low", "source": "docling"},
        }
    }


class PaperCompletenessTests(unittest.TestCase):
    def test_always_missing_fields_are_not_extracted(self):
        result = score_paper_completeness(_reconciled(), _wiki_page(), ref_count=5, has_figures=True)
        for name in ("authors", "abstract", "introduction", "metrics", "conclusion"):
            self.assertEqual(result["fields"][name]["status"], "not_extracted")

    def test_title_fallback_to_filename_is_not_extracted(self):
        # wiki_compiler falls back to the raw filename when the LLM call
        # fails -- that must not be counted as a genuine title.
        result = score_paper_completeness(
            _reconciled(), _wiki_page(title="paper.pdf", source_file="paper.pdf"), ref_count=5,
        )
        self.assertEqual(result["fields"]["title"]["status"], "not_extracted")

    def test_title_genuinely_extracted_is_present(self):
        result = score_paper_completeness(_reconciled(), _wiki_page(), ref_count=5)
        self.assertEqual(result["fields"]["title"]["status"], "present")

    def test_doi_present_and_empty_cases(self):
        present = score_paper_completeness(_reconciled(doi_value="10.1234/x"), _wiki_page(), ref_count=1)
        self.assertEqual(present["fields"]["doi"]["status"], "present")

        empty = score_paper_completeness(_reconciled(doi_value=None), _wiki_page(), ref_count=1)
        self.assertEqual(empty["fields"]["doi"]["status"], "empty")

    def test_wiki_list_field_empty_when_present_but_empty_list(self):
        result = score_paper_completeness(_reconciled(), _wiki_page(methods=[]), ref_count=1)
        self.assertEqual(result["fields"]["methodology"]["status"], "empty")

    def test_wiki_list_field_not_extracted_when_key_absent(self):
        page = _wiki_page()
        del page["methods"]
        result = score_paper_completeness(_reconciled(), page, ref_count=1)
        self.assertEqual(result["fields"]["methodology"]["status"], "not_extracted")

    def test_references_and_tables_and_figures(self):
        result = score_paper_completeness(
            _reconciled(tables=[{"content": "t"}]), _wiki_page(), ref_count=10, has_figures=True,
        )
        self.assertEqual(result["fields"]["references"]["status"], "present")
        self.assertEqual(result["fields"]["tables"]["status"], "present")
        self.assertEqual(result["fields"]["figures"]["status"], "present")

        empty_result = score_paper_completeness(_reconciled(tables=[]), _wiki_page(), ref_count=0, has_figures=False)
        self.assertEqual(empty_result["fields"]["references"]["status"], "empty")
        self.assertEqual(empty_result["fields"]["tables"]["status"], "empty")
        self.assertEqual(empty_result["fields"]["figures"]["status"], "empty")

    def test_completeness_score_matches_present_count_over_checklist_length(self):
        result = score_paper_completeness(
            _reconciled(tables=[{"content": "t"}]), _wiki_page(), ref_count=5, has_figures=True,
        )
        # present: title, doi, methodology, dataset_population, results,
        # limitations, future_work, references, tables, figures = 10
        self.assertEqual(result["present_count"], 10)
        self.assertEqual(result["total_fields"], len(FIELD_CHECKLIST))
        self.assertAlmostEqual(result["completeness_score"], 10 / 16, places=3)


class CorpusQualityAggregationTests(unittest.TestCase):
    def test_averages_completeness_across_papers(self):
        scores = [{"completeness_score": 0.5}, {"completeness_score": 0.9}]
        metrics = compute_corpus_quality(scores, {})
        self.assertAlmostEqual(metrics["extraction_completeness"], 0.7, places=3)

    def test_empty_paper_list_gives_zero_completeness_not_crash(self):
        metrics = compute_corpus_quality([], {})
        self.assertEqual(metrics["extraction_completeness"], 0.0)
        self.assertEqual(metrics["n_papers"], 0)

    def test_reference_funnel_maps_real_diagnostics_shape(self):
        # Real shape from pipeline/reference_extractor.py's diagnostics dict
        diagnostics = {
            "raw_entries": 270, "structured_entries": 90, "fallback_entries": 8,
            "doi_entries": 60, "enriched": 76, "title_only": 6, "duplicates_skipped": 4,
        }
        metrics = compute_corpus_quality([{"completeness_score": 0.6}], diagnostics)
        funnel = metrics["reference_funnel"]
        self.assertEqual(funnel["detected"], 270)
        self.assertEqual(funnel["parsed"], 90)
        self.assertEqual(funnel["resolved"], 82)  # enriched + title_only
        self.assertEqual(funnel["unresolved"], 8)  # 90 - 82
        self.assertEqual(funnel["duplicates_merged_in_run"], 4)
        self.assertEqual(funnel["quarantined"], 0)  # honest -- no status model yet (Epic 1.3)

    def test_doi_resolution_rate_computed_from_actual_reference_records(self):
        # Regression case: an earlier implementation divided ref_diagnostics'
        # doi_entries by structured_entries, which are NOT numerator/
        # denominator of the same fraction (doi_entries counts raw
        # DOI-pattern matches added on top of structured_entries during
        # combined-list construction, not a subset of it) -- this produced
        # a rate greater than 1.0 when first run against real data
        # (Data-17072026/, 2026-08-21). The correct source is the actual
        # resolved reference records.
        ref_papers = [{"doi": "10.1/a"}, {"doi": "10.1/b"}, {"doi": ""}, {"title": "no doi"}]
        metrics = compute_corpus_quality([{"completeness_score": 0.6}], {}, ref_papers=ref_papers)
        self.assertEqual(metrics["doi_resolution_rate"], 0.5)  # 2 of 4 have a doi
        self.assertLessEqual(metrics["doi_resolution_rate"], 1.0)

    def test_doi_resolution_rate_zero_when_no_ref_papers_given(self):
        metrics = compute_corpus_quality([{"completeness_score": 0.6}], {})
        self.assertEqual(metrics["doi_resolution_rate"], 0.0)

    def test_high_completeness_and_doi_rate_passes(self):
        ref_papers = [{"doi": f"10.1/{i}"} for i in range(8)] + [{"doi": ""}, {"doi": ""}]
        metrics = compute_corpus_quality([{"completeness_score": 0.8}], {}, ref_papers=ref_papers)
        self.assertEqual(metrics["quality_gate"], "PASS")
        self.assertEqual(metrics["quality_gate_reasons"], [])

    def test_low_completeness_fails(self):
        metrics = compute_corpus_quality([{"completeness_score": 0.1}], {})
        self.assertEqual(metrics["quality_gate"], "FAIL")
        self.assertTrue(len(metrics["quality_gate_reasons"]) > 0)

    def test_medium_completeness_degrades(self):
        ref_papers = [{"doi": f"10.1/{i}"} for i in range(8)] + [{"doi": ""}, {"doi": ""}]
        metrics = compute_corpus_quality([{"completeness_score": 0.45}], {}, ref_papers=ref_papers)
        self.assertEqual(metrics["quality_gate"], "DEGRADED")

    def test_low_doi_rate_degrades_even_with_good_completeness(self):
        ref_papers = [{"doi": "10.1/a"}] + [{"doi": ""}] * 9  # 10% DOI rate
        metrics = compute_corpus_quality([{"completeness_score": 0.9}], {}, ref_papers=ref_papers)
        self.assertEqual(metrics["quality_gate"], "DEGRADED")
        self.assertTrue(any("DOI" in r for r in metrics["quality_gate_reasons"]))


class QualityGateEnforcementTests(unittest.TestCase):
    def test_fail_without_override_raises(self):
        metrics = {"quality_gate": "FAIL", "quality_gate_reasons": ["extraction completeness too low"]}
        with self.assertRaises(QualityGateBlockedError) as ctx:
            enforce_quality_gate(metrics)
        self.assertIn("extraction completeness too low", str(ctx.exception))

    def test_fail_with_override_proceeds_and_logs(self):
        metrics = {"quality_gate": "FAIL", "quality_gate_reasons": ["too low"]}
        result = enforce_quality_gate(metrics, override=True, override_reason="testing anyway", override_by="researcher_1")
        self.assertTrue(result["gate_override"]["applied"])
        self.assertEqual(result["gate_override"]["reason"], "testing anyway")
        self.assertEqual(result["gate_override"]["by"], "researcher_1")
        self.assertIn("timestamp", result["gate_override"])

    def test_pass_gate_needs_no_override_and_is_unaffected(self):
        metrics = {"quality_gate": "PASS", "quality_gate_reasons": []}
        result = enforce_quality_gate(metrics)
        self.assertNotIn("gate_override", result)

    def test_degraded_gate_proceeds_without_requiring_override(self):
        # Only FAIL blocks by default (PRD FR-3) -- DEGRADED still runs,
        # just with its provenance visible.
        metrics = {"quality_gate": "DEGRADED", "quality_gate_reasons": ["doi rate low"]}
        result = enforce_quality_gate(metrics)
        self.assertEqual(result["quality_gate"], "DEGRADED")
        self.assertNotIn("gate_override", result)


if __name__ == "__main__":
    unittest.main()
