"""_model_bundle names the models a run used; with no per-role assignment it must
fall back to the single provider:model instead of calling itself forever (the
manifest step swallowed the RecursionError, so runs silently lost their manifest)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.run_pipeline import RunOptions, _model_bundle


class ModelBundleTests(unittest.TestCase):
    def test_without_a_role_assignment_it_names_the_single_model(self):
        self.assertEqual(_model_bundle(RunOptions(provider_key="gemini", model="gemini-3.5-flash-lite")),
                         "gemini:gemini-3.5-flash-lite")

    def test_with_a_role_assignment_it_lists_the_roles_and_fallback(self):
        models = {"roles": {"extraction": {"provider": "gemini", "model": "a"},
                            "wiki": {"provider": "gemini", "model": "a"},
                            "analysis": {"provider": "gemini", "model": "b"}},
                  "fallback": {"provider": "gemini", "model": "c"}}
        out = _model_bundle(RunOptions(provider_key="gemini", model="b", models=models))
        self.assertEqual(out, "extraction=gemini:a; wiki=gemini:a; analysis=gemini:b; fallback=gemini:c")

    def test_an_empty_assignment_falls_back_too(self):
        self.assertEqual(_model_bundle(RunOptions(provider_key="x", model="y", models={})), "x:y")


if __name__ == "__main__":
    unittest.main()
