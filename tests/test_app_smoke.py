"""
Smoke test: the whole Streamlit app (app.py) loads against an empty database
without raising, and the project controls are present. Catches syntax and
wiring mistakes in the UI layer that no unit test of a helper would see.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from streamlit.testing.v1 import AppTest

import utils.database as db
from utils import project_store

APP = str(Path(__file__).resolve().parent.parent / "app.py")


class AppSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="resgap_app_")
        self.env = patch.dict(os.environ, {"RESGAP_DB_PATH": str(Path(self.tmp) / "t.db"),
                                           "RESGAP_PROJECTS_DIR": str(Path(self.tmp) / "projects")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        db._INITIALIZED.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self):
        return AppTest.from_file(APP, default_timeout=120).run()

    def test_app_parses(self):
        import ast
        ast.parse(Path(APP).read_text(encoding="utf-8"))

    def test_loads_with_an_empty_database_and_shows_project_controls(self):
        at = self._run()
        self.assertEqual([e.value for e in at.exception], [])
        self.assertEqual([e.value for e in at.error], [])
        picker = next(s for s in at.sidebar.selectbox if s.label == "Project")
        self.assertEqual(len(picker.options), 1)
        self.assertIn("Default project", picker.options[0])
        self.assertIn("New project", [b.label for b in at.sidebar.button])
        run_btn = next(b for b in at.button if b.label == "Run analysis")
        self.assertTrue(run_btn.disabled)          # no papers yet
        self.assertEqual(len(at.tabs), 0)          # no results on screen

    def test_newly_created_projects_appear_in_the_picker(self):
        project_store.create_project("Alpha review")
        at = self._run()
        self.assertEqual([e.value for e in at.exception], [])
        picker = next(s for s in at.sidebar.selectbox if s.label == "Project")
        self.assertEqual(len(picker.options), 2)
        self.assertTrue(any("Alpha review" in o for o in picker.options))

    def test_selecting_another_project_keeps_the_app_healthy(self):
        project_store.create_project("Alpha review")
        at = self._run()
        picker = next(s for s in at.sidebar.selectbox if s.label == "Project")
        alpha = next(o for o in picker.options if "Alpha review" in o)
        picker.select(alpha).run()
        self.assertEqual([e.value for e in at.exception], [])
        self.assertIn("Alpha review", next(m.value for m in at.markdown if "Project" in m.value and "Alpha" in m.value))
        self.assertIn("No saved runs in this project yet.", [c.value for c in at.sidebar.caption])


_ALL_KEYS = ("NVIDIA_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "DASHSCOPE_API_KEY",
             "CUSTOM_LLM_API_KEY", "CUSTOM_LLM_BASE_URL")


class ModelPickerUiTests(unittest.TestCase):
    """'Models for this run': which provider/model does which job, in the Run step."""

    def _env(self, **keys):
        self.tmp = tempfile.mkdtemp(prefix="resgap_models_ui_")
        env = {k: "" for k in _ALL_KEYS}      # "" (not absent) stops app.py's .env loader from filling them in
        env.update(keys)
        env.update({"RESGAP_DB_PATH": str(Path(self.tmp) / "t.db"),
                    "RESGAP_PROJECTS_DIR": str(Path(self.tmp) / "projects")})
        self.patcher = patch.dict(os.environ, env)
        self.patcher.start()
        return AppTest.from_file(APP, default_timeout=120).run()

    def tearDown(self):
        self.patcher.stop()
        db._INITIALIZED.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _models(self, at):
        return {role: (at.selectbox(key=f"mp_{role}").value, at.selectbox(key=f"mm_{role}").value)
                for role in ("extraction", "wiki", "analysis", "fallback", "council_a", "council_b", "council_c",
                             "council_chair")}

    def test_panel_shows_a_row_for_every_job_and_the_test_and_preset_buttons(self):
        at = self._env(GEMINI_API_KEY="fake")
        self.assertEqual([e.value for e in at.exception], [])
        self.assertEqual(len(self._models(at)), 8)
        labels = [b.label for b in at.button]
        for expected in ("Test models", "Use recommended", "Fastest", "Refresh model lists"):
            self.assertIn(expected, labels)

    def test_with_only_gemini_everything_defaults_to_gemini_and_nothing_blocks_the_run(self):
        at = self._env(GEMINI_API_KEY="fake")
        m = self._models(at)
        self.assertEqual(m["extraction"], ("gemini", "gemini-3.5-flash-lite"))
        self.assertEqual(m["analysis"], ("gemini", "gemini-3.5-flash-lite"))   # request headroom for 29+ calls
        self.assertEqual(m["council_chair"], ("gemini", "gemini-3.6-flash"))   # few calls, so the stronger model
        self.assertEqual(m["fallback"][0], "gemini")                       # a different model, same provider
        self.assertNotEqual(m["fallback"], m["analysis"])
        self.assertFalse(any("add a" in x.value.lower() and "key" in x.value.lower()
                             for x in at.markdown if "run-status" in x.value))

    def test_without_any_key_run_is_held_with_a_clear_message(self):
        at = self._env()
        status = " ".join(x.value for x in at.markdown if "run-status" in x.value)
        self.assertIn("add a", status.lower())
        self.assertIn("key", status.lower())
        self.assertTrue(next(b for b in at.button if b.label == "Run analysis").disabled)

    def test_fastest_preset_puts_the_fast_model_on_every_job(self):
        at = self._env(GEMINI_API_KEY="fake", NVIDIA_API_KEY="fake")
        at.button(key="preset_fastest").click().run()
        self.assertEqual([e.value for e in at.exception], [])
        for role, spec in self._models(at).items():
            if role != "fallback":
                self.assertEqual(spec, ("gemini", "gemini-3.5-flash-lite"), role)

    def test_changing_a_provider_resets_its_model_and_saves_the_choice(self):
        at = self._env(GEMINI_API_KEY="fake", NVIDIA_API_KEY="fake")
        at.selectbox(key="mp_wiki").select("nvidia").run()
        self.assertEqual([e.value for e in at.exception], [])
        self.assertEqual(at.selectbox(key="mm_wiki").value, "openai/gpt-oss-20b")
        saved = json.loads((Path(self.tmp) / "model_settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["roles"]["wiki"], {"provider": "nvidia", "model": "openai/gpt-oss-20b"})
        self.assertNotIn("key", json.dumps(saved).lower())

    def test_a_role_on_a_provider_without_a_key_blocks_run_and_names_it(self):
        at = self._env(GEMINI_API_KEY="fake")
        at.selectbox(key="mp_analysis").select("nvidia").run()
        status = " ".join(x.value for x in at.markdown if "run-status" in x.value)
        self.assertIn("Analysis", status)
        self.assertIn("NVIDIA", status)
        self.assertTrue(next(b for b in at.button if b.label == "Run analysis").disabled)

    def test_choosing_no_fallback_is_allowed(self):
        at = self._env(GEMINI_API_KEY="fake")
        at.selectbox(key="mp_fallback").select("(none)").run()
        self.assertEqual([e.value for e in at.exception], [])
        self.assertIn("No fallback", " ".join(c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()
