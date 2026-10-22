import os

import pytest

from tests.fixtures.make_golden_run import golden_results
from tests.ui.harness import ARTIFACTS, running_app, screenshot_all

pytestmark = pytest.mark.e2e


def test_home_renders_at_three_viewports(tmp_path):
    with running_app(tmp_path) as url:
        shots = screenshot_all(url, "home")
    assert len(shots) == 3 and all(p.stat().st_size > 5000 for p in shots)


def test_headline_numbers_are_visible_without_scrolling_at_1440x800(tmp_path, monkeypatch):
    import utils.database as db
    from tests.fixtures.make_golden_run import seed_run
    monkeypatch.setenv("RESGAP_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv("RESGAP_PROJECTS_DIR", str(tmp_path / "projects"))
    db._INITIALIZED.clear()
    seed_run(golden_results())
    from playwright.sync_api import sync_playwright
    with running_app(tmp_path) as url, sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 800})
        page.goto(url)
        page.wait_for_selector("text=Papers Analysed", timeout=45000)
        page.wait_for_timeout(1500)
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(ARTIFACTS / "loaded-run-1440.png"))
        box = page.get_by_text("Papers Analysed").bounding_box()
        browser.close()
    # The run's headline numbers are the first thing on screen (they used to start ~1,000 px down).
    assert box is not None and box["y"] + box["height"] <= 800, f"headline numbers at y={box and box['y']}"
