"""The sidebar behaves on a phone: closed on arrival, closed again after a choice, untouched on a desktop.
Runs fully offline (a local Chromium and the local app)."""
import pytest

from tests.fixtures.make_golden_run import golden_results, seed_run
from tests.ui import a11y
from tests.ui.harness import running_app

pytestmark = pytest.mark.e2e


@pytest.fixture
def app_url(tmp_path, monkeypatch):
    import utils.database as db
    monkeypatch.setenv("RESGAP_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv("RESGAP_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 30)
    db._INITIALIZED.clear()
    seed_run(golden_results())
    with running_app(tmp_path) as url:
        yield url


def _expanded(page) -> str:
    return page.evaluate("() => document.querySelector('[data-testid=stSidebar]').getAttribute('aria-expanded')")


def _offline(page):
    page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(
        ("http://127.0.0.1", "http://localhost", "data:", "blob:")) else route.abort())


def test_phone_sidebar_starts_closed_and_closes_after_choosing_a_page(app_url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        _offline(page)
        page.goto(app_url)
        page.wait_for_selector("text=Papers Analysed", timeout=60000)
        assert _expanded(page) == "false"                              # nothing covers the results on arrival
        a11y.open_sidebar(page)
        assert _expanded(page) == "true"
        page.get_by_role("button", name="Settings", exact=True).first.click()
        page.wait_for_selector("text=API keys", timeout=30000)
        page.wait_for_function(
            "() => document.querySelector('[data-testid=stSidebar]').getAttribute('aria-expanded') === 'false'",
            timeout=10000)                                             # closed itself: the page just chosen is visible
        browser.close()


def test_desktop_sidebar_stays_open(app_url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        _offline(page)
        page.goto(app_url)
        page.wait_for_selector("text=Papers Analysed", timeout=60000)
        assert _expanded(page) == "true"
        page.get_by_role("button", name="Settings", exact=True).first.click()
        page.wait_for_selector("text=API keys", timeout=30000)
        page.wait_for_timeout(1000)
        assert _expanded(page) == "true"                                # untouched on a wide screen
        browser.close()
