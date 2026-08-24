"""One-off Playwright verification script for Phase 5 Slice 2 -- the visual
redesign (dark app shell, elevation/gradient system) plus the 9 new screens
(Corpus, Evidence, Knowledge Graph, Research Gaps, Gap Challenger, Research
Council, Proposals, Versions) and the POST /runs/{id}/promote write path.
Requires the same three services as playwright_phase5_slice1.py already
running (FastAPI :8000, Next.js :3000, Postgres). Prints PASS/FAIL per check
and exits 1 on any failure. Screenshots saved to ./screenshots.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from playwright.sync_api import sync_playwright

from utils.database import _get_conn, init_db

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)
WEB_BASE = "http://localhost:3000"
API_BASE = "http://localhost:8000"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" -- {detail}" if detail and not ok else ""))


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1680, "height": 1200})

        # --- Redesign: the sidebar is genuinely dark (not the flat white
        # panel the original complaint was about), and real elevation
        # (a soft, layered box-shadow) is used on cards, not a 1px ring.
        page.goto(f"{WEB_BASE}/dashboard", wait_until="networkidle", timeout=20000)
        sidebar_bg = page.evaluate("""() => {
            const nav = document.querySelector('nav[aria-label="Primary"]');
            return nav ? getComputedStyle(nav).backgroundImage : '';
        }""")
        check("redesign: sidebar uses a dark gradient background", "gradient" in sidebar_bg, sidebar_bg[:80])
        card_shadow = page.evaluate("""() => {
            const card = document.querySelector('.shadow-card');
            return card ? getComputedStyle(card).boxShadow : '';
        }""")
        check(
            "redesign: cards use a layered shadow (not a flat 1px ring)",
            card_shadow.count(",") >= 1,
            card_shadow[:120],
        )
        page.screenshot(path=str(SCREENSHOT_DIR / "10_dashboard_redesign.png"), full_page=True)

        # --- New screens: each loads real content, not an error/empty shell.
        # Section labels (ConfidenceStat, CountStatView, h2 headers) are
        # deliberately rendered uppercase via CSS text-transform -- compare
        # case-insensitively, same lesson learned in slice1's script.
        checks_per_page = {
            "corpus": ["Corpus Confidence", "AuDHD"],
            "evidence": ["Evidence Confidence"],
            "knowledge-graph": ["Entities", "Relationships"],
            "gaps": ["Research Gaps"],
            "gap-challenger": ["Gap Challenger"],
            "council": ["Research Council"],
            "proposals": ["Proposals"],
            "versions": ["Versions", "pipeline:"],
            "settings": ["System status", "Branding"],
        }
        for path, expected_strings in checks_per_page.items():
            page.goto(f"{WEB_BASE}/{path}", wait_until="networkidle", timeout=20000)
            body_lower = page.inner_text("body").lower()
            for s in expected_strings:
                check(f"{path}: shows '{s}'", s.lower() in body_lower)
            page.screenshot(path=str(SCREENSHOT_DIR / f"11_{path.replace('-', '_')}.png"), full_page=True)

        # --- Corpus: reference funnel stages render in the fixed, correct
        # order (not Postgres JSONB's arbitrary round-trip order).
        page.goto(f"{WEB_BASE}/corpus", wait_until="networkidle", timeout=20000)
        # textContent (unlike innerText) does NOT reflect the CSS
        # uppercase transform, so this compares against the real,
        # un-transformed Title Case label text.
        stage_order = page.evaluate("""() => {
            const known = ['Detected','Parsed','Resolved','Unresolved','Quarantined',
                           'Duplicates Merged','Fallback Parsed'];
            return [...document.querySelectorAll('p')]
                .map(el => el.textContent.trim())
                .filter(t => known.includes(t));
        }""")
        check(
            "corpus: reference funnel stages in fixed pipeline order",
            stage_order[:2] == ["Detected", "Parsed"] if len(stage_order) >= 2 else False,
            f"got {stage_order}",
        )

        # --- Knowledge Graph: relationship rows are compact (not a
        # multi-line wrap caused by a right-floated long paper name).
        page.goto(f"{WEB_BASE}/knowledge-graph", wait_until="networkidle", timeout=20000)
        row_heights = page.evaluate("""() => {
            const rows = [...document.querySelectorAll('li')].filter(
                li => li.querySelector('.rounded-full') && li.className.includes('border')
            );
            return rows.slice(0, 10).map(r => r.getBoundingClientRect().height);
        }""")
        check(
            "knowledge-graph: relationship rows stay compact (<70px)",
            all(h < 70 for h in row_heights) if row_heights else False,
            f"heights sample: {row_heights[:5]}",
        )

        # --- Versions + promote: exercised against a throwaway artifact
        # inserted/cleaned up directly (never the real pipeline champions
        # the rest of this app's screenshots depend on).
        init_db()
        conn = _get_conn()
        cur = conn.cursor()
        test_run_id = "playwright_slice2_promote_test"
        artifact_id = f"pipeline:{test_run_id}"
        cur.execute(
            """INSERT INTO research_artifacts
               (artifact_id, artifact_type, artifact_version, project_id, run_id, content_hash, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (artifact_id) DO UPDATE SET status = EXCLUDED.status""",
            (artifact_id, "pipeline", "1", "Healthcare AI", test_run_id, "deadbeef", "EXPERIMENTAL"),
        )
        conn.commit()
        try:
            page.goto(f"{WEB_BASE}/versions", wait_until="networkidle", timeout=20000)
            row = page.locator(f"text={artifact_id}").locator("xpath=ancestor::tr")
            check("versions: throwaway test artifact row renders", row.count() > 0)
            if row.count() > 0:
                select_trigger = row.locator("button").first
                select_trigger.click()
                page.get_by_role("option", name="CANDIDATE").click()
                promote_btn = row.get_by_role("button", name="Promote")
                promote_btn.click()
                page.wait_for_timeout(1500)
                # StatusBadge renders the chip label Title Case ("Candidate"),
                # not the raw uppercase status code.
                body_after = page.inner_text("body")
                check("versions: promote button drives a real state change", "Candidate" in body_after)
        finally:
            cur.execute("DELETE FROM research_artifacts WHERE artifact_id = %s", (artifact_id,))
            conn.commit()
            conn.close()

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
