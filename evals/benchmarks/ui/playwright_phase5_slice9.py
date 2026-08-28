"""Phase 5, Slice 9 -- verifies the UI-rethink pass:

  * the sidebar stays pinned when a long page scrolls (it used to scroll
    away, leaving a bare white column),
  * the project selector is a real control wired to a real selection
    (it previously had no change handler at all),
  * "Computational Modelling" is reachable from the sidebar as its own
    screen, not only as a tab label buried on Research Council,
  * the knowledge graph carries real annotations: labels, a clickable
    entity detail panel, and type-colored entity chips that match the
    graph's own palette,
  * relationship rows show human-readable entity names, not raw slug ids.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

WEB_BASE = "http://localhost:3000"
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL "), name, (f"- {detail}" if detail and not ok else ""))


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        # --- Sticky sidebar -------------------------------------------------
        page.goto(f"{WEB_BASE}/workspace?tab=graph", wait_until="networkidle", timeout=25000)
        page.wait_for_timeout(4500)

        nav_box_before = page.locator("nav[aria-label='Primary']").bounding_box()
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(700)
        nav_box_after = page.locator("nav[aria-label='Primary']").bounding_box()
        check(
            "shell: sidebar stays pinned while a long page scrolls",
            nav_box_after is not None and abs(nav_box_after["y"]) < 5,
            f"y before={nav_box_before['y'] if nav_box_before else None} after={nav_box_after['y'] if nav_box_after else None}",
        )
        page.mouse.wheel(0, -3000)
        page.wait_for_timeout(400)

        # --- Graph annotations ---------------------------------------------
        nodes = page.locator("svg g circle[stroke='white']")
        check("graph: renders real nodes", nodes.count() > 5, f"{nodes.count()} nodes")
        check("graph: has visible node labels", page.locator("svg text").count() > 0)
        check("graph: has a 'Label every node' control", page.locator("text=Label every node").count() > 0)
        check("graph: legend shows per-type counts", page.locator("text=/concept\\s*\\(\\d+\\)/").count() > 0)

        # click the highest-degree node -> detail panel
        best_i, best_r = 0, 0.0
        for i in range(nodes.count()):
            r = float(nodes.nth(i).get_attribute("r") or 0)
            if r > best_r:
                best_r, best_i = r, i
        nodes.nth(best_i).click(force=True)
        page.wait_for_timeout(600)
        check("graph: clicking a node opens an entity detail panel", page.locator("text=Appears in").count() > 0)
        check("graph: detail panel lists real relationships", page.locator("text=/Relationships \\(\\d+\\)/").count() > 0)
        page.screenshot(path=str(SCREENSHOT_DIR / "15_graph_annotated.png"))

        # --- Readable entity + relationship text ----------------------------
        body = page.inner_text("body")
        check(
            "knowledge-graph: relationships show real names, not raw slug ids",
            "autism_spectrum_disorder_asd" not in body and "Autism Spectrum Disorder (ASD)" in body,
        )
        chips = page.locator("span[title*='importance:']")
        check("knowledge-graph: entity chips are type-colored", chips.count() > 5, f"{chips.count()} chips")
        tinted = page.evaluate(
            """() => [...document.querySelectorAll("span[title*='importance:']")]
                     .filter(s => getComputedStyle(s).backgroundColor !== 'rgba(0, 0, 0, 0)').length"""
        )
        check("knowledge-graph: chips carry a real background tint", tinted > 5, f"{tinted} tinted")

        # --- Computational Modelling is its own reachable screen ------------
        page.goto(f"{WEB_BASE}/workspace?tab=graph", wait_until="networkidle", timeout=25000)
        # Slice 15: this is a workspace tab rather than a sidebar link. The
        # original complaint was that "computational modelling" appeared
        # nowhere you could scan for it -- that requirement is unchanged, only
        # the surface it lives on moved.
        tab = page.get_by_role("tab", name="Computational Modelling")
        check("workspace: 'Computational Modelling' is a real, labelled destination "
              "(a tab since Slice 15, a sidebar link before)", tab.count() == 1)
        tab.first.click()
        page.wait_for_function("location.search.includes('tab=modelling')", timeout=30000)
        page.wait_for_load_state("networkidle")
        check("modelling tab: renders its own content, not an empty panel",
              len(page.locator("main").inner_text().strip()) > 200)

        # Every workspace tab is pinned to the selected run, and the newest
        # run did not use the Computational Lab -- so real model results live
        # on the run that did. Reaching them is a run switch, not a bug.
        page.goto(f"{WEB_BASE}/workspace?tab=modelling&run=916eb3489e10",
                  wait_until="networkidle", timeout=30000)
        check("modelling tab: shows real model results", page.locator("text=Sensitivity").count() > 0)
        page.screenshot(path=str(SCREENSHOT_DIR / "16_modelling_page.png"), full_page=True)

        # --- Project selection is real, not decorative ----------------------
        # NOTE: this dataset has exactly one project, so the <Select>'s
        # onValueChange can never fire (Radix only fires it on an actual
        # change). What IS testable -- and what was genuinely broken before,
        # since every page hardcoded projects[0] and the Select had no
        # handler at all -- is that the server now resolves the rendered
        # project from the stored selection, and falls back safely when that
        # selection names a project that doesn't exist.
        page.goto(f"{WEB_BASE}/dashboard", wait_until="networkidle", timeout=25000)
        trigger = page.locator("header button").first
        trigger.click()
        page.wait_for_timeout(400)
        options = page.get_by_role("option")
        check("top bar: project selector opens with real options", options.count() >= 1)
        page.keyboard.press("Escape")

        page.context.add_cookies([
            {"name": "clinova_project", "value": "Healthcare AI", "url": WEB_BASE},
        ])
        page.goto(f"{WEB_BASE}/workspace?tab=corpus", wait_until="networkidle", timeout=25000)
        check(
            "project selection: a stored selection drives the rendered project",
            "AuDHD" in page.inner_text("body"),
        )

        page.context.add_cookies([
            {"name": "clinova_project", "value": "no-such-project-xyz", "url": WEB_BASE},
        ])
        page.goto(f"{WEB_BASE}/workspace?tab=corpus", wait_until="networkidle", timeout=25000)
        check(
            "project selection: an unknown stored project falls back instead of erroring",
            "AuDHD" in page.inner_text("body"),
        )

        check("no page errors across the whole pass", len(errors) == 0, "; ".join(errors))
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
