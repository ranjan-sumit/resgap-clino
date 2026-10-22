"""Accessibility scanning with axe-core in a real browser."""
from __future__ import annotations

from pathlib import Path

AXE_URL ="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"

# Findings in markup the framework itself writes (Streamlit's sidebar carries aria-expanded on a <section>, and
# the page has no landmark regions). They are not ours to fix; everything else must be clean.
FRAMEWORK_RULES = {"aria-allowed-attr", "region"}
WIDTHS = {"desktop": (1440, 900), "tablet": (768, 1024), "phone": (390, 844)}

_AXE_JS = """async () => {
  const r = await axe.run(document, {resultTypes: ['violations']});
  return r.violations.map(v => ({id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length,
                                 sample: v.nodes[0].html.slice(0, 160)}));
}"""


VENDORED_AXE = Path(__file__).parent / "vendor" / "axe.min.js"


def inject_axe(page) -> None:
    """axe-core from the vendored copy (no network needed); the CDN is only a fallback."""
    if VENDORED_AXE.is_file():
        page.add_script_tag(path=str(VENDORED_AXE))
    else:
        page.add_script_tag(url=AXE_URL)


def scan(page) -> list[dict]:
    return page.evaluate(_AXE_JS)


def ours(violations: list[dict]) -> list[dict]:
    """Serious or critical findings that are not the framework's."""
    return [v for v in violations if v["impact"] in ("serious", "critical") and v["id"] not in FRAMEWORK_RULES]


def horizontal_overflow(page) -> int:
    return page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")


def close_sidebar(page) -> None:
    """On a narrow screen an open sidebar covers the page; close it before clicking in the main area."""
    if page.viewport_size["width"] > 768:
        return
    expanded = page.evaluate(
        "() => { const s = document.querySelector('[data-testid=stSidebar]'); return s ? s.getAttribute('aria-expanded') : 'false'; }")
    if expanded == "true":
        page.locator("[data-testid=stSidebarCollapseButton] button").first.click()
        page.wait_for_timeout(500)


def open_sidebar(page) -> None:
    if page.viewport_size["width"] > 768:
        return
    expanded = page.evaluate(
        "() => { const s = document.querySelector('[data-testid=stSidebar]'); return s ? s.getAttribute('aria-expanded') : 'false'; }")
    if expanded != "true":
        page.locator("[data-testid=stExpandSidebarButton]").first.click()
        page.wait_for_timeout(500)
