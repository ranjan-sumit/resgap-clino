"""UI-14: the key screens at three widths against approved screenshots (nightly; needs Chromium).

Approve a deliberate change:   set UPDATE_BASELINES=1, run this file, then LOOK at the changed pictures in tests/ui/_baselines/<platform>/
before committing them. A platform with no baselines yet skips.
"""
import shutil

import pytest

from tests.fixtures.make_golden_run import golden_comp, golden_results, seed_run
from tests.ui import a11y, visual
from tests.ui.harness import running_app

pytestmark = pytest.mark.e2e

# section -> text that only that section shows. A picture is taken after it appears, never while the previous section is
# still on screen (Streamlit keeps the old one, faded, until the new one is drawn).
READY = {"Overview": "Top gaps", "Gaps": "Research gaps", "Proposals": "Research proposals",
         "Evidence": "Every item the reader extracted", "Graph": "How to read this graph", "Wiki": "Compiled wiki pages",
         "Lab": "Computational lab", "Trace": "Pipeline trace", "Export": "Export results"}
# A text match is a substring match unless exact: "Research gaps" is also inside the group note ("...the research gaps, and
# the proposals..."), which is on screen before the section has changed, so it must be matched exactly.
EXACT = {"Overview", "Gaps", "Proposals", "Graph", "Wiki", "Export"}
SECTIONS = list(READY)


def _marker(page, name: str):
    return page.get_by_text(READY[name], exact=name in EXACT).first
_OTHER_KEYS = ("NVIDIA_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "DASHSCOPE_API_KEY", "CUSTOM_LLM_API_KEY",
               "CUSTOM_LLM_BASE_URL", "SEMANTIC_SCHOLAR_API_KEY", "OPENALEX_API_KEY")


@pytest.fixture
def app_url(tmp_path, monkeypatch):
    """The app on a synthetic project, with exactly one provider key so the planner looks the same on every machine."""
    import utils.database as db
    for k in _OTHER_KEYS:
        monkeypatch.setenv(k, "")                        # "" (not absent) stops the app's .env loader filling them in
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 30)
    monkeypatch.setenv("RESGAP_DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setenv("RESGAP_PROJECTS_DIR", str(tmp_path / "projects"))
    db._INITIALIZED.clear()
    seed_run(golden_results(), comp_results=golden_comp())
    with running_app(tmp_path) as url:
        yield url


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-").replace(":", "")


def _open_settings_models(page) -> None:
    a11y.open_sidebar(page)
    page.get_by_role("button", name="Settings", exact=True).first.click()
    page.wait_for_timeout(1500)
    a11y.close_sidebar(page)
    page.get_by_role("tab", name="Models").click()
    page.wait_for_selector("text=Run planner", timeout=30000)


@pytest.mark.parametrize("viewport", list(visual.VIEWPORTS))
def test_key_screens_match_their_approved_screenshots(app_url, viewport):
    from playwright.sync_api import sync_playwright
    w, h = visual.VIEWPORTS[viewport]
    failures, missing = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": w, "height": h})
        page.goto(app_url)
        page.wait_for_selector("text=Papers Analysed", timeout=60000)
        page.add_style_tag(content=visual.FREEZE_CSS)

        def check(name: str) -> None:
            a11y.settled(page)
            page.wait_for_function("() => document.querySelectorAll('[class*=\"Skeleton\"]').length === 0", timeout=30000)
            # Where the page is scrolled depends on what was clicked last; every picture starts from the top.
            page.evaluate("() => { const m = document.querySelector('[data-testid=\"stMain\"]'); if (m) m.scrollTop = 0; window.scrollTo(0, 0); }")
            page.wait_for_timeout(1200)
            slug = _slug(name)
            actual = visual.ARTIFACTS / "actual" / viewport / f"{slug}.png"
            actual.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(actual))
            baseline = visual.BASELINES / viewport / f"{slug}.png"
            if visual.UPDATE:
                baseline.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(actual, baseline)
            elif not baseline.exists():
                missing.append(slug)
            else:
                ok, share = visual.compare(actual, baseline)
                if not ok:
                    visual.save_side_by_side(actual, baseline, visual.ARTIFACTS / "diff" / viewport / f"{slug}.png")
                    failures.append(f"{slug}: {share:.2%} of pixels changed")

        previous = None
        for name in SECTIONS:
            a11y.close_sidebar(page)
            a11y.open_section(page, name)
            _marker(page, name).wait_for(timeout=60000)                    # the new section is drawn ...
            if previous:
                _marker(page, previous).wait_for(state="hidden", timeout=60000)   # ... and the old one is gone
            previous = name
            if name == "Graph":
                page.wait_for_selector(".js-plotly-plot", timeout=30000)
            check(name)
        _open_settings_models(page)
        check("Settings: Models")
        browser.close()
    if visual.UPDATE:
        return
    assert not failures, "screens changed (see tests/ui/_artifacts/diff): " + "; ".join(failures)
    if missing:
        pytest.skip(f"no {visual.PLATFORM} baselines for {viewport} yet ({len(missing)} screens): run with UPDATE_BASELINES=1")
