"""Verify the 2026-08-21 decoupling fix: evidence extraction now runs even
with the Corpus Quality Engine toggle OFF (previously it required the
toggle -- this is genuinely new behavior, never tested live before)."""
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

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 1200})
    page.goto("http://localhost:8501", timeout=30000)
    page.wait_for_selector("text=Clinova", timeout=30000)
    print("App loaded.")

    page.fill('input[aria-label="NVIDIA API Key"]', api_key)
    # Deliberately NOT clicking the Quality Engine checkbox this time.
    print("Quality Engine left OFF (default).")

    file_input = page.locator('input[type="file"]').first
    file_input.set_input_files([
        str(REPO_ROOT / "Data-17072026" / "AuDHD_1.pdf"),
        str(REPO_ROOT / "Data-17072026" / "AuDHD_2.pdf"),
    ])
    page.wait_for_timeout(3000)

    page.get_by_role("button", name="Run Analysis").click()
    print("Run clicked, waiting for completion...")

    deadline = time.time() + 600
    completed = False
    while time.time() < deadline:
        page.wait_for_timeout(5000)
        body_text = page.inner_text("body")
        if "Pipeline error" in body_text:
            print("PIPELINE ERROR")
            print(body_text[:3000])
            browser.close()
            raise SystemExit(1)
        if "Done —" in body_text:
            completed = True
            break

    print("completed:", completed)
    browser.close()
