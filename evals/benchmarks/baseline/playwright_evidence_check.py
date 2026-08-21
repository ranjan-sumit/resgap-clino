"""Verify Stage 2C (evidence extraction) + Story 2.2.2 (report citation)
end-to-end via a real browser session against the live app."""
import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv(path: Path) -> None:
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
api_key = os.environ["NVIDIA_API_KEY"].strip()

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 1200})
    page.goto("http://localhost:8501", timeout=30000)
    page.wait_for_selector("text=Clinova", timeout=30000)
    print("App loaded.")

    page.fill('input[aria-label="NVIDIA API Key"]', api_key)
    page.locator('label:has-text("Corpus Quality Engine")').click()
    print("Quality Engine enabled.")

    file_input = page.locator('input[type="file"]').first
    file_input.set_input_files([
        str(REPO_ROOT / "Data-17072026" / "AuDHD_1.pdf"),
        str(REPO_ROOT / "Data-17072026" / "AuDHD_2.pdf"),
    ])
    page.wait_for_timeout(3000)

    page.get_by_role("button", name="Run Analysis").click()
    print("Run clicked, waiting for completion (up to 15 min)...")

    deadline = time.time() + 900
    completed = False
    while time.time() < deadline:
        page.wait_for_timeout(5000)
        body_text = page.inner_text("body")
        if "Pipeline error" in body_text:
            print("PIPELINE ERROR")
            page.screenshot(path=str(SCREENSHOT_DIR / "ERROR_evidence_run.png"))
            print(body_text[:3000])
            browser.close()
            raise SystemExit(1)
        if "Done —" in body_text:
            completed = True
            break

    if not completed:
        print("TIMED OUT waiting for pipeline completion")
        page.screenshot(path=str(SCREENSHOT_DIR / "TIMEOUT_evidence_run.png"))
        browser.close()
        raise SystemExit(1)

    print("PIPELINE COMPLETED.")

    # Click Export tab, generate the final report
    page.get_by_role("tab", name="Export").click()
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="Generate final report").click()
    print("Generating final report...")

    report_deadline = time.time() + 120
    report_ready = False
    while time.time() < report_deadline:
        page.wait_for_timeout(3000)
        if "Evidence" in page.inner_text("body") or page.locator("text=Download HTML").count() > 0:
            report_ready = True
            break

    page.screenshot(path=str(SCREENSHOT_DIR / "07_report_generated.png"), full_page=True)
    print("report_ready flag:", report_ready)

    browser.close()
    print("Done.")
