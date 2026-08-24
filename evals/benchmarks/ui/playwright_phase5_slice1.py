"""One-off Playwright verification script for Phase 5 Slice 1 (App Shell +
Landing + Dashboard + Runs + Compare + Lineage) against the real Next.js dev
server + FastAPI backend + Postgres registry -- not part of the pytest
suite. Requires all three already running:

    T1  python -m uvicorn apps.api.main:app --reload --port 8000
    T2  npm run dev --prefix apps/web
    T3  streamlit run app.py   (not exercised by this script, but the API
                                 reads the same Postgres registry it writes)

Prints a PASS/FAIL line per check and exits 1 if any check failed, matching
evals/benchmarks/baseline/playwright_smoke_test.py's convention. Screenshots
saved to ./screenshots next to this script for the visual-review pass.
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[3]
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)
WEB_BASE = "http://localhost:3000"
API_BASE = "http://localhost:8000"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" -- {detail}" if detail and not ok else ""))


def main() -> int:
    branding = json.loads((REPO_ROOT / "packages" / "branding" / "theme.json").read_text(encoding="utf-8"))
    copy = json.loads((REPO_ROOT / "packages" / "branding" / "copy.json").read_text(encoding="utf-8"))
    landing_copy = copy["landing"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1200})

        # --- Landing: every string read from copy.json/theme.json at test
        # time, not hardcoded -- proves single-sourcing, not just matching
        # coincidentally-identical hardcoded copies.
        page.goto(WEB_BASE, wait_until="networkidle", timeout=20000)
        body = page.inner_text("body")
        body_lower = body.lower()
        # product_name and the trust strip are deliberately rendered
        # uppercase via CSS text-transform -- innerText reflects the
        # rendered (uppercased) text, so these two compare case-insensitively;
        # everything else on the page keeps its natural case.
        check("landing: product_name from theme.json", branding["product_name"].lower() in body_lower)
        check("landing: tagline from theme.json", branding["tagline"] in body)
        check("landing: hero_headline from copy.json", landing_copy["hero_headline"] in body)
        check("landing: hero_supporting from copy.json", landing_copy["hero_supporting"] in body)
        check("landing: primary_cta from copy.json", landing_copy["primary_cta"] in body)
        check("landing: secondary_cta from copy.json", landing_copy["secondary_cta"] in body)
        check(
            "landing: trust strip items from copy.json",
            all(item.lower() in body_lower for item in landing_copy["footer_trust_strip"]),
        )
        page.screenshot(path=str(SCREENSHOT_DIR / "01_landing.png"), full_page=True)

        # --- Hero canvas actually animates (two frames differ), not a
        # static image or a Math.random() unseeded scatter.
        canvas = page.locator("canvas").first
        if canvas.count() > 0:
            frame1 = page.evaluate(
                "(el) => el.toDataURL()", canvas.element_handle()
            )
            page.wait_for_timeout(700)
            frame2 = page.evaluate(
                "(el) => el.toDataURL()", canvas.element_handle()
            )
            check("landing: hero canvas animates between frames", frame1 != frame2)
        else:
            check("landing: hero canvas animates between frames", False, "no <canvas> found")

        # --- App shell: exact nav groups present, Governance absent
        # (Phase 6-gated, never shown even muted).
        page.goto(f"{WEB_BASE}/dashboard", wait_until="networkidle", timeout=20000)
        body = page.inner_text("body")
        body_lower = body.lower()
        # Group headers are rendered uppercase via CSS text-transform.
        for group in ["Workspace", "Research", "Intelligence", "Engineering", "Settings"]:
            check(f"shell: nav group '{group}' present", group.lower() in body_lower)
        check("shell: 'Governance' nav group absent", "governance" not in body_lower)
        page.screenshot(path=str(SCREENSHOT_DIR / "02_dashboard.png"), full_page=True)

        # --- Dashboard: the unmeasured confidence tile renders "Not
        # recorded" with its basis visible as body text, not a bare blank.
        check(
            "dashboard: unmeasured tile shows 'Not recorded' + basis",
            "Not recorded" in body and "composite research" in body.lower(),
        )

        # --- Runs: zero raw emoji reach the DOM (status always goes
        # through a StatusChip -> lucide icon, never the pipeline_trace's
        # raw ✅/⚠️/❌).
        page.goto(f"{WEB_BASE}/runs", wait_until="networkidle", timeout=20000)
        runs_body = page.inner_text("body")
        raw_emoji = [e for e in ("✅", "⚠️", "❌") if e in runs_body]
        check("runs: zero raw emoji in DOM", len(raw_emoji) == 0, f"found {raw_emoji}")
        page.screenshot(path=str(SCREENSHOT_DIR / "03_runs.png"), full_page=True)

        # --- Compare: Promote button disabled with its reason visible as
        # real text on the page (not hover-only).
        runs_json = page.evaluate(f"() => fetch('{API_BASE}/api/runs?limit=2').then(r => r.json())")
        run_ids = [r["run_id"] for r in runs_json["runs"]]
        if len(run_ids) >= 2:
            page.goto(
                f"{WEB_BASE}/runs/compare?baseline={run_ids[1]}&candidate={run_ids[0]}",
                wait_until="networkidle", timeout=20000,
            )
            compare_body = page.inner_text("body")
            promote_btn = page.get_by_role("button", name="Promote candidate")
            is_disabled = promote_btn.is_disabled() if promote_btn.count() > 0 else False
            check("compare: Promote button is disabled", is_disabled)
            check(
                "compare: disabled reason visible as body text",
                "read-only" in compare_body.lower() or "cannot evaluate" in compare_body.lower(),
            )
            page.screenshot(path=str(SCREENSHOT_DIR / "04_compare.png"), full_page=True)

            # --- Lineage: technical diagram renders. Uses the one real run
            # known to have a backfilled 'pipeline' artifact (none of the
            # 5 real runs predate manifest capture with a full spine) --
            # not run_ids[0], which has zero recorded artifacts.
            lineage_run_id = "b18ae1c95838"
            page.goto(f"{WEB_BASE}/runs/{lineage_run_id}/lineage", wait_until="networkidle", timeout=20000)
            node_count = page.locator("div[style*='200px']").count()
            edge_count = page.locator("svg line").count()
            check(
                "lineage: technical diagram renders at least one artifact node",
                node_count > 0,
                f"{node_count} nodes, {edge_count} edges",
            )
            page.screenshot(path=str(SCREENSHOT_DIR / "05_lineage.png"), full_page=True)
        else:
            check("compare/lineage: at least 2 real runs available", False, f"found {len(run_ids)}")

        # --- Keyboard navigation: Tab reaches real interactive nav links
        # with a visible focus ring, not an invisible/removed outline.
        page.goto(f"{WEB_BASE}/runs", wait_until="networkidle", timeout=20000)
        page.keyboard.press("Tab")
        focus_tags = []
        reached_nav_link = False
        has_visible_focus_ring = False
        for _ in range(15):
            info = page.evaluate("""() => {
                const el = document.activeElement;
                if (!el) return null;
                const style = getComputedStyle(el);
                return {
                    tag: el.tagName,
                    href: el.getAttribute('href'),
                    outline: style.outlineStyle,
                    boxShadow: style.boxShadow,
                    ring: style.getPropertyValue('--tw-ring-color'),
                };
            }""")
            if info is None:
                break
            focus_tags.append(info["tag"])
            if info["href"] and "/runs" in (info["href"] or ""):
                reached_nav_link = True
            if info["outline"] != "none" or (info["boxShadow"] and info["boxShadow"] != "none"):
                has_visible_focus_ring = True
            page.keyboard.press("Tab")
        check("keyboard: Tab reaches a real nav link", reached_nav_link, f"tags seen: {focus_tags}")
        check("keyboard: focused elements show a visible focus ring", has_visible_focus_ring)

        # --- Contrast: #0093D0 (clinova_blue) is ~3.1:1 on white, below
        # WCAG AA for body text -- mechanically confirm it is never used
        # as a text color anywhere rendered, only clinova_deep_blue is.
        page.goto(f"{WEB_BASE}/dashboard", wait_until="networkidle", timeout=20000)
        offending = page.evaluate("""() => {
            const target = 'rgb(0, 147, 208)'; // clinova_blue
            const bad = [];
            for (const el of document.querySelectorAll('body *')) {
                if (el.children.length > 0) continue;
                if (!el.textContent || !el.textContent.trim()) continue;
                const color = getComputedStyle(el).color;
                if (color === target) bad.push(el.textContent.trim().slice(0, 40));
            }
            return bad;
        }""")
        check(
            "contrast: clinova_blue (#0093D0, ~3.1:1) never used as text color",
            len(offending) == 0,
            f"found on: {offending}",
        )

        # --- DM Serif Display actually loaded and applied to the page
        # title, not a silent fallback to the generic serif stack.
        h1_font = page.evaluate("""() => {
            const h1 = document.querySelector('h1');
            return h1 ? getComputedStyle(h1).fontFamily : null;
        }""")
        font_loaded = page.evaluate("() => document.fonts.check('16px \\'DM Serif Display\\'')")
        check(
            "typography: DM Serif Display loaded and applied to h1",
            font_loaded and h1_font is not None and "DM Serif Display" in h1_font,
            f"loaded={font_loaded}, h1 font-family={h1_font}",
        )

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
