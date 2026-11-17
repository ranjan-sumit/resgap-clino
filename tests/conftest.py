"""Shared fixtures. Import `tests.fakes` / `tests.fixtures.make_golden_run` directly."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _never_touch_real_data(tmp_path_factory, monkeypatch):
    """Every test starts on a throwaway database and projects folder. Before this, a test that did not ask for
    `isolated_env` (three pipeline tests) wrote run.started / run.finished events into the real, tamper-evident
    audit log in data/run_history.db. A test that needs its own location still sets it, and `isolated_env` replaces
    this one."""
    import utils.database as db
    base = tmp_path_factory.mktemp("guard")
    monkeypatch.setenv("RESGAP_DB_PATH", str(base / "guard.db"))
    monkeypatch.setenv("RESGAP_PROJECTS_DIR", str(base / "projects"))
    db._INITIALIZED.clear()
    yield
    db._INITIALIZED.clear()


@pytest.fixture(autouse=True)
def _no_provider_pacing(monkeypatch):
    """Lookups to Semantic Scholar wait for their turn in real runs (1-3.5 s apiece); tests mock the network and must not."""
    import pipeline.reference_extractor as rx
    monkeypatch.setattr(rx, "_s2_pace", lambda: None)
    monkeypatch.setitem(rx._SS_KEY, "value", "")             # a run sets this key and never clears it; no test may inherit it
    yield


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Fresh SQLite file and projects folder; nothing touches real data."""
    import utils.database as db
    monkeypatch.setenv("RESGAP_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("RESGAP_PROJECTS_DIR", str(tmp_path / "projects"))
    db._INITIALIZED.clear()
    yield tmp_path
    db._INITIALIZED.clear()


@pytest.fixture
def app_test(isolated_env):
    """Factory returning a loaded AppTest of app.py against the isolated env."""
    from streamlit.testing.v1 import AppTest

    def make(timeout: int = 60):
        return AppTest.from_file(str(ROOT / "app.py"), default_timeout=timeout).run()
    return make


def pytest_collection_modifyitems(config, items):
    # Tests using the app_test fixture are UI tests.
    for item in items:
        if "app_test" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.ui)
