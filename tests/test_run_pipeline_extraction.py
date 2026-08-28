"""
Guards the Stage 1-6 extraction from app.py into pipeline/run_pipeline.py
(Clinova Phase 5, Epic 5.6).

These deliberately do NOT execute a real pipeline run -- that costs real LLM
calls and minutes of wall clock. What they lock in is the extraction's
contract: that the module is genuinely Streamlit-free, that its callbacks are
optional, that it validates input before spending anything, and that app.py
now delegates to it instead of carrying its own copy of the orchestration.
"""
import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.run_pipeline import (
    MAX_PAPERS, MIN_PAPERS, PipelineInputError, RunOptions, run_full_pipeline,
)

REPO = Path(__file__).resolve().parent.parent


class ExtractionContractTests(unittest.TestCase):
    def test_module_imports_no_streamlit(self):
        """The whole point of the extraction: a non-Streamlit caller (the
        FastAPI app) must be able to import and run this."""
        source = (REPO / "pipeline" / "run_pipeline.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("streamlit", imported)

    def test_too_few_papers_raises_before_doing_any_work(self):
        # A client that would explode if touched -- proves validation happens
        # before the pipeline spends anything.
        class ExplodingClient:
            def __getattr__(self, name):
                raise AssertionError(f"client.{name} must not be touched on invalid input")

        with self.assertRaises(PipelineInputError) as ctx:
            run_full_pipeline(
                papers=[("only_one.pdf", b"%PDF-1.4")],
                context={"domain": "Healthcare AI"},
                client=ExplodingClient(),
                options=RunOptions(provider_key="nvidia", model="test-model"),
            )
        self.assertIn("at least", str(ctx.exception).lower())

    def test_callbacks_are_optional(self):
        """progress/trace/warn all default to no-ops, so a script or the API
        can call this without inventing UI callbacks."""
        import inspect
        sig = inspect.signature(run_full_pipeline)
        for cb in ("progress", "trace", "warn"):
            self.assertIsNot(sig.parameters[cb].default, inspect.Parameter.empty)

    def test_paper_limits_match_the_original_streamlit_behaviour(self):
        self.assertEqual(MIN_PAPERS, 2)
        self.assertEqual(MAX_PAPERS, 5)

    def test_results_dict_still_carries_pipeline_trace(self):
        """Run Detail's Stages tab reads results["pipeline_trace"]. The
        extraction moved trace emission to a callback, so the module has to
        retain the rows itself or every new run would silently lose its
        stage timeline."""
        source = (REPO / "pipeline" / "run_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('"pipeline_trace": trace_rows', source)


class AppDelegatesToTheExtractionTests(unittest.TestCase):
    """app.py must call the shared pipeline, not keep a second copy of the
    orchestration that could drift away from what the API runs."""

    def setUp(self):
        self.source = (REPO / "app.py").read_text(encoding="utf-8")

    def test_app_calls_run_full_pipeline(self):
        self.assertIn("run_full_pipeline(", self.source)

    def test_app_no_longer_inlines_the_stage_orchestration(self):
        # These were the load-bearing calls of the old inline block. If any
        # reappears in app.py, the two callers have started to diverge.
        for moved_call in ("build_wiki(", "build_knowledge_graph(", "detect_gaps(",
                            "validate_gaps(", "generate_proposals("):
            self.assertNotIn(moved_call, self.source,
                             f"{moved_call} should now live only in pipeline/run_pipeline.py")

    def test_app_still_passes_its_streamlit_callbacks_in(self):
        self.assertIn("progress=upd", self.source)
        self.assertIn("trace=_add_trace", self.source)


if __name__ == "__main__":
    unittest.main()
