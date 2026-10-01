import unittest

from pipeline.graph_quality import score_graph_quality, apply_graph_quality_to_gaps


def _graph(entities, relationships, used_fallback=False):
    return {
        "entities": entities,
        "relationships": relationships,
        "diagnostics": {"used_fallback": used_fallback},
    }


def _wiki(titles):
    return {"pages": [{"title": t} for t in titles]}


class ScoreGraphQualityCleanTests(unittest.TestCase):
    def test_clean_graph_scores_high_and_is_not_fallback(self):
        entities = [
            {"id": "e1", "name": "Model A", "papers": ["Paper 1"]},
            {"id": "e2", "name": "Dataset X", "papers": ["Paper 1", "Paper 2"]},
        ]
        relationships = [
            {"source": "e1", "target": "e2", "relation": "evaluates_on", "evidence": "trained on X per Table 2"},
        ]
        result = score_graph_quality(_graph(entities, relationships), _wiki(["Paper 1", "Paper 2"]))
        self.assertEqual(result["build_status"], "CLEAN")
        self.assertFalse(result["fallback_indicator"])
        self.assertEqual(result["duplicate_rate"], 0.0)
        self.assertEqual(result["unresolved_entity_rate"], 0.0)
        self.assertEqual(result["evidence_coverage"], 1.0)
        self.assertEqual(result["extraction_coverage"], 1.0)
        self.assertGreaterEqual(result["quality_score"], 0.5)

    def test_no_wiki_gives_honest_zero_extraction_coverage_not_a_guess(self):
        entities = [{"id": "e1", "name": "Model A", "papers": ["Paper 1"]}]
        result = score_graph_quality(_graph(entities, []))
        self.assertEqual(result["extraction_coverage"], 0.0)


class ScoreGraphQualityDegradedTests(unittest.TestCase):
    def test_duplicate_entities_are_counted(self):
        entities = [
            {"id": "e1", "name": "Model A", "papers": []},
            {"id": "e2", "name": "model a", "papers": []},  # same normalized name
            {"id": "e3", "name": "  Model A  ", "papers": []},  # same normalized name
        ]
        result = score_graph_quality(_graph(entities, []))
        self.assertEqual(result["duplicate_rate"], round(2 / 3, 3))

    def test_unresolved_relationship_is_counted(self):
        entities = [{"id": "e1", "name": "Model A", "papers": []}]
        relationships = [
            {"source": "e1", "target": "does_not_exist", "relation": "extends", "evidence": "x"},
        ]
        result = score_graph_quality(_graph(entities, relationships))
        self.assertEqual(result["unresolved_entity_rate"], 1.0)

    def test_relationship_resolves_by_name_when_id_does_not_match(self):
        entities = [{"id": "e1", "name": "Model A", "papers": []},
                    {"id": "e2", "name": "Dataset X", "papers": []}]
        relationships = [
            {"source": "Model A", "target": "Dataset X", "relation": "evaluates_on", "evidence": "x"},
        ]
        result = score_graph_quality(_graph(entities, relationships))
        self.assertEqual(result["unresolved_entity_rate"], 0.0)

    def test_missing_evidence_lowers_evidence_coverage(self):
        entities = [{"id": "e1", "name": "A", "papers": []}, {"id": "e2", "name": "B", "papers": []}]
        relationships = [
            {"source": "e1", "target": "e2", "relation": "extends", "evidence": ""},
        ]
        result = score_graph_quality(_graph(entities, relationships))
        self.assertEqual(result["evidence_coverage"], 0.0)

    def test_low_quality_real_graph_is_degraded_not_fallback(self):
        # No evidence, all entities duplicated, one unresolved relationship,
        # no wiki passed -- every signal is bad, but this is a real (non-
        # fallback) LLM-extracted graph.
        entities = [
            {"id": "e1", "name": "A", "papers": []},
            {"id": "e2", "name": "a", "papers": []},
        ]
        relationships = [{"source": "e1", "target": "missing", "relation": "x", "evidence": ""}]
        result = score_graph_quality(_graph(entities, relationships, used_fallback=False))
        self.assertEqual(result["build_status"], "DEGRADED")
        self.assertFalse(result["fallback_indicator"])


