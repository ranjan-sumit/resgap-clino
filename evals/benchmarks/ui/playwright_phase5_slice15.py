"""Phase 5, Slice 15 -- re-converging the workspace, after a direct
comparison against Streamlit.

Your verdict was "streamlit was more cleaner, not liking this react, not user
friendly." Screenshotting both at 1440x900 showed you were right and named
why: Streamlit fits its run banner, upload, Run Analysis button, nine stats
AND its full tab bar above the fold, with run history always in the sidebar.
The React app had split one workspace across nineteen routes, so every
cross-reference cost a full navigation, and four of the five confidence tiles
on its landing screen said "Not recorded" over a four-line justification --
absence given more room than presence.

These checks pin the fixes: one tabbed workspace, a run switcher that moves
every tab at once, and the density that made the tab bar reachable.
"""
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

WEB_BASE = "http://localhost:3000"
API_BASE = "http://localhost:8000"
PROJECT = "Healthcare AI"
VIEWPORT = {"width": 1440, "height": 900}
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL "), name, (f"- {detail}" if detail and not ok else ""))


def main():
    runs = requests.get(f"{API_BASE}/api/run-options", params={"limit": 25}, timeout=30).json()
    project_runs = [r for r in runs if r["project_id"] == PROJECT]
    check("api: run-options returns the project's runs", len(project_runs) >= 2, str(len(project_runs)))
    newest, older = project_runs[0], project_runs[1]

    # --- the run switcher is real, and it moves every tab -------------------
    for path in ("corpus", "evidence", "graph", "quality", "workspace"):
        body = requests.get(f"{API_BASE}/api/projects/{PROJECT}/{path}",
                            params={"run_id": older["run_id"]}, timeout=30).json()
        check(f"api: {path} honours the pinned run",
              body["basis_run"]["run_id"] == older["run_id"], body["basis_run"]["run_id"])

    latest_note = requests.get(f"{API_BASE}/api/projects/{PROJECT}/corpus", timeout=30).json()["basis_note"]
    pinned_note = requests.get(f"{API_BASE}/api/projects/{PROJECT}/corpus",
                               params={"run_id": older["run_id"]}, timeout=30).json()["basis_note"]
    check("api: the basis note stops claiming 'most recent' when it is not",
          "most recent run" in latest_note and "most recent run" not in pinned_note, pinned_note)

    # --- the slim endpoints exist because the heavy ones were the fold ------
    t0 = time.perf_counter()
    requests.get(f"{API_BASE}/api/projects/{PROJECT}/workspace", timeout=60)
    header_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    requests.get(f"{API_BASE}/api/projects/{PROJECT}/dashboard", timeout=60)
    dash_s = time.perf_counter() - t0
    check("api: the workspace header is cheaper than the full dashboard",
          header_s < dash_s, f"header {header_s:.2f}s vs dashboard {dash_s:.2f}s")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 500 else None)

        page.goto(f"{WEB_BASE}/workspace", wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(1200)

        # --- density: the whole point of the comparison --------------------
        tabs = page.get_by_role("tab")
        check("workspace: all nine sections are tabs on one screen",
              tabs.count() == 9, str(tabs.count()))
        box = page.get_by_role("tablist").bounding_box()
        check("workspace: the tab bar is above the fold (Streamlit's was at ~863px)",
              box is not None and box["y"] < VIEWPORT["height"], str(box["y"] if box else None))

        # --- the primary verb is visible, as it was in Streamlit -----------
        check("workspace: 'Run analysis' is on the screen, not buried in nav",
              page.get_by_role("link", name="Run analysis").count() == 1)

        # --- unmeasured confidence is disclosed, not dominant --------------
        body_text = page.inner_text("body")
        check("workspace: unmeasured confidence is collapsed behind a disclosure",
              "confidence measures not recorded" in body_text)
        # Collapsed, NOT deleted -- every reason is still one click away.
        page.locator("summary", has_text="not recorded").first.click()
        page.wait_for_timeout(300)
        check("workspace: opening the disclosure still shows every real reason",
              "Gap Challenger stage" in page.inner_text("body")
              or "was not enabled" in page.inner_text("body"))

        # --- switching runs keeps the tab you were reading ------------------
        page.goto(f"{WEB_BASE}/workspace?tab=gaps", wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(1000)
        page.get_by_role("navigation", name="Primary").get_by_text(older["name"]).first.click()
        page.wait_for_function("location.search.includes('run=')", timeout=60000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)
        check("workspace: switching runs keeps the current tab",
              "tab=gaps" in page.url, page.url)
        check("workspace: switching runs changes the run on screen",
              older["name"] in page.inner_text("main"))
        check("workspace: the switched-to tab stays selected",
              page.get_by_role("tab", name="Research Gaps").get_attribute("aria-selected") == "true")

        # --- the run switcher itself ---------------------------------------
        nav = page.get_by_role("navigation", name="Primary")
        check("sidebar: run history is always visible",
              nav.get_by_text("Run history").count() == 1)
        check("sidebar: each run carries enough preview to tell them apart",
              f"{newest['n_papers']}p" in nav.inner_text() and f"{newest['n_gaps']}g" in nav.inner_text())

        # --- nothing that used to work may 404 ------------------------------
        for legacy, expected_tab in [
            ("/corpus", "tab=corpus"), ("/gaps", "tab=gaps"), ("/knowledge-graph", "tab=graph"),
            ("/quality", "tab=quality"), ("/evidence", "tab=evidence"), ("/proposals", "tab=proposals"),
            ("/gap-challenger", "tab=challenger"), ("/council", "tab=council"),
            ("/council/modelling", "tab=modelling"),
        ]:
            page.goto(f"{WEB_BASE}{legacy}", wait_until="domcontentloaded", timeout=90000)
            check(f"legacy route {legacy} redirects into the workspace",
                  expected_tab in page.url, page.url)

        # --- per-tab browser titles, which the nine routes gave for free ----
        page.goto(f"{WEB_BASE}/workspace?tab=graph", wait_until="domcontentloaded", timeout=90000)
        check("workspace: the browser tab names the section, not just 'Workspace'",
              page.title().startswith("Knowledge Graph"), page.title())

        # --- the palette must still find screens that became tabs -----------
        page.goto(f"{WEB_BASE}/workspace", wait_until="networkidle", timeout=90000)
        page.keyboard.press("Control+k")
        page.wait_for_timeout(500)
        palette_input = page.locator('[role="dialog"] input').first
        for term, label in [("corpus", "Corpus"), ("knowledge", "Knowledge Graph"),
                             ("quality", "Data Quality")]:
            palette_input.fill(term)
            page.wait_for_timeout(700)
            check(f"palette: still finds '{label}' after it became a tab",
                  label in page.locator('[role="dialog"]').inner_text())

        page.goto(f"{WEB_BASE}/workspace?tab=gaps", wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(1000)
        page.screenshot(path=str(SCREENSHOT_DIR / "21_workspace_tabs.png"))

        check("no page errors", len(errors) == 0, "; ".join(errors[:3]))
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
