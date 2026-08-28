"""One-off Playwright verification script for Phase 5 Slice 5 -- the
"top notch" polish pass: per-page browser tab titles, a branded generated
favicon, a real working Cmd+K command palette (replacing a permanently
disabled search icon with stale copy), and a branded 404 page. Requires
the same services as the other playwright_phase5_slice*.py scripts already
running (FastAPI :8000, Next.js :3000, Postgres). Prints PASS/FAIL per
check and exits 1 on any failure. Screenshots saved to ./screenshots.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)
WEB_BASE = "http://localhost:3000"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" -- {detail}" if detail and not ok else ""))


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1680, "height": 1200})

        # --- Per-page tab titles: each real screen sets its own title
        # (previously every single page showed the same generic app name).
        for path, expected in [
            ("/dashboard", "Dashboard"), ("/corpus", "Corpus"), ("/runs", "Runs"),
            ("/knowledge-graph", "Knowledge Graph"), ("/versions", "Versions"),
        ]:
            page.goto(f"{WEB_BASE}{path}", wait_until="networkidle", timeout=20000)
            title = page.title()
            check(f"title: {path} -> '{expected} · Clinova'", title == f"{expected} · Clinova", f"got {title!r}")

        # A dynamic run-detail title uses the real run name, not a generic
        # "Run" placeholder.
        runs_json = page.evaluate(f"() => fetch('http://localhost:8000/api/runs?limit=1').then(r => r.json())")
        if runs_json["runs"]:
            run = runs_json["runs"][0]
            page.goto(f"{WEB_BASE}/runs/{run['run_id']}", wait_until="networkidle", timeout=20000)
            check(
                "title: run detail uses the real run name, not a generic placeholder",
                run["name"] in page.title(),
                f"got {page.title()!r}, expected to contain {run['name']!r}",
            )

        # --- Favicon: a real generated branded icon, not Next's default.
        icon_resp = page.request.get(f"{WEB_BASE}/icon")
        check(
            "favicon: /icon returns a real generated PNG",
            icon_resp.status == 200 and "image" in (icon_resp.headers.get("content-type") or ""),
            f"status={icon_resp.status}",
        )

        # --- Command palette: Ctrl+K opens it, typing filters results,
        # clicking a result actually navigates (verified with a generous
        # wait -- first-visit dev-mode route compilation is genuinely
        # slower than production, not a bug in the palette itself).
        page.goto(f"{WEB_BASE}/dashboard", wait_until="networkidle", timeout=20000)
        page.keyboard.press("Control+k")
        page.wait_for_timeout(400)
        # Selected by role inside the open dialog rather than by placeholder
        # text: the placeholder is user-facing copy that legitimately changes
        # (it did, when the palette gained real content search), and a test
        # should not fail because a sentence was reworded.
        search_input = page.locator('[role="dialog"] input').first
        check("command palette: opens via Ctrl+K", search_input.is_visible())
        search_input.fill("corpus")
        page.wait_for_timeout(300)
        corpus_result = page.get_by_role("button", name="Corpus", exact=True)
        check("command palette: typing filters to a real matching screen", corpus_result.count() > 0)
        if corpus_result.count() > 0:
            corpus_result.click()
            page.wait_for_timeout(2500)
            check("command palette: clicking a result actually navigates", page.url.endswith("/corpus"), page.url)
        page.screenshot(path=str(SCREENSHOT_DIR / "12_command_palette.png"))

        # --- 404: an unmatched route gets a real branded not-found page,
        # not a raw framework error screen.
        page.goto(f"{WEB_BASE}/this-route-does-not-exist-anywhere", wait_until="networkidle", timeout=20000)
        body = page.inner_text("body")
        check("404: unmatched route shows the branded not-found page", "Page not found" in body)
        check("404: offers a real way back (Dashboard/Runs links)", "Dashboard" in body and "Runs" in body)
        page.screenshot(path=str(SCREENSHOT_DIR / "13_not_found.png"))

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
