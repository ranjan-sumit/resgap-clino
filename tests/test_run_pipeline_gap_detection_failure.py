"""
Regression guard for pipeline/run_pipeline.py: the gap agents returning
nothing in Stage 4 must not kill the run before save_run -- the run
degrades to the deterministic + graph-structural gap sources only, records
the failure, and still saves (same philosophy as the B23 quality-gate path).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.run_pipeline import RunOptions, run_full_pipeline


def _paper(i):
    return {"filename": f"paper_{i}.pdf", "char_count": 100,
            "sections": {}, "tables": [], "figures": []}


_PAPERS = [("paper_1.pdf", b"%PDF-1.4 fake"), ("paper_2.pdf", b"%PDF-1.4 fake two")]


class GapDetectionFailureTests(unittest.TestCase):
    def setUp(self):
        # The fixtures use fake PDF bytes, so the readability check is stubbed.
        # (Started here: a with-statement may nest at most 20 blocks.)
        _p = patch("pipeline.run_pipeline.check_pdf_readable", return_value=None)
        _p.start()
        self.addCleanup(_p.stop)

    def _run(self, warnings):
        options = RunOptions(provider_key="nvidia", model="test-model")
        with \
            patch("pipeline.run_pipeline.parse_pdf", side_effect=lambda _p, f, **_kw: _paper(f)), \
            patch("pipeline.run_pipeline.build_tree", return_value={"root": {}}), \
            patch("pipeline.run_pipeline.tree_to_summary", return_value="tree"), \
            patch("pipeline.run_pipeline.build_wiki", return_value={
                "pages": [{"title": "p1"}, {"title": "p2"}],
                "cross_links": {"shared_concepts": []}}), \
            patch("pipeline.run_pipeline.build_knowledge_graph", return_value={
                "stats": {"entity_count": 0, "relationship_count": 0}, "communities": []}), \
            patch("pipeline.run_pipeline.score_graph_quality",
                  return_value={"build_status": "ok", "quality_score": 1.0}), \
            patch("pipeline.run_pipeline.detect_deterministic_gaps",
                  return_value=[{"title": "det gap", "confidence": "medium"}]), \
            patch("pipeline.run_pipeline.detect_graph_structural_gaps", return_value=[]), \
            patch("pipeline.run_pipeline.apply_graph_quality_to_gaps", side_effect=lambda g, _q: g), \
            patch("pipeline.run_pipeline.scout_gaps",
                  side_effect=lambda gaps, *_a, **_kw: {"gaps": gaps, "diagnostics": {}}), \
            patch("pipeline.run_pipeline.generate_proposals", return_value=[]), \
            patch("pipeline.run_pipeline.assign_tiers", return_value=[]), \
            patch("pipeline.run_pipeline.corpus_stats", return_value={}), \
            patch("pipeline.run_pipeline.summarise_reference_corpus",
                  return_value={"total": 0, "tier2_abstract": 0, "tier3_title": 0}), \
            patch("pipeline.run_pipeline.extract_evidence_cached", return_value=([], None, None)), \
            patch("pipeline.run_pipeline.save_run", return_value="run-id-123") as mock_save, \
            patch("pipeline.run_pipeline.record_artifact"), \
            patch("pipeline.run_pipeline.record_run_lineage", return_value={"artifact_ids": []}), \
            patch("pipeline.run_pipeline.record_run_manifest"):
            outcome = run_full_pipeline(
                papers=_PAPERS,
                context={"domain": "Healthcare AI"},
                client=MagicMock(),
                options=options,
                warn=warnings.append,
            )
        return outcome, mock_save

    def test_gap_agents_returning_nothing_still_saves_the_run(self):
        warnings = []
        outcome, mock_save = self._run(warnings)
        mock_save.assert_called_once()
        self.assertEqual(outcome.run_id, "run-id-123")
        self.assertFalse(outcome.gate_blocked)

    def test_gap_agents_returning_nothing_falls_back_to_non_llm_gap_sources(self):
        warnings = []
        outcome, _ = self._run(warnings)
        # The deterministic-pattern candidate survives; the LLM source's gaps
        # are absent, not fabricated.
        self.assertEqual(outcome.n_gaps, 1)
        self.assertEqual(outcome.results["gaps"][0]["title"], "det gap")
        # Both papers survive to the saved results (no zip() truncation).
        self.assertEqual(len(outcome.results["papers"]), 2)
        # every stored trace row says how long its step took
        rows = outcome.results["pipeline_trace"]
        self.assertTrue(rows and all(isinstance(r["duration_s"], float) and r["duration_s"] >= 0 for r in rows))

    def test_gap_agents_returning_nothing_records_a_warning(self):
        warnings = []
        self._run(warnings)
        self.assertTrue(any("gap detection" in w.lower() for w in warnings))


if __name__ == "__main__":
    unittest.main()

