"""
Tests for Clinova Phase 4, Epic 4.4's Scientific Lineage plumbing in
pipeline/graph_builder.py: relationship_id assignment (both the LLM path
and the fallback path) and evidence provenance linking via
pipeline/evidence_linker.py.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import Success, Failure, ErrorInfo
from pipeline.graph_builder import build_knowledge_graph


def _wiki(source_file="paper1.pdf", title="Paper One"):
    return {
        "pages": [{"title": title, "source_file": source_file, "key_concepts": ["x"],
                   "methods": [], "limitations": [], "future_work": [], "datasets": [],
                   "key_findings": [], "evaluated_on": []}],
        "cross_links": {},
    }


_ENTITY_JSON_WITH_RELATIONSHIPS = (
    '{"entities": ['
    '{"id": "e1", "name": "Entity One", "type": "concept", "papers": ["Paper One"], "importance": "high"},'
    '{"id": "e2", "name": "Entity Two", "type": "method", "papers": ["Paper One"], "importance": "high"}'
    '], "relationships": ['
    '{"source": "e1", "target": "e2", "relation": "extends", "paper": "Paper One", '
    '"evidence": "state of the art accuracy on the benchmark dataset"}'
    ']}'
)
_COMMUNITY_JSON = '[]'


class RelationshipIdLLMPathTests(unittest.TestCase):
    def test_relationship_gets_a_real_id(self):
        client = MagicMock()
        client.chat_json.side_effect = [Success(_ENTITY_JSON_WITH_RELATIONSHIPS), Success(_COMMUNITY_JSON)]
        result = build_knowledge_graph(_wiki(), client)
        rel = result["relationships"][0]
        self.assertIn("relationship_id", rel)
        self.assertTrue(rel["relationship_id"])

    def test_relationship_id_is_deterministic(self):
        client1 = MagicMock()
        client1.chat_json.side_effect = [Success(_ENTITY_JSON_WITH_RELATIONSHIPS), Success(_COMMUNITY_JSON)]
        result1 = build_knowledge_graph(_wiki(), client1)

        client2 = MagicMock()
        client2.chat_json.side_effect = [Success(_ENTITY_JSON_WITH_RELATIONSHIPS), Success(_COMMUNITY_JSON)]
        result2 = build_knowledge_graph(_wiki(), client2)

        self.assertEqual(result1["relationships"][0]["relationship_id"],
                          result2["relationships"][0]["relationship_id"])

    def test_duplicate_relationships_get_suffixed_ids(self):
        dup_json = (
            '{"entities": [{"id": "e1", "name": "E1", "type": "concept", "papers": [], "importance": "high"},'
            '{"id": "e2", "name": "E2", "type": "concept", "papers": [], "importance": "high"}], '
            '"relationships": ['
            '{"source": "e1", "target": "e2", "relation": "extends", "paper": "P", "evidence": "a"},'
            '{"source": "e1", "target": "e2", "relation": "extends", "paper": "P", "evidence": "a"}'
            ']}'
        )
        client = MagicMock()
        client.chat_json.side_effect = [Success(dup_json), Success(_COMMUNITY_JSON)]
        result = build_knowledge_graph(_wiki(), client)
        ids = [r["relationship_id"] for r in result["relationships"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_relationship_id_present_without_evidence_objects(self):
        """relationship_id assignment doesn't depend on the optional
        evidence_objects param being supplied."""
        client = MagicMock()
        client.chat_json.side_effect = [Success(_ENTITY_JSON_WITH_RELATIONSHIPS), Success(_COMMUNITY_JSON)]
        result = build_knowledge_graph(_wiki(), client)
        self.assertTrue(result["relationships"][0]["relationship_id"])
        # No evidence_objects supplied -> linking was never attempted, so
        # the key is honestly absent, not fabricated as an empty list.
        self.assertNotIn("provenance_evidence_ids", result["relationships"][0])
        self.assertNotIn("provenance_resolution", result["diagnostics"])


class RelationshipIdFallbackPathTests(unittest.TestCase):
    def test_fallback_graph_relationships_also_get_ids(self):
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="timeout", detail="timed out"))
        result = build_knowledge_graph(_wiki(), client)
        self.assertTrue(result["diagnostics"]["used_fallback"])
        for rel in result["relationships"]:
            self.assertIn("relationship_id", rel)
            self.assertTrue(rel["relationship_id"])


class ProvenanceLinkingTests(unittest.TestCase):
    def test_evidence_objects_supplied_links_real_evidence(self):
        client = MagicMock()
        client.chat_json.side_effect = [Success(_ENTITY_JSON_WITH_RELATIONSHIPS), Success(_COMMUNITY_JSON)]
        evidence_objects = {
            "paper1.pdf": [
                {"evidence_id": "ev1", "text": "The model achieves state of the art accuracy on the benchmark dataset."},
            ],
        }
        result = build_knowledge_graph(_wiki(), client, evidence_objects=evidence_objects)
        rel = result["relationships"][0]
        self.assertEqual(rel["provenance_evidence_ids"], ["ev1"])
        self.assertIn("provenance_resolution", result["diagnostics"])
        self.assertEqual(result["diagnostics"]["provenance_resolution"]["relationships_with_evidence"], 1)

    def test_no_matching_evidence_gives_honest_empty_list(self):
        client = MagicMock()
        client.chat_json.side_effect = [Success(_ENTITY_JSON_WITH_RELATIONSHIPS), Success(_COMMUNITY_JSON)]
        evidence_objects = {"paper1.pdf": [{"evidence_id": "ev1", "text": "totally unrelated content about cooking"}]}
        result = build_knowledge_graph(_wiki(), client, evidence_objects=evidence_objects)
        self.assertEqual(result["relationships"][0]["provenance_evidence_ids"], [])

    def test_network_diagram_edges_carry_relationship_id(self):
        client = MagicMock()
        client.chat_json.side_effect = [Success(_ENTITY_JSON_WITH_RELATIONSHIPS), Success(_COMMUNITY_JSON)]
        result = build_knowledge_graph(_wiki(), client)
        edge = result["network_data"]["edges"][0]
        self.assertIn("relationship_id", edge)


if __name__ == "__main__":
    unittest.main()
