"""
Tests for pipeline/graph_structural_gaps.py (Clinova Phase 3, Epic 3.2 --
the graph-structural signal source of the Hybrid Gap Engine, operating on
the existing local LazyGraphRAG-style graph, no Neo4j required).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.graph_structural_gaps import detect_graph_structural_gaps


def _entity(eid, name, etype, papers, importance="high"):
    return {"id": eid, "name": name, "type": etype, "papers": papers, "importance": importance}


def _rel(source, target, relation, paper=""):
    return {"source": source, "target": target, "relation": relation, "paper": paper}


class EmptyGraphTests(unittest.TestCase):
    def test_empty_graph_returns_no_gaps(self):
        self.assertEqual(detect_graph_structural_gaps({}), [])

    def test_graph_with_no_signals_returns_no_gaps(self):
        graph = {"entities": [_entity("e1", "Model A", "model", ["P1"])],
                 "relationships": [], "orphan_concepts": [], "missing_bridges": []}
        self.assertEqual(detect_graph_structural_gaps(graph), [])


class OrphanPromotionTests(unittest.TestCase):
    def test_orphan_concepts_become_tagged_gap_candidates(self):
        graph = {
            "entities": [], "relationships": [],
            "orphan_concepts": [{
                "entity": {"name": "Rare Biomarker X", "papers": ["P1"]},
                "connections": 0,
                "signal": "'Rare Biomarker X' appears in only one paper",
            }],
            "missing_bridges": [],
        }
        gaps = detect_graph_structural_gaps(graph)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["source"], "graph_structural")
        self.assertEqual(gaps[0]["pattern_id"], "graph_orphan_concept")
        self.assertIn("Rare Biomarker X", gaps[0]["title"])


class BridgePromotionTests(unittest.TestCase):
    def test_missing_bridges_become_tagged_gap_candidates(self):
        graph = {
            "entities": [], "relationships": [], "orphan_concepts": [],
            "missing_bridges": [{
                "type": "limitation_bridge",
                "description": "'small sample' in P1 could be addressed by federated pooling from P2",
                "source_paper": "P1", "target_paper": "P2",
            }],
        }
        gaps = detect_graph_structural_gaps(graph)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["pattern_id"], "graph_missing_bridge")
        self.assertEqual(gaps[0]["supporting_papers"], ["P1", "P2"])


class ConflictingRelationshipTests(unittest.TestCase):
    def test_opposite_relations_between_same_pair_across_papers_fires(self):
        entities = [_entity("m1", "Model A", "model", ["P1"]),
                    _entity("d1", "Dataset X", "dataset", ["P1", "P2"])]
        relationships = [
            _rel("m1", "d1", "outperforms", paper="P1"),
            _rel("m1", "d1", "underperforms_on", paper="P2"),
        ]
        graph = {"entities": entities, "relationships": relationships,
                 "orphan_concepts": [], "missing_bridges": []}
        gaps = detect_graph_structural_gaps(graph)
        conflict_gaps = [g for g in gaps if g["pattern_id"] == "graph_conflicting_relationship"]
        self.assertEqual(len(conflict_gaps), 1)
        self.assertIn("Model A", conflict_gaps[0]["title"])
        self.assertIn("Dataset X", conflict_gaps[0]["title"])

    def test_non_contradictory_relations_between_same_pair_does_not_fire(self):
        entities = [_entity("m1", "Model A", "model", ["P1"]),
                    _entity("d1", "Dataset X", "dataset", ["P1", "P2"])]
        relationships = [
            _rel("m1", "d1", "evaluated_on", paper="P1"),
            _rel("m1", "d1", "trained_on", paper="P2"),
        ]
        graph = {"entities": entities, "relationships": relationships,
                 "orphan_concepts": [], "missing_bridges": []}
        gaps = detect_graph_structural_gaps(graph)
        conflict_gaps = [g for g in gaps if g["pattern_id"] == "graph_conflicting_relationship"]
        self.assertEqual(conflict_gaps, [])

    def test_relation_matching_works_by_entity_name_not_only_id(self):
        # LLM-produced relationships sometimes use names instead of ids
        # (graph_builder.py's own existing dual-lookup convention).
        entities = [_entity("m1", "Model A", "model", ["P1"]),
                    _entity("d1", "Dataset X", "dataset", ["P1", "P2"])]
        relationships = [
            _rel("Model A", "Dataset X", "outperforms", paper="P1"),
            _rel("model a", "dataset x", "underperforms_on", paper="P2"),
        ]
        graph = {"entities": entities, "relationships": relationships,
                 "orphan_concepts": [], "missing_bridges": []}
        gaps = detect_graph_structural_gaps(graph)
        conflict_gaps = [g for g in gaps if g["pattern_id"] == "graph_conflicting_relationship"]
        self.assertEqual(len(conflict_gaps), 1)


class UntestedCombinationTests(unittest.TestCase):
    def test_two_disconnected_differently_typed_high_importance_entities_fire(self):
        entities = [
            _entity("m1", "Model A", "model", ["P1"]),
            _entity("d1", "Dataset X", "dataset", ["P2"]),
            _entity("other", "Other Thing", "concept", ["P1"]),
        ]
        relationships = [
            _rel("m1", "other", "evaluated_on", paper="P1"),
            _rel("d1", "other", "trained_on", paper="P2"),
        ]
        graph = {"entities": entities, "relationships": relationships,
                 "orphan_concepts": [], "missing_bridges": []}
        gaps = detect_graph_structural_gaps(graph)
        combo_gaps = [g for g in gaps if g["pattern_id"] == "graph_untested_combination"]
        self.assertEqual(len(combo_gaps), 1)
        self.assertIn("Model A", combo_gaps[0]["title"])
        self.assertIn("Dataset X", combo_gaps[0]["title"])

    def test_entities_already_connected_do_not_fire(self):
        entities = [_entity("m1", "Model A", "model", ["P1"]),
                    _entity("d1", "Dataset X", "dataset", ["P1"])]
        relationships = [_rel("m1", "d1", "evaluated_on", paper="P1")]
        graph = {"entities": entities, "relationships": relationships,
                 "orphan_concepts": [], "missing_bridges": []}
        gaps = detect_graph_structural_gaps(graph)
        self.assertEqual([g for g in gaps if g["pattern_id"] == "graph_untested_combination"], [])

    def test_entities_co_mentioned_in_same_paper_do_not_fire(self):
        entities = [
            _entity("m1", "Model A", "model", ["P1"]),
            _entity("d1", "Dataset X", "dataset", ["P1"]),  # shares P1 with Model A
            _entity("other", "Other Thing", "concept", ["P1"]),
        ]
        relationships = [
            _rel("m1", "other", "evaluated_on", paper="P1"),
            _rel("d1", "other", "trained_on", paper="P1"),
        ]
        graph = {"entities": entities, "relationships": relationships,
                 "orphan_concepts": [], "missing_bridges": []}
        gaps = detect_graph_structural_gaps(graph)
        self.assertEqual([g for g in gaps if g["pattern_id"] == "graph_untested_combination"], [])

    def test_same_type_entities_are_not_a_combination(self):
        entities = [_entity("d1", "Dataset X", "dataset", ["P1"]),
                    _entity("d2", "Dataset Y", "dataset", ["P2"])]
        relationships = []
        graph = {"entities": entities, "relationships": relationships,
                 "orphan_concepts": [], "missing_bridges": []}
        gaps = detect_graph_structural_gaps(graph)
        self.assertEqual([g for g in gaps if g["pattern_id"] == "graph_untested_combination"], [])

    def test_low_importance_entities_are_excluded(self):
        entities = [_entity("m1", "Model A", "model", ["P1"], importance="low"),
                    _entity("d1", "Dataset X", "dataset", ["P2"], importance="low")]
        relationships = [_rel("m1", "x", "evaluated_on", paper="P1"),
                          _rel("d1", "y", "trained_on", paper="P2")]
        graph = {"entities": entities, "relationships": relationships,
                 "orphan_concepts": [], "missing_bridges": []}
        gaps = detect_graph_structural_gaps(graph)
        self.assertEqual([g for g in gaps if g["pattern_id"] == "graph_untested_combination"], [])


class PaperContainerEntityExclusionTests(unittest.TestCase):
    """Real-data regression (found validating against the AuDHD_1/AuDHD_2
    corpus's actual fallback-path graph, 2026-08-21): graph_builder.py's
    _fallback_graph_from_wiki() adds each paper itself as a type="domain"
    entity whose name equals its own papers[0] -- a self-referential
    "container" node, not a domain concept. Left unfiltered this produced
    nonsense gaps like "Untested combination: <full paper title> x Some
    Metric"."""

    def test_paper_container_entity_is_excluded_from_untested_combinations(self):
        entities = [
            _entity("paper1", "My Paper Title", "domain", ["My Paper Title"]),  # self-referential
            _entity("m1", "Some Metric", "metric", ["My Paper Title"]),
            _entity("d1", "Some Dataset", "dataset", ["Other Paper"]),
        ]
        relationships = [
            _rel("paper1", "m1", "mentions", paper="My Paper Title"),
            _rel("d1", "x", "evaluated_on", paper="Other Paper"),
        ]
        graph = {"entities": entities, "relationships": relationships,
                 "orphan_concepts": [], "missing_bridges": []}
        gaps = detect_graph_structural_gaps(graph)
        combo_gaps = [g for g in gaps if g["pattern_id"] == "graph_untested_combination"]
        for g in combo_gaps:
            self.assertNotIn("My Paper Title", g["title"])

    def test_paper_container_entity_is_excluded_from_conflicting_relationships(self):
        entities = [
            _entity("paper1", "My Paper Title", "domain", ["My Paper Title"]),
            _entity("m1", "Some Metric", "metric", ["My Paper Title"]),
        ]
        relationships = [
            _rel("paper1", "m1", "outperforms", paper="P1"),
            _rel("paper1", "m1", "underperforms_on", paper="P2"),
        ]
        graph = {"entities": entities, "relationships": relationships,
                 "orphan_concepts": [], "missing_bridges": []}
        gaps = detect_graph_structural_gaps(graph)
        self.assertEqual([g for g in gaps if g["pattern_id"] == "graph_conflicting_relationship"], [])

    def test_paper_container_entity_is_excluded_from_orphan_promotion(self):
        graph = {
            "entities": [], "relationships": [], "missing_bridges": [],
            "orphan_concepts": [
                {"entity": {"name": "My Paper Title", "papers": ["My Paper Title"]},
                 "connections": 0, "signal": "orphan paper-container"},
                {"entity": {"name": "Real Orphan Concept", "papers": ["My Paper Title"]},
                 "connections": 0, "signal": "genuine orphan"},
            ],
        }
        gaps = detect_graph_structural_gaps(graph)
        orphan_gaps = [g for g in gaps if g["pattern_id"] == "graph_orphan_concept"]
        self.assertEqual(len(orphan_gaps), 1)
        self.assertIn("Real Orphan Concept", orphan_gaps[0]["title"])

    def test_a_genuine_concept_entity_that_merely_shares_its_papers_paper_is_not_excluded(self):
        # Sanity check the heuristic isn't over-broad: a real concept whose
        # name differs from the paper title must still be eligible.
        entities = [
            _entity("m1", "Model A", "model", ["Some Paper"]),
            _entity("d1", "Dataset X", "dataset", ["Other Paper"]),
            _entity("other", "Other Thing", "concept", ["Some Paper"]),
        ]
        relationships = [
            _rel("m1", "other", "evaluated_on", paper="Some Paper"),
            _rel("d1", "other", "trained_on", paper="Other Paper"),
        ]
        graph = {"entities": entities, "relationships": relationships,
                 "orphan_concepts": [], "missing_bridges": []}
        gaps = detect_graph_structural_gaps(graph)
        combo_gaps = [g for g in gaps if g["pattern_id"] == "graph_untested_combination"]
        self.assertEqual(len(combo_gaps), 1)


class GapShapeTests(unittest.TestCase):
    def test_all_emitted_gaps_share_the_llm_gap_shape(self):
        graph = {
            "entities": [], "relationships": [],
            "orphan_concepts": [{"entity": {"name": "X", "papers": ["P1"]}, "connections": 0, "signal": "s"}],
            "missing_bridges": [],
        }
        gap = detect_graph_structural_gaps(graph)[0]
        for key in ("title", "description", "gap_type", "confidence", "evidence",
                    "supporting_papers", "missing_connection", "why_important",
                    "validation_status", "existing_papers", "source", "pattern_id"):
            self.assertIn(key, gap)


if __name__ == "__main__":
    unittest.main()
