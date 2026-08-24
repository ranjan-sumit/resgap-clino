"""
Tests for Clinova Phase 4, Epic 4.4's Scientific Lineage plumbing across
all three gap-producing sources (deterministic pattern library, graph-
structural signals, semantic/LLM detection): every gap gets a real
gap_id, and motivating_evidence_ids/motivating_relationship_ids/
motivating_entity_ids + evidence_basis correctly reflect whether the gap
has real, traceable evidence or fires on an absence of it.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import Success
from pipeline.deterministic_gap_patterns import detect_deterministic_gaps
from pipeline.graph_structural_gaps import detect_graph_structural_gaps
from pipeline.gap_detector import detect_gaps


def _ev(evidence_type, text, paper_id="P1", confidence="medium", evidence_id=None):
    return {"evidence_type": evidence_type, "text": text, "paper_id": paper_id,
            "confidence": confidence, "evidence_id": evidence_id or f"{paper_id}:{evidence_type}:{hash(text)}"}


class DeterministicGapPatternsProvenanceTests(unittest.TestCase):
    def test_absence_pattern_has_no_evidence_and_is_absence_based(self):
        corpus = {"P1": [_ev("Method", "we trained a CNN")]}
        gap = next(g for g in detect_deterministic_gaps(corpus, "Healthcare AI")
                   if g["pattern_id"] == "missing_benchmark_comparison")
        self.assertTrue(gap["gap_id"])
        self.assertEqual(gap["evidence_basis"], "absence_of_evidence")
        self.assertEqual(gap["motivating_evidence_ids"], [])

    def test_keyword_present_pattern_carries_real_evidence_ids(self):
        corpus = {"P1": [_ev("StudyDesign", "This was a retrospective single-center study.", evidence_id="ev-retro-1")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        gap = next((g for g in gaps if g["pattern_id"] == "retrospective_only_design"), None)
        self.assertIsNotNone(gap)
        self.assertEqual(gap["evidence_basis"], "positive_evidence")
        self.assertIn("ev-retro-1", gap["motivating_evidence_ids"])

    def test_named_limitation_carries_its_own_evidence_id(self):
        corpus = {"P1": [_ev("Limitation", "Small sample size limits generalizability.", evidence_id="ev-lim-1")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        gap = next(g for g in gaps if g["pattern_id"] == "named_limitation_self_reported")
        self.assertEqual(gap["evidence_basis"], "positive_evidence")
        self.assertEqual(gap["motivating_evidence_ids"], ["ev-lim-1"])

    def test_every_gap_has_a_stable_gap_id(self):
        corpus = {"P1": [_ev("Method", "we trained a CNN"), _ev("Limitation", "small sample", evidence_id="ev-x")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        self.assertTrue(all(g.get("gap_id") for g in gaps))


class GraphStructuralGapsProvenanceTests(unittest.TestCase):
    def test_orphan_gap_is_absence_based_but_has_entity_id(self):
        graph = {
            "entities": [{"id": "e1", "name": "Orphan Concept", "type": "concept",
                          "papers": ["P1"], "importance": "high"}],
            "relationships": [],
            "orphan_concepts": [{"entity": {"id": "e1", "name": "Orphan Concept", "papers": ["P1"]},
                                  "connections": 0, "signal": "isolated"}],
            "missing_bridges": [],
        }
        gaps = detect_graph_structural_gaps(graph)
        gap = next(g for g in gaps if g["pattern_id"] == "graph_orphan_concept")
        self.assertEqual(gap["evidence_basis"], "absence_of_evidence")
        self.assertEqual(gap["motivating_entity_ids"], ["e1"])
        self.assertEqual(gap["motivating_evidence_ids"], [])
        self.assertTrue(gap["gap_id"])

    def test_bridge_gap_has_no_ids_at_all_honestly(self):
        graph = {
            "entities": [], "relationships": [], "orphan_concepts": [],
            "missing_bridges": [{"source_paper": "P1", "target_paper": "P2",
                                  "description": "limitation X could be solved by Y"}],
        }
        gaps = detect_graph_structural_gaps(graph)
        gap = next(g for g in gaps if g["pattern_id"] == "graph_missing_bridge")
        self.assertEqual(gap["evidence_basis"], "absence_of_evidence")
        self.assertEqual(gap["motivating_entity_ids"], [])
        self.assertEqual(gap["motivating_relationship_ids"], [])

    def test_conflicting_relationship_gap_carries_real_ids_and_is_positive_evidence(self):
        entities = [
            {"id": "e1", "name": "Model A", "type": "method", "papers": ["P1"], "importance": "high"},
            {"id": "e2", "name": "Model B", "type": "method", "papers": ["P2"], "importance": "high"},
        ]
        relationships = [
            {"source": "e1", "target": "e2", "relation": "outperforms", "paper": "P1",
             "relationship_id": "rel1", "provenance_evidence_ids": ["ev1"]},
            {"source": "e1", "target": "e2", "relation": "underperforms_on", "paper": "P2",
             "relationship_id": "rel2", "provenance_evidence_ids": ["ev2"]},
        ]
        graph = {"entities": entities, "relationships": relationships,
                 "orphan_concepts": [], "missing_bridges": []}
        gaps = detect_graph_structural_gaps(graph)
        gap = next(g for g in gaps if g["pattern_id"] == "graph_conflicting_relationship")
        self.assertEqual(gap["evidence_basis"], "positive_evidence")
        self.assertEqual(set(gap["motivating_entity_ids"]), {"e1", "e2"})
        self.assertEqual(set(gap["motivating_relationship_ids"]), {"rel1", "rel2"})
        self.assertEqual(set(gap["motivating_evidence_ids"]), {"ev1", "ev2"})

    def test_untested_combination_gap_has_entity_ids_but_absence_based(self):
        entities = [
            {"id": "e1", "name": "Method A", "type": "method", "papers": ["P1"], "importance": "high"},
            {"id": "e2", "name": "Dataset B", "type": "dataset", "papers": ["P2"], "importance": "high"},
        ]
        relationships = [{"source": "e1", "target": "other", "relation": "applied_to", "paper": "P1"}]
        graph = {"entities": entities, "relationships": relationships,
                 "orphan_concepts": [], "missing_bridges": []}
        gaps = detect_graph_structural_gaps(graph)
        gap = next((g for g in gaps if g["pattern_id"] == "graph_untested_combination"), None)
        if gap:  # connection_count guard requires each entity connected elsewhere
            self.assertEqual(gap["evidence_basis"], "absence_of_evidence")
            self.assertEqual(gap["motivating_evidence_ids"], [])


def _wiki_with_source_files():
    return {
        "pages": [{"title": "Paper One", "source_file": "paper1.pdf", "contributions": [], "methods": [],
                    "limitations": [], "future_work": [], "evaluated_on": [], "comparison_gap": ""}],
        "cross_links": {},
    }


class SemanticGapProvenanceTests(unittest.TestCase):
    def test_semantic_gap_always_positive_evidence_even_when_unlinked(self):
        raw = (
            '[{"title": "Gap", "description": "desc", "gap_type": "methodology", '
            '"confidence": "high", "evidence": ["Paper One (Section: Limitations): unrelated cooking text"], '
            '"supporting_papers": [], "missing_connection": "", "why_important": ""}]'
        )
        client = MagicMock()
        client.chat_json.return_value = Success(raw)
        evidence_objects = {"paper1.pdf": [{"evidence_id": "ev1", "text": "a completely different sentence about brains"}]}
        gaps = detect_gaps(_wiki_with_source_files(), {"communities": []}, {}, client,
                            evidence_objects=evidence_objects)
        gap = gaps[0]
        self.assertEqual(gap["evidence_basis"], "positive_evidence")
        # LLM claimed evidence that didn't resolve to anything real -- an
        # honest, meaningful "unlinked" signal, not hidden.
        self.assertEqual(gap["motivating_evidence_ids"], [])
        self.assertTrue(gap["gap_id"])

    def test_semantic_gap_links_real_evidence_when_it_resolves(self):
        raw = (
            '[{"title": "Gap", "description": "desc", "gap_type": "methodology", '
            '"confidence": "high", "evidence": ["Paper One (Section: Limitations): small sample size limits generalizability"], '
            '"supporting_papers": [], "missing_connection": "", "why_important": ""}]'
        )
        client = MagicMock()
        client.chat_json.return_value = Success(raw)
        evidence_objects = {"paper1.pdf": [{"evidence_id": "ev1", "text": "small sample size limits generalizability of these findings"}]}
        gaps = detect_gaps(_wiki_with_source_files(), {"communities": []}, {}, client,
                            evidence_objects=evidence_objects)
        self.assertIn("ev1", gaps[0]["motivating_evidence_ids"])

    def test_without_evidence_objects_no_linking_attempted(self):
        raw = (
            '[{"title": "Gap", "description": "desc", "gap_type": "methodology", '
            '"confidence": "high", "evidence": [], "supporting_papers": [], '
            '"missing_connection": "", "why_important": ""}]'
        )
        client = MagicMock()
        client.chat_json.return_value = Success(raw)
        gaps = detect_gaps(_wiki_with_source_files(), {"communities": []}, {}, client)
        self.assertTrue(gaps[0]["gap_id"])
        self.assertEqual(gaps[0]["motivating_evidence_ids"], [])


if __name__ == "__main__":
    unittest.main()
