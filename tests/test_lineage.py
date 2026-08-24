"""
Tests for pipeline/lineage.py (Clinova Phase 4, Epic 4.4, FR-24). Runs
against a real, isolated Postgres schema per test class (see
tests/pg_test_utils.py), same convention as tests/test_database_registry.py.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from tests.pg_test_utils import new_test_schema, drop_test_schema
from pipeline.lineage import (
    get_scientific_lineage,
    get_technical_lineage,
    record_run_lineage,
    trace_artifact_ancestry,
    trace_artifact_descendants,
)


class _IsolatedSchemaTestCase(unittest.TestCase):
    def setUp(self):
        self.schema = new_test_schema()
        self.patcher = patch.object(db, "_SCHEMA", self.schema)
        self.patcher.start()
        db.init_db()

    def tearDown(self):
        self.patcher.stop()
        drop_test_schema(self.schema)


_PAPERS = [
    {"filename": "AuDHD_1.pdf", "char_count": 1000},
    {"filename": "AuDHD_2.pdf", "char_count": 1200},
]
_WIKI = {"pages": [{"source_file": "AuDHD_1.pdf"}, {"source_file": "AuDHD_2.pdf"}]}
_EVIDENCE = {
    "AuDHD_1.pdf": [{"evidence_id": "ev1", "provenance": {"page": 3}}],
    "AuDHD_2.pdf": [{"evidence_id": "ev2", "provenance": {"page": None}}],
}
_GRAPH = {
    "entities": [{"id": "e1", "name": "Entity One"}],
    "relationships": [{"relationship_id": "r1", "source": "e1", "target": "e1"}],
    "stats": {"entity_count": 1, "relationship_count": 1},
    "diagnostics": {"used_fallback": False},
}
_GAPS = [{
    "gap_id": "g1", "title": "Gap One", "source": "deterministic",
    "evidence_basis": "positive_evidence",
    "motivating_evidence_ids": ["ev1"], "motivating_relationship_ids": ["r1"],
    "motivating_entity_ids": ["e1"],
}]
_PROPOSALS = [{"title": "Proposal One", "addresses_gap_id": "g1"}]


class RecordRunLineageTests(_IsolatedSchemaTestCase):
    def test_full_spine_recorded_in_order(self):
        result = record_run_lineage(
            run_id="run1", project_id="proj1", papers=_PAPERS, wiki=_WIKI,
            ref_papers=[], evidence_objects=_EVIDENCE, graph=_GRAPH,
            gaps=_GAPS, proposals=_PROPOSALS,
        )
        self.assertEqual(result["skipped"], [])
        for t in ("corpus", "evidence_set", "graph", "gap_set", "proposal_set"):
            self.assertIn(t, result["by_type"])
        # 1 corpus + 2 paper_extraction + evidence_set + graph + gap_set + proposal_set
        self.assertEqual(len(result["artifact_ids"]), 7)

    def test_reference_set_only_written_when_ref_papers_present(self):
        result = record_run_lineage(
            run_id="run2", project_id="proj1", papers=_PAPERS, wiki=_WIKI,
            ref_papers=[{"title": "ref"}], evidence_objects=_EVIDENCE,
            graph=_GRAPH, gaps=_GAPS, proposals=_PROPOSALS,
        )
        self.assertIn("reference_set", result["by_type"])

    def test_gate_blocked_truncates_after_evidence_set(self):
        result = record_run_lineage(
            run_id="run3", project_id="proj1", papers=_PAPERS, wiki=_WIKI,
            ref_papers=[], evidence_objects=_EVIDENCE, graph=None,
            gaps=None, proposals=None, gate_blocked=True,
        )
        self.assertEqual(sorted(result["skipped"]), ["gap_set", "graph", "proposal_set"])
        self.assertNotIn("graph", result["by_type"])
        evidence_set = db.get_artifact(result["by_type"]["evidence_set"])
        self.assertIn("chain_truncated_reason", evidence_set["metadata"])

    def test_parent_artifact_chain_is_correct(self):
        result = record_run_lineage(
            run_id="run4", project_id="proj1", papers=_PAPERS, wiki=_WIKI,
            ref_papers=[], evidence_objects=_EVIDENCE, graph=_GRAPH,
            gaps=_GAPS, proposals=_PROPOSALS,
        )
        graph_row = db.get_artifact(result["by_type"]["graph"])
        self.assertEqual(graph_row["parent_artifact"], result["by_type"]["evidence_set"])
        gap_set_row = db.get_artifact(result["by_type"]["gap_set"])
        self.assertEqual(gap_set_row["parent_artifact"], result["by_type"]["graph"])
        proposal_set_row = db.get_artifact(result["by_type"]["proposal_set"])
        self.assertEqual(proposal_set_row["parent_artifact"], result["by_type"]["gap_set"])

    def test_evidence_set_records_fan_in_parents(self):
        result = record_run_lineage(
            run_id="run5", project_id="proj1", papers=_PAPERS, wiki=_WIKI,
            ref_papers=[], evidence_objects=_EVIDENCE, graph=_GRAPH,
            gaps=_GAPS, proposals=_PROPOSALS,
        )
        evidence_set = db.get_artifact(result["by_type"]["evidence_set"])
        contributing = evidence_set["metadata"]["contributing_parents"]
        self.assertEqual(len(contributing), 2)


class GetTechnicalLineageTests(_IsolatedSchemaTestCase):
    def test_returns_full_walkable_spine(self):
        record_run_lineage(
            run_id="run6", project_id="proj1", papers=_PAPERS, wiki=_WIKI,
            ref_papers=[], evidence_objects=_EVIDENCE, graph=_GRAPH,
            gaps=_GAPS, proposals=_PROPOSALS,
        )
        lineage = get_technical_lineage("run6")
        self.assertIsNotNone(lineage["root"])
        self.assertEqual(lineage["orphans"], [])
        self.assertEqual(len(lineage["fan_in_edges"]), 2)
        self.assertEqual(len(lineage["nodes"]), 7)

    def test_unknown_run_returns_empty_spine(self):
        lineage = get_technical_lineage("does-not-exist")
        self.assertIsNone(lineage["root"])
        self.assertEqual(lineage["nodes"], [])


class GetScientificLineageTests(_IsolatedSchemaTestCase):
    def test_resolves_real_ids_and_reports_unresolved(self):
        results = {
            "graph": _GRAPH, "evidence_objects": _EVIDENCE,
            "gaps": [
                dict(_GAPS[0]),
                {"gap_id": "g2", "title": "Gap Two", "source": "semantic",
                 "evidence_basis": "positive_evidence",
                 "motivating_evidence_ids": ["ev-does-not-exist"],
                 "motivating_relationship_ids": [], "motivating_entity_ids": []},
            ],
            "proposals": _PROPOSALS, "papers": [], "context": {},
        }
        db.save_run("test-run", results)
        run_id = db.list_runs(limit=1)[0]["id"]

        lineage = get_scientific_lineage(run_id)
        self.assertEqual(len(lineage["gaps"]), 2)

        g1_chain = next(g for g in lineage["gaps"] if g["gap_id"] == "g1")
        self.assertEqual(len(g1_chain["chain"]["evidence"]), 1)
        self.assertEqual(len(g1_chain["chain"]["relationships"]), 1)
        self.assertEqual(g1_chain["unresolved"]["evidence_ids_not_found"], [])
        self.assertEqual(len(g1_chain["chain"]["proposals"]), 1)

        g2_chain = next(g for g in lineage["gaps"] if g["gap_id"] == "g2")
        self.assertEqual(g2_chain["chain"]["evidence"], [])
        self.assertEqual(g2_chain["unresolved"]["evidence_ids_not_found"], ["ev-does-not-exist"])

    def test_unknown_run_raises(self):
        with self.assertRaises(ValueError):
            get_scientific_lineage("does-not-exist")

    def test_gaps_without_gap_id_are_excluded_and_counted(self):
        """Real bug found via live UI verification (2026-08-24): a run
        predating Epic 4.4's identity fields has gaps with no gap_id --
        these must not be rendered with a fabricated/None identity."""
        results = {
            "graph": {}, "evidence_objects": {},
            "gaps": [
                {"title": "Old gap, no gap_id"},  # predates Epic 4.4
                dict(_GAPS[0]),  # has a real gap_id
            ],
            "proposals": [], "papers": [], "context": {},
        }
        db.save_run("test-run-3", results)
        run_id = db.list_runs(limit=1)[0]["id"]

        lineage = get_scientific_lineage(run_id)
        self.assertEqual(lineage["n_gaps_without_identity"], 1)
        self.assertEqual(len(lineage["gaps"]), 1)
        self.assertEqual(lineage["gaps"][0]["gap_id"], "g1")

    def test_gap_id_filter(self):
        results = {"graph": _GRAPH, "evidence_objects": _EVIDENCE, "gaps": _GAPS,
                   "proposals": _PROPOSALS, "papers": [], "context": {}}
        db.save_run("test-run-2", results)
        run_id = db.list_runs(limit=1)[0]["id"]
        lineage = get_scientific_lineage(run_id, gap_id="g1")
        self.assertEqual(len(lineage["gaps"]), 1)


class TraceArtifactTests(_IsolatedSchemaTestCase):
    def test_ancestry_is_root_first(self):
        result = record_run_lineage(
            run_id="run7", project_id="proj1", papers=_PAPERS, wiki=_WIKI,
            ref_papers=[], evidence_objects=_EVIDENCE, graph=_GRAPH,
            gaps=_GAPS, proposals=_PROPOSALS,
        )
        ancestry = trace_artifact_ancestry(result["by_type"]["gap_set"])
        types = [a["artifact_type"] for a in ancestry]
        self.assertEqual(types, ["corpus", "evidence_set", "graph", "gap_set"])

    def test_descendants_of_corpus_include_full_spine(self):
        result = record_run_lineage(
            run_id="run8", project_id="proj1", papers=_PAPERS, wiki=_WIKI,
            ref_papers=[], evidence_objects=_EVIDENCE, graph=_GRAPH,
            gaps=_GAPS, proposals=_PROPOSALS,
        )
        descendants = trace_artifact_descendants(result["by_type"]["corpus"])
        descendant_types = {d["artifact_type"] for d in descendants}
        self.assertIn("proposal_set", descendant_types)
        self.assertIn("graph", descendant_types)

    def test_unknown_artifact_ancestry_is_empty(self):
        self.assertEqual(trace_artifact_ancestry("does-not-exist"), [])

    def test_unknown_artifact_descendants_is_empty(self):
        self.assertEqual(trace_artifact_descendants("does-not-exist"), [])


if __name__ == "__main__":
    unittest.main()
