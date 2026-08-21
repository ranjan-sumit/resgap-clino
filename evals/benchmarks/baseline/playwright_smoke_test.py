"""One-off Playwright smoke test driving the real Streamlit app in a browser
to verify the Corpus Quality Engine / reference-resolution wiring (Epic 1.2/
1.3 integration into app.py) actually works end-to-end, not just in unit
tests. Not part of the pytest suite -- a manual verification script, run
once per significant app.py change to this flow."""
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv(path: Path) -> None:
    import os
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() and k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip()


_load_dotenv(REPO_ROOT / ".env")
import os
api_key = os.environ["NVIDIA_API_KEY"].strip()

from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 1200})
    page.goto("http://localhost:8501", timeout=30000)
    page.wait_for_selector("text=Research Gap Analyzer", timeout=30000)
    print("App loaded.")

    # NVIDIA API key
    page.fill('input[aria-label="NVIDIA API Key"]', api_key)
    print("API key filled.")

    # Enable Corpus Quality Engine checkbox
    quality_checkbox = page.locator('label:has-text("Corpus Quality Engine")')
    quality_checkbox.click()
    print("Quality Engine checkbox clicked.")
    page.screenshot(path=str(SCREENSHOT_DIR / "01_after_checkbox.png"))

    # Upload the two real AuDHD papers (already Docling-cached from earlier
    # runs this session -- fast pass through Stage 2B)
    file_input = page.locator('input[type="file"]').first
    file_input.set_input_files([
        str(REPO_ROOT / "Data-17072026" / "AuDHD_1.pdf"),
        str(REPO_ROOT / "Data-17072026" / "AuDHD_2.pdf"),
    ])
    print("Files uploaded, waiting for upload to register...")
    page.wait_for_timeout(3000)
    page.screenshot(path=str(SCREENSHOT_DIR / "02_after_upload.png"))

    # Click the Run button
    run_button = page.get_by_role("button", name="Run Analysis")
    if run_button.count() == 0:
        # Fallback: dump visible button texts for debugging
        buttons = page.locator("button").all_inner_texts()
        print("Could not find 'Run Analysis' button. Visible buttons:", buttons)
        page.screenshot(path=str(SCREENSHOT_DIR / "ERROR_no_run_button.png"))
        browser.close()
        sys.exit(1)
    run_button.click()
    print("Run clicked. Waiting for pipeline to complete (this can take several minutes)...")

    # Poll for completion or error, up to 15 minutes (isolated parse+wiki+
    # graph+gaps alone measured ~4 minutes on 2026-08-21; full pipeline
    # with references/quality-engine/validation/proposals needs more room)
    deadline = time.time() + 900
    last_status = ""
    while time.time() < deadline:
        page.wait_for_timeout(5000)
        body_text = page.inner_text("body")
        if "Pipeline error" in body_text:
            print("PIPELINE ERROR DETECTED")
            page.screenshot(path=str(SCREENSHOT_DIR / "ERROR_pipeline_error.png"))
            # Try to expand error details
            try:
                page.get_by_text("Error details").click()
                page.wait_for_timeout(500)
                page.screenshot(path=str(SCREENSHOT_DIR / "ERROR_pipeline_error_expanded.png"))
            except Exception:
                pass
            print(page.inner_text("body")[:3000])
            browser.close()
            sys.exit(1)
        if "Done —" in body_text or "gaps," in body_text and "proposals." in body_text:
            print("PIPELINE COMPLETED SUCCESSFULLY")
            break
        # Print progress indicator if changed
        for marker in ("Stage 1C", "Stage 2B", "Stage 3", "Stage 4", "Stage 5", "Stage 6"):
            if marker in body_text and marker != last_status:
                print(f"  ...saw {marker}")
                last_status = marker

    page.screenshot(path=str(SCREENSHOT_DIR / "03_final_state.png"), full_page=True)
    console_errors = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

    body_text = page.inner_text("body")
    print("\n--- Looking for Stage 1C / Stage 2B trace entries in final page text ---")
    for marker in ("Stage 1C", "Stage 2B", "Reference Resolution", "Corpus Quality Engine"):
        print(f"  {marker!r} present: {marker in body_text}")

    browser.close()
    print("\nDone. Screenshots in", SCREENSHOT_DIR)
