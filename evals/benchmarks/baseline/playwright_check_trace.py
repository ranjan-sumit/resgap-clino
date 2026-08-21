"""Follow-up: load the just-completed run from Run History and inspect the
Pipeline Trace tab for the Stage 1C / Stage 2B entries."""
from pathlib import Path
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 1200})
    page.goto("http://localhost:8501", timeout=30000)
    page.wait_for_selector("text=Research Gap Analyzer", timeout=30000)

    # Click the most recent run in Run History (the one we just produced)
    page.get_by_role("button", name="Healthcare AI", exact=False).first.click()
    page.wait_for_timeout(3000)
    page.screenshot(path=str(SCREENSHOT_DIR / "04_loaded_run.png"))

    # Click the "Pipeline Trace" tab
    trace_tab = page.get_by_role("tab", name="Pipeline Trace")
    if trace_tab.count() == 0:
        trace_tab = page.locator('text="Pipeline Trace"')
    trace_tab.first.click()
    page.wait_for_timeout(1500)
    page.screenshot(path=str(SCREENSHOT_DIR / "05_pipeline_trace.png"), full_page=True)

    body_text = page.inner_text("body")
    for marker in ("Stage 1C", "Stage 2B", "Reference Resolution", "Corpus Quality Engine",
                   "extraction completeness", "DOI resolution", "trusted"):
        print(f"  {marker!r} present: {marker in body_text}")

    browser.close()
    print("Done.")