class ScoreGraphQualityFallbackTests(unittest.TestCase):
    def test_fallback_graph_is_always_fallback_status_even_with_perfect_signals(self):
        entities = [{"id": "e1", "name": "A", "papers": ["Paper 1"]}]
        relationships = [{"source": "e1", "target": "e1", "relation": "mentions", "evidence": "wiki field"}]
        # entities self-referencing so unresolved=0, evidence present -- would
        # score CLEAN under the raw arithmetic if fallback weren't checked first.
        result = score_graph_quality(_graph(entities, relationships, used_fallback=True), _wiki(["Paper 1"]))
        self.assertEqual(result["build_status"], "FALLBACK")
        self.assertTrue(result["fallback_indicator"])

    def test_fallback_penalty_actually_reduces_the_score(self):
        entities = [{"id": "e1", "name": "A", "papers": ["Paper 1"]}]
        relationships = [{"source": "e1", "target": "e1", "relation": "mentions", "evidence": "wiki field"}]
        wiki = _wiki(["Paper 1"])
        clean = score_graph_quality(_graph(entities, relationships, used_fallback=False), wiki)
        fallback = score_graph_quality(_graph(entities, relationships, used_fallback=True), wiki)
        self.assertLess(fallback["quality_score"], clean["quality_score"])


class ApplyGraphQualityToGapsTests(unittest.TestCase):
    def _gap(self, source, confidence):
        return {"title": "t", "source": source, "confidence": confidence}

    def test_clean_status_leaves_gaps_untouched(self):
        gaps = [self._gap("graph_structural", "high")]
        quality = {"build_status": "CLEAN", "quality_score": 0.9}
        result = apply_graph_quality_to_gaps(gaps, quality)
        self.assertEqual(result[0]["confidence"], "high")
        self.assertNotIn("confidence_caveat", result[0])

    def test_degraded_status_downgrades_graph_structural_gaps_by_one_level(self):
        gaps = [self._gap("graph_structural", "high")]
        quality = {"build_status": "DEGRADED", "quality_score": 0.3}
        result = apply_graph_quality_to_gaps(gaps, quality)
        self.assertEqual(result[0]["confidence"], "medium")
        self.assertIn("confidence_caveat", result[0])

    def test_degraded_status_does_not_touch_other_sources(self):
        gaps = [self._gap("deterministic_pattern", "high"), self._gap("semantic", "high")]
        quality = {"build_status": "DEGRADED", "quality_score": 0.3}
        result = apply_graph_quality_to_gaps(gaps, quality)
        self.assertEqual(result[0]["confidence"], "high")
        self.assertEqual(result[1]["confidence"], "high")
        self.assertNotIn("confidence_caveat", result[0])

    def test_fallback_status_caps_graph_structural_confidence_at_low(self):
        gaps = [self._gap("graph_structural", "high")]
        quality = {"build_status": "FALLBACK", "quality_score": 0.2}
        result = apply_graph_quality_to_gaps(gaps, quality)
        self.assertEqual(result[0]["confidence"], "low")

    def test_already_low_confidence_is_not_marked_as_downgraded(self):
        gaps = [self._gap("graph_structural", "low")]
        quality = {"build_status": "DEGRADED", "quality_score": 0.3}
        result = apply_graph_quality_to_gaps(gaps, quality)
        self.assertEqual(result[0]["confidence"], "low")
        self.assertNotIn("confidence_caveat", result[0])

    def test_does_not_mutate_input_gaps(self):
        gaps = [self._gap("graph_structural", "high")]
        quality = {"build_status": "FALLBACK", "quality_score": 0.2}
        apply_graph_quality_to_gaps(gaps, quality)
        self.assertEqual(gaps[0]["confidence"], "high")


class DuplicateRateNamedEntitiesTests(unittest.TestCase):
    def test_empty_named_entities_are_excluded_from_the_denominator(self):
        # Entities with no name cannot be duplicates; counting them in the
        # denominator biased the rate downward.
        entities = [
            {"id": "e1", "name": "Model A", "papers": []},
            {"id": "e2", "name": "model a", "papers": []},
            {"id": "e3", "name": "", "papers": []},
            {"id": "e4", "papers": []},  # no name key at all
        ]
        result = score_graph_quality(_graph(entities, []))
        # 1 duplicate over 2 named entities, not 1 over 4 total entities
        self.assertEqual(result["duplicate_rate"], round(1 / 2, 3))


if __name__ == "__main__":
    unittest.main()
