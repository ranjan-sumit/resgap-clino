"""Phase 5, Slice 8 -- verifies the Report Download menu on Run Detail:
a real download surface (HTML/PDF/Markdown/JSON) for utils/export.py's
existing report builders, which the web app had no access to before this
slice -- a genuine Streamlit-parity gap (app.py already exposed all four
formats via st.download_button).
"""
import sys
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

WEB_BASE = "http://localhost:3000"
API_BASE = "http://localhost:8000"
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL "), name, (f"- {detail}" if detail and not ok else ""))


def main():
    runs = requests.get(f"{API_BASE}/api/runs?limit=1", timeout=10).json()["runs"]
    if not runs:
        print("No real runs available -- cannot verify.")
        return 1
    run_id = runs[0]["run_id"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1200})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        page.goto(f"{WEB_BASE}/runs/{run_id}", wait_until="networkidle", timeout=20000)
        check("run detail: 'Download report' button present", page.locator("text=Download report").count() > 0)

        page.locator("text=Download report").click()
        page.wait_for_timeout(300)
        page.screenshot(path=str(SCREENSHOT_DIR / "14_report_menu_open.png"))

        for label in ["HTML report", "PDF report", "Markdown", "Raw JSON"]:
            check(f"report menu: '{label}' option present", page.locator(f"text={label}").count() > 0)

        html_link = page.locator("a", has_text="HTML report")
        href = html_link.get_attribute("href")
        check("report menu: HTML link points at the real report endpoint", href is not None and "/report?format=html" in href)

        # Fetch the actual href directly (a real click triggers a browser
        # download, which Playwright can't easily inspect) -- confirms the
        # link the user would click is genuinely wired to real content.
        resp = requests.get(href, timeout=15)
        check("report link: returns 200 with real HTML content", resp.status_code == 200 and "Research Gap Analysis Report" in resp.text)
        check("report link: has a real download filename", "attachment" in resp.headers.get("content-disposition", ""))

        check("no page errors", len(errors) == 0, "; ".join(errors))

        browser.close()

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    if failed:
        print("\nFailed checks:")
        for name, _, detail in failed:
            print(f"  - {name}" + (f" ({detail})" if detail else ""))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
