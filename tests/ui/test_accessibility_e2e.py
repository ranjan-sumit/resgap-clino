"""axe-core on the main screens at three widths (nightly; needs network for axe-core and Chromium)."""
import pytest

from tests.fixtures.make_golden_run import golden_comp, golden_results, seed_run
from tests.ui import a11y
from tests.ui.harness import running_app

pytestmark = pytest.mark.e2e

SECTIONS = ["Overview", "Evidence", "Wiki", "References", "Graph", "Gaps", "Proposals", "Lab", "Trace", "Export"]
PAGES = ["Settings", "New analysis", "New project"]


@pytest.fixture
def app_url(tmp_path, monkeypatch):
    import utils.database as db
    monkeypatch.setenv("RESGAP_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv("RESGAP_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 30)
    db._INITIALIZED.clear()
    seed_run(golden_results(), comp_results=golden_comp())
    with running_app(tmp_path) as url:
        yield url


@pytest.mark.parametrize("width", list(a11y.WIDTHS))
def test_no_serious_accessibility_violations_and_no_horizontal_scroll(app_url, width):
    from playwright.sync_api import sync_playwright
    w, h = a11y.WIDTHS[width]
    problems, overflows = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h})
        # Prove the test needs no internet: anything that is not the local app is refused.
        page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(
            ("http://127.0.0.1", "http://localhost", "data:", "blob:")) else route.abort())
        page.goto(app_url)
        page.wait_for_selector("text=Papers Analysed", timeout=60000)
        a11y.inject_axe(page)                       # the vendored copy in tests/ui/vendor

        def check(label):
            problems.extend({**v, "screen": label} for v in a11y.ours(a11y.scan(page)))
            if a11y.horizontal_overflow(page) > 0:
                overflows.append(label)

        for name in SECTIONS:
            a11y.close_sidebar(page)
            page.get_by_text(name, exact=True).first.click()
            page.wait_for_timeout(1500)
            check(name)
        for name in PAGES:
            a11y.open_sidebar(page)
            page.get_by_role("button", name=name, exact=True).first.click()
            page.wait_for_timeout(1800)
            check(name)
            a11y.close_sidebar(page)
            back = page.get_by_role("button", name="Cancel" if name == "New analysis" else "← Back").first
            back.click()
            page.wait_for_timeout(1200)
        browser.close()
    assert problems == [], [(p["screen"], p["id"], p["sample"]) for p in problems[:6]]
    assert overflows == [], f"horizontal scroll on: {overflows}"
