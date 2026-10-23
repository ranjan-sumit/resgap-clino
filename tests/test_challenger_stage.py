"""PR-22c: Stage 5b runs the Gap Challenger for every gap, side by side, and one failure costs only that gap."""
import contextlib
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from pipeline.run_pipeline import RunOptions, run_full_pipeline

_PAPERS = [("paper_1.pdf", b"%PDF-1.4 fake"), ("paper_2.pdf", b"%PDF-1.4 fake two")]


def _paper(name):
    return {"filename": name, "char_count": 100, "sections": {}, "tables": [], "figures": []}


GAPS = [{"title": f"Gap {i}", "description": "d", "confidence": "high", "gap_id": f"g{i}", "supporting_papers": []}
        for i in range(5)]


class ChallengerStageTests(unittest.TestCase):
    def _run(self, challenge):
        options = RunOptions(provider_key="nvidia", model="test-model", enable_gap_challenger=True)
        targets = {
            "check_pdf_readable": dict(return_value=None),
            "parse_pdf": dict(side_effect=lambda _p, f, **_kw: _paper(f)),
            "build_tree": dict(return_value={"root": {}}),
            "tree_to_summary": dict(return_value="tree"),
            "build_wiki": dict(return_value={"pages": [{"title": "p1"}, {"title": "p2"}],
                                             "cross_links": {"shared_concepts": []}}),
            "build_knowledge_graph": dict(return_value={"stats": {"entity_count": 0, "relationship_count": 0},
                                                        "communities": []}),
            "score_graph_quality": dict(return_value={"build_status": "ok", "quality_score": 1.0}),
            "find_gaps": dict(return_value={"gaps": [dict(g) for g in GAPS], "rejected": [], "diagnostics": {}}),
            "detect_deterministic_gaps": dict(return_value=[]),
            "detect_graph_structural_gaps": dict(return_value=[]),
            "apply_graph_quality_to_gaps": dict(side_effect=lambda g, _q: g),
            "scout_gaps": dict(side_effect=lambda gaps, *_a, **_kw: {"gaps": gaps, "diagnostics": {}}),
            "run_challenge": dict(side_effect=challenge),
            "generate_proposals": dict(return_value=[]),
            "assign_tiers": dict(return_value=[]),
            "corpus_stats": dict(return_value={}),
            "summarise_reference_corpus": dict(return_value={"total": 0, "tier2_abstract": 0, "tier3_title": 0}),
            "extract_evidence_cached": dict(return_value=([], None, None)),
            "save_run": dict(return_value="run-id-123"),
            "record_artifact": dict(),
            "record_run_lineage": dict(return_value={"artifact_ids": []}),
            "record_run_manifest": dict(),
        }
        with contextlib.ExitStack() as stack:
            for name, kw in targets.items():
                stack.enter_context(patch(f"pipeline.run_pipeline.{name}", **kw))
            return run_full_pipeline(papers=_PAPERS, context={"domain": "Healthcare AI"}, client=MagicMock(),
                                     options=options, warn=lambda *_: None)

    def test_every_gap_is_challenged_and_one_failure_costs_only_that_gap(self):
        def challenge(gap, client, **kw):
            if gap["gap_id"] == "g2":
                raise RuntimeError("search exploded")
            return {"challenger_state": "CHALLENGED", "challenger_status": "OPEN", "challenged_gap_id": gap["gap_id"]}

        outcome = self._run(challenge)
        gaps = {g["gap_id"]: g for g in outcome.results["gaps"]}
        self.assertEqual({k: g.get("challenger_status") for k, g in gaps.items()},
                         {"g0": "OPEN", "g1": "OPEN", "g2": None, "g3": "OPEN", "g4": "OPEN"})
        self.assertIn("search exploded", gaps["g2"]["challenger_error"])

    def test_gaps_are_challenged_side_by_side(self):
        live, peak, lock = [0], [0], threading.Lock()

        def challenge(gap, client, **kw):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.2)
            with lock:
                live[0] -= 1
            return {"challenger_state": "CHALLENGED", "challenger_status": "OPEN"}

        t0 = time.time()
        self._run(challenge)
        self.assertGreaterEqual(peak[0], 2)
        self.assertLess(time.time() - t0, 5 * 0.2 + 30)          # the pipeline itself is fast here; mostly proves overlap

    def test_arxiv_is_not_searched_for_a_healthcare_corpus(self):
        seen = []

        def challenge(gap, client, **kw):
            seen.append(kw.get("use_arxiv"))
            return {"challenger_state": "CHALLENGED", "challenger_status": "OPEN"}

        self._run(challenge)
        self.assertTrue(seen and all(v is False for v in seen))      # healthcare study types: no arXiv


if __name__ == "__main__":
    unittest.main()
