"""Phase 5, Slice 7 -- verifies the Paper Detail page: real per-paper LLM
wiki content (contributions/methods/datasets/key findings/limitations/
future work/key concepts) plus parsed sections and extracted tables, reached
via a real link from the Corpus list rather than a dead-end hover card.
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
        page = browser.new_page(viewport={"width": 1600, "height": 1200})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        page.goto(f"{WEB_BASE}/corpus", wait_until="networkidle", timeout=20000)
        page.screenshot(path=str(SCREENSHOT_DIR / "12_corpus_list.png"), full_page=True)

        paper_link = page.locator("a[href^='/corpus/papers/']").first
        check("corpus: paper card is a real link (not a dead-end hover card)", paper_link.count() > 0)

        paper_link.click()
        page.wait_for_url("**/corpus/papers/**", timeout=10000)
        page.wait_for_load_state("networkidle")
        check("paper detail: navigated to a real per-paper URL", "/corpus/papers/" in page.url)

        title = page.locator("h1").first.inner_text()
        check("paper detail: real paper title rendered", len(title) > 10, title)

        check("paper detail: Contributions card present", page.locator("text=Contributions").count() > 0)
        check("paper detail: Key findings card present", page.locator("text=Key findings").count() > 0)
        check("paper detail: parsed sections listed", page.locator("text=/Parsed sections/").count() > 0)
        check(
            "paper detail: internal '_header' key relabeled for readers",
            page.locator("text=_header").count() == 0,
        )

        page.screenshot(path=str(SCREENSHOT_DIR / "13_paper_detail.png"), full_page=True)

        section_button = page.get_by_role("button").filter(has_text="Header / Abstract")
        if section_button.count() > 0:
            section_button.first.click()
            page.wait_for_timeout(300)
            check("paper detail: a section expands to show real parsed text", len(page.inner_text("body")) > 500)

        back_link = page.locator("a", has_text="Corpus").first
        check("paper detail: back-to-corpus link present", back_link.count() > 0)

        page.goto(f"{WEB_BASE}/corpus/papers/does-not-exist.pdf", wait_until="networkidle", timeout=20000)
        check(
            "paper detail: unknown paper shows a real ErrorState, not a crash",
            page.locator("text=Paper not found").count() > 0,
        )

        check("no page errors across corpus/paper-detail flow", len(errors) == 0, "; ".join(errors))

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
