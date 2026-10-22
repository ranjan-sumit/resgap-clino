import os

import pytest

from tests.fixtures.make_golden_run import golden_results
from tests.ui.harness import ARTIFACTS, running_app, screenshot_all

pytestmark = pytest.mark.e2e


def test_home_renders_at_three_viewports(tmp_path):
    with running_app(tmp_path) as url:
        shots = screenshot_all(url, "home")
    assert len(shots) == 3 and all(p.stat().st_size > 5000 for p in shots)


def test_background_run_survives_a_page_refresh_and_opens_results(tmp_path, monkeypatch):
    from pathlib import Path
    import utils.database as db
    from tests.test_unreadable_pdfs import _text_pdf
    from utils import project_store
    monkeypatch.setenv("RESGAP_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv("RESGAP_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 30)
    db._INITIALIZED.clear()
    project_store.save_papers(db.DEFAULT_PROJECT_ID, [(f"p{i}.pdf", _text_pdf(f"x{i}")) for i in range(2)])
    from playwright.sync_api import sync_playwright
    script = Path(__file__).parent / "fake_runner_app.py"
    with running_app(tmp_path, script=script) as url, sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url)
        page.wait_for_selector("text=New analysis", timeout=45000)
        for label in ("p0.pdf", "p1.pdf"):
            page.get_by_text(label, exact=False).first.click()
        page.get_by_role("button", name="Run analysis").click()
        page.wait_for_selector("text=running in the background", timeout=30000)
        page.wait_for_selector("text=Summarise each paper", timeout=15000)
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(ARTIFACTS / "background-running.png"))
        page.reload()                                              # the tab is refreshed mid-run
        page.wait_for_selector("text=running in the background", timeout=30000)
        page.wait_for_selector("text=Papers Analysed", timeout=60000)   # finished: results open by themselves
        page.screenshot(path=str(ARTIFACTS / "background-done.png"))
        browser.close()


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
