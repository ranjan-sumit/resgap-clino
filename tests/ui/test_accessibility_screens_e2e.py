"""UI-14: axe-core on the screens the main accessibility test does not reach: every Settings tab and every step of the
New analysis wizard, at a desktop and a phone width (nightly; needs Chromium).

A screen that is known to fail is a ratchet: KNOWN lists the rule ids it breaks today, a NEW id fails, and a fixed one fails
until it is removed from KNOWN (the later UI PRs remove them).
"""
import pytest

from tests.fixtures.make_golden_run import golden_comp, golden_results, seed_run
from tests.ui import a11y
from tests.ui.harness import running_app

pytestmark = pytest.mark.e2e

SETTINGS_TABS = ["API keys", "Models", "Analysis defaults", "Saved results", "Backup", "Audit log"]
# screen -> serious or critical axe rule ids it breaks today. Everything not listed must be clean.
KNOWN: dict[str, set[str]] = {
    "settings: Analysis defaults": {"color-contrast"},     # F48: the disabled "References per paper" label (UI-09)
    "settings: Audit log": {"color-contrast"},             # F47: the green "Intact" message (UI-09)
    "wizard: 3 options": {"color-contrast"},               # F48 again: the same disabled label in the wizard's options step (UI-09)
}
WIDTHS = {"desktop": (1440, 900), "phone": (390, 844)}


@pytest.fixture
def app_url(tmp_path, monkeypatch):
    import utils.database as db
    from tests.test_unreadable_pdfs import _text_pdf
    from utils import project_store
    monkeypatch.setenv("RESGAP_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv("RESGAP_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 30)
    db._INITIALIZED.clear()
    project_store.save_papers(db.DEFAULT_PROJECT_ID, [(f"p{i}.pdf", _text_pdf(f"x{i}")) for i in range(2)])
    seed_run(golden_results(), comp_results=golden_comp())
    with running_app(tmp_path) as url:
        yield url


@pytest.mark.parametrize("width", list(WIDTHS))
def test_settings_tabs_and_wizard_steps_have_only_the_known_accessibility_violations(app_url, width):
    from playwright.sync_api import sync_playwright
    w, h = WIDTHS[width]
    found: dict[str, set[str]] = {}
    overflow: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h})
        page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(
            ("http://127.0.0.1", "http://localhost", "data:", "blob:")) else route.abort())
        page.goto(app_url)
        page.wait_for_selector("text=Papers Analysed", timeout=60000)
        a11y.inject_axe(page)

        def check(label: str) -> None:
            found[label] = {v["id"] for v in a11y.ours(a11y.scan(page))}
            if a11y.horizontal_overflow(page) > 0:
                overflow.append(label)

        # Settings, one tab at a time
        a11y.open_sidebar(page)
        page.get_by_role("button", name="Settings", exact=True).first.click()
        page.wait_for_timeout(1500)
        a11y.close_sidebar(page)
        for tab in SETTINGS_TABS:
            page.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(1800)
            check(f"settings: {tab}")
        page.get_by_role("button", name="Back").first.click()
        page.wait_for_selector("text=Papers Analysed", timeout=30000)

        # the wizard, step by step
        a11y.open_sidebar(page)
        page.get_by_role("button", name="New analysis", exact=True).first.click()
        page.wait_for_selector("text=Add 2", timeout=30000)
        a11y.close_sidebar(page)
        check("wizard: 1 papers")
        for label in ("p0.pdf", "p1.pdf"):
            page.locator("[data-testid=stCheckbox]").filter(has_text=label).first.locator("label").click()
        page.wait_for_selector("text=2 paper(s) selected", timeout=15000)
        for step, waits_for in (("2 setup", "text=Research interest"), ("3 options", "text=Include cited references"),
                                ("4 review", "text=Papers (2)")):
            page.get_by_role("button", name="Next").first.click()
            page.wait_for_selector(waits_for, timeout=30000)
            page.wait_for_timeout(1200)
            check(f"wizard: {step}")
        browser.close()
    new = {s: sorted(ids - KNOWN.get(s, set())) for s, ids in found.items() if ids - KNOWN.get(s, set())}
    fixed = {s: sorted(KNOWN[s] - found.get(s, set())) for s in KNOWN if KNOWN[s] - found.get(s, set())}
    assert not new, f"new accessibility violations: {new}"
    assert not fixed, f"fixed, so remove from KNOWN: {fixed}"
    assert overflow == [], f"horizontal scroll on: {overflow}"
