"""Phase 5, Slice 11 -- global content search + knowledge-graph image export.

Search: the command palette could previously only find nav labels and run
names. It now searches real research content (papers, entities, gaps,
proposals) via the API, grouped by kind.

Export: the knowledge graph can be downloaded as PNG or SVG for slides and
papers -- verified by actually performing the downloads and checking the
bytes, not just that a button exists.
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
    # --- Search API -------------------------------------------------------
    body = requests.get(f"{API_BASE}/api/projects/{PROJECT}/search",
                        params={"q": "depression"}, timeout=20).json()
    check("search api: finds real content", body["total"] > 0, f"{body['total']} hits")
    kinds = {h["kind"] for h in body["hits"]}
    check("search api: spans multiple content kinds",
          len(kinds & {"paper", "entity", "gap", "proposal"}) >= 2, str(kinds))
    check("search api: every hit has a real href and a matched_on reason",
          all(h["href"].startswith("/") and h["matched_on"] for h in body["hits"]))
    scores = [h["score"] for h in body["hits"]]
    check("search api: results are ranked", scores == sorted(scores, reverse=True))

    empty = requests.get(f"{API_BASE}/api/projects/{PROJECT}/search",
                         params={"q": "zzzznotarealterm"}, timeout=20).json()
    check("search api: no-match says so honestly",
          empty["total"] == 0 and empty["empty_reason"])

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        # --- Palette content search --------------------------------------
        page.goto(f"{WEB_BASE}/dashboard", wait_until="networkidle", timeout=30000)
        page.keyboard.press("Control+k")
        page.wait_for_timeout(400)
        page.keyboard.type("depression")
        page.wait_for_timeout(1500)

        # Group headers are uppercased by CSS, so compare case-insensitively.
        text = page.inner_text("body").lower()
        for group in ("entities", "gaps", "proposals"):
            check(f"palette: '{group}' group rendered", group in text)
        check("palette: shows a real matched entity", "depression" in text)
        page.screenshot(path=str(SCREENSHOT_DIR / "19_palette_search.png"))

        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(200)
        page.keyboard.press("Enter")
        page.wait_for_timeout(2500)
        check("palette: selecting a content hit navigates",
              page.url.rstrip("/") != f"{WEB_BASE}/dashboard", page.url)

        # --- Graph image export ------------------------------------------
        page.goto(f"{WEB_BASE}/knowledge-graph", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(4500)

        for label, ext, min_bytes in [("SVG", "svg", 2000), ("PNG", "png", 10000)]:
            with page.expect_download(timeout=20000) as dl:
                page.get_by_role("button", name=label, exact=True).click()
            download = dl.value
            out = SCREENSHOT_DIR / f"graph_export_check.{ext}"
            download.save_as(str(out))
            size = out.stat().st_size
            check(f"graph export: {label} downloads real content",
                  download.suggested_filename.endswith(f".{ext}") and size > min_bytes,
                  f"{download.suggested_filename} {size}B")
            out.unlink(missing_ok=True)

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
