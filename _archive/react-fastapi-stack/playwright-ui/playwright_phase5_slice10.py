"""Phase 5, Slice 10 -- verifies the New Run screen: the web app can finally
start a pipeline run itself, which was the last real capability the Streamlit
app had and this one did not ("dont know how to start new run").

Deliberately does NOT start a real run -- that makes paid LLM calls and takes
minutes. What's verified is the whole surface around it: the screen exists, is
reachable from the nav, reports real providers/models, refuses to submit
without enough papers, and refuses a provider with no configured API key.
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
    # --- API pre-flight (no run started, nothing spent) -------------------
    cfg = requests.get(f"{API_BASE}/api/runs/new/config", timeout=15).json()
    check("api: config lists real providers", len(cfg["providers"]) >= 1)
    check("api: config reports per-provider key presence",
          all(isinstance(p["api_key_present"], bool) for p in cfg["providers"]))
    check("api: config states jobs are in-process and ephemeral",
          cfg["jobs_are_in_process"] and "restart" in cfg["jobs_note"].lower())

    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    r = requests.post(f"{API_BASE}/api/runs/new",
                      files=[("files", ("one.pdf", pdf, "application/pdf"))], timeout=20)
    check("api: one paper is rejected 400 with a real reason",
          r.status_code == 400 and "at least" in r.json()["detail"].lower(),
          f"got {r.status_code}")

    r = requests.get(f"{API_BASE}/api/jobs", timeout=15)
    check("api: /api/jobs listing does not collide with /api/runs/{run_id}",
          r.status_code == 200 and isinstance(r.json(), list), f"got {r.status_code}")

    # --- The screen itself ------------------------------------------------
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1200})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        page.goto(f"{WEB_BASE}/dashboard", wait_until="networkidle", timeout=25000)
        nav_link = page.locator("nav[aria-label='Primary'] a", has_text="New Run")
        check("nav: 'New Run' is a real sidebar link", nav_link.count() == 1)
        nav_link.first.click()
        page.wait_for_url("**/runs/new", timeout=15000)
        page.wait_for_load_state("networkidle")

        check("new run: has its own heading", page.locator("h1", has_text="New Run").count() > 0)
        check("new run: has a real upload dropzone", page.locator("text=Drop PDFs here").count() > 0)

        start = page.get_by_role("button", name="Start run")
        check("new run: Start is disabled with no papers", start.is_disabled())
        check("new run: says why it's disabled", page.locator("text=/Add at least \\d+ papers/").count() > 0)

        check("new run: lists real provider options",
              page.locator("select").nth(1).locator("option").count() >= 1)
        check("new run: discloses that a run costs real LLM calls",
              "real LLM calls" in page.inner_text("body"))
        check("new run: discloses in-process job caveat",
              "restart" in page.inner_text("body").lower())

        page.screenshot(path=str(SCREENSHOT_DIR / "17_new_run.png"), full_page=True)

        # Selecting a provider with no configured key must warn + block.
        no_key = [p for p in cfg["providers"] if not p["api_key_present"]]
        if no_key:
            page.select_option("select >> nth=1", no_key[0]["key"])
            page.wait_for_timeout(400)
            check("new run: warns when the chosen provider has no API key",
                  no_key[0]["api_key_env"] in page.inner_text("body"))
            check("new run: Start stays disabled without an API key",
                  page.get_by_role("button", name="Start run").is_disabled())
            page.screenshot(path=str(SCREENSHOT_DIR / "18_new_run_no_key.png"))

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
