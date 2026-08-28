"""Phase 5, Slice 14 -- the Data Quality screen, and one shared copy source.

Data Quality was deferred twice on the belief that "app.py computes per-paper
completeness as a local and never persists it, so there is nothing to show."
Half right: the per-paper FIELD grid genuinely was discarded (now saved by
pipeline/run_pipeline.py), but three substantial datasets -- the ADR-007
reference trust breakdown, per-paper reference extraction diagnostics, and
the corpus quality metrics -- were already written on every run and surfaced
nowhere. These checks read the real page, not fixtures.

Also verifies the API no longer serves the stale "runs only come from
Streamlit" empty state that Slice 12 fixed on the React side only.
"""
import sys
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

WEB_BASE = "http://localhost:3000"
API_BASE = "http://localhost:8000"
PROJECT = "Healthcare AI"
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL "), name, (f"- {detail}" if detail and not ok else ""))


def main():
    # --- API --------------------------------------------------------------
    body = requests.get(f"{API_BASE}/api/projects/{PROJECT}/quality", timeout=20).json()
    check("quality api: returns a real basis run", bool(body["basis_run"]))
    check("quality api: reference funnel is real data",
          len(body["reference_funnel"]) >= 5, str(len(body["reference_funnel"])))
    check("quality api: ADR-007 trust statuses are present",
          len(body["trust_statuses"]) == 5, str(len(body["trust_statuses"])))
    check("quality api: per-paper reference diagnostics are present",
          len(body["per_paper_references"]) > 0)

    # Every status carries its own icon and its own definition -- a count
    # like "QUARANTINED: 1" is meaningless without one.
    icons = [t["status"]["icon"] for t in body["trust_statuses"]]
    check("quality api: each trust status has a distinct icon",
          len(icons) == len(set(icons)), str(icons))
    check("quality api: each trust status explains what it means",
          all(len(t["status"]["reason"]) > 30 for t in body["trust_statuses"]))

    # A status the resolver never emitted must not be reported as a real 0.
    unrecorded = [t for t in body["trust_statuses"] if not t["recorded"]]
    check("quality api: a never-emitted status is 'not recorded', not zero",
          len(unrecorded) > 0 and bool(body["trust_note"]),
          f"{len(unrecorded)} unrecorded, note={bool(body['trust_note'])}")

    # No measure may be a bare number.
    check("quality api: every measure carries a basis and a source",
          all(m["basis"].strip() and m["source"].strip() for m in body["measures"]))
    check("quality api: unmeasured values say so instead of showing 0%",
          all(m["value"] is None and m["display"] == "Not recorded"
              for m in body["measures"] if not m["recorded"]))

    # --- the shared-copy fix ----------------------------------------------
    stale = "Runs created in the Streamlit workspace appear here automatically"
    endpoints = ["quality", "corpus", "evidence", "graph", "challenger", "council", "dashboard"]
    offenders = [
        e for e in endpoints
        if stale in requests.get(f"{API_BASE}/api/projects/does-not-exist/{e}", timeout=20).text
    ]
    check("api copy: no endpoint still serves the stale Streamlit-only sentence",
          offenders == [], str(offenders))
    empty = requests.get(f"{API_BASE}/api/projects/does-not-exist/quality", timeout=20).json()
    check("api copy: the empty state points at the web app's own New Run screen",
          "New Run" in (empty["empty_reason"] or ""), empty["empty_reason"])

    # --- the page ---------------------------------------------------------
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 500 else None)

        # Reachable by name without knowing a URL -- the whole reason the
        # previous "planned" marker was a problem is that nothing led here.
        # Slice 15: Data Quality is a workspace tab rather than its own
        # route. The check is unchanged in spirit -- it must be reachable by
        # name without knowing a URL -- only the mechanism moved.
        page.goto(f"{WEB_BASE}/workspace", wait_until="networkidle", timeout=30000)
        tab = page.get_by_role("tab", name="Data Quality")
        check("workspace: Data Quality is a real tab, not a 'Later' placeholder",
              tab.count() == 1)
        tab.first.click()
        page.wait_for_function("location.search.includes('tab=quality')", timeout=20000)

        page.wait_for_timeout(1200)
        text = page.inner_text("body")

        check("page: renders the quality gate with its reasons visible as text",
              "Quality gate" in text and "threshold" in text)
        check("page: the funnel contradiction is explained, not hidden",
              "counts different populations" in text or "not a strict narrowing" in text)
        check("page: trust statuses are labelled, not bare counts",
              "Verified" in text and "Quarantined" in text)
        check("page: per-paper reference extraction is shown",
              "LLM-structured" in text)
        # The one genuinely-absent dataset must explain itself rather than
        # render an empty section.
        check("page: the missing field grid states why it is missing",
              "discarded" in text or "cannot be backfilled" in text)

        page.screenshot(path=str(SCREENSHOT_DIR / "20_data_quality.png"), full_page=True)

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
