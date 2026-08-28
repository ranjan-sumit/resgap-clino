"""Phase 5, Slice 6 -- verifies the two fixes for "there is no knowledge
graph visual available" and "dont know where is computaional modelling":
a real force-directed graph on /knowledge-graph, and a "Computational
modelling" tab (active by default) on /council.
"""
import sys

from playwright.sync_api import sync_playwright

WEB_BASE = "http://localhost:3000"
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL "), name, (f"- {detail}" if detail and not ok else ""))


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1200})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        # --- Knowledge Graph: real force-directed visual, not just lists ---
        page.goto(f"{WEB_BASE}/workspace?tab=graph", wait_until="networkidle", timeout=20000)
        check("knowledge-graph: 'Graph explorer' section present", page.locator("text=Graph explorer").count() > 0)
        page.wait_for_timeout(4200)  # let the force simulation settle
        node_count = page.locator("svg circle[stroke='white']").count()
        check("knowledge-graph: force graph renders real nodes", node_count > 5, f"{node_count} nodes")
        edge_count = page.locator("svg line").count()
        check("knowledge-graph: force graph renders real edges", edge_count > 5, f"{edge_count} edges")
        legend_types = page.locator("text=concept").count()
        check("knowledge-graph: color legend present", legend_types > 0)

        # hover interaction actually dims unrelated nodes
        first_circle = page.locator("svg circle[stroke='white']").first
        first_circle.hover(force=True)
        page.wait_for_timeout(200)
        dimmed = page.evaluate(
            "() => [...document.querySelectorAll('svg g[opacity]')].some(g => parseFloat(g.getAttribute('opacity')) < 1)"
        )
        check("knowledge-graph: hover highlight dims unrelated nodes", dimmed)

        # --- Research Council: Computational modelling is an unmissable tab ---
        # Slice 15 pins every workspace tab to the selected run, and the
        # newest run did not use the Computational Lab -- so this opens the
        # run that did, which is the run the empty state now names.
        page.goto(f"{WEB_BASE}/workspace?tab=council&run=916eb3489e10",
                  wait_until="networkidle", timeout=30000)
        # Slice 15 removed the council's INNER tab pair. Modelling is a
        # workspace tab in its own right now, so keeping a second tab with
        # the same label on the same screen was the very confusion the
        # top-level tab existed to fix. Council renders findings directly and
        # links across; the original requirement -- modelling must not be
        # buried behind a click -- is now checked on the workspace tab.
        check("council: findings render directly, no inner tab to click through",
              page.locator("text=Council debate").count() > 0
              or page.locator("text=Clinical insights").count() > 0)
        check("council: links across to the modelling results",
              page.get_by_role("link", name="Computational modelling results").count() == 1)

        page.goto(f"{WEB_BASE}/workspace?tab=modelling&run=916eb3489e10",
                  wait_until="networkidle", timeout=30000)
        check("modelling: results table visible without clicking anything",
              page.locator("text=Sensitivity").count() > 0)

        # --- Number formatting: en-US grouping, not locale-leaked lakh grouping ---
        page.goto(f"{WEB_BASE}/workspace?tab=council&run=916eb3489e10",
                  wait_until="networkidle", timeout=30000)
        body = page.inner_text("body")
        check("council: no lakh-style number grouping (e.g. '11,89,94,772')", "11,89,94,772" not in body)

        check("no page errors across knowledge-graph/council", len(errors) == 0, "; ".join(errors))

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
