"""Rules about what the screens show, checked on the rendered app rather than on source text (UI-14).

Two ideas run through this module:

* A rule is checked on what a person would see: AppTest renders each screen against a seeded synthetic project and
  the helpers read the visible text and the buttons. CSS, scripts and tags are stripped first.
* A rule that today's UI already breaks is a RATCHET: the known violations are written down in
  tests/data/ui_rules_baseline.json, a NEW violation fails, and a violation that has been fixed must be removed from
  the file (the test says which). The later UI PRs shrink the file; nothing may grow it.
"""
from __future__ import annotations

import html
import re

# ── text the user can see ─────────────────────────────────────────────────────────────────────────
_STYLE = re.compile(r"<(style|script)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_HEADING_HTML = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.S | re.I)
_HEADING_MD = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$", re.M)

EM_DASH = "—"
# Pictographs that render as colour emoji. Text-style marks (a check mark, an arrow, a middle dot) are not emoji
# and stay allowed as status marks.
_EMOJI = re.compile("[\U0001F300-\U0001FAFF✅❌❎⚠⭐⬛⬜⏳⌛✨❗❓️]")

LABEL_KINDS = {"title", "header", "subheader", "heading", "label"}      # emoji are only refused where they head something


def plain(markup) -> str:
    """Visible text of a markdown or HTML string."""
    s = _STYLE.sub(" ", str(markup or ""))
    s = _TAG.sub(" ", s)
    return html.unescape(" ".join(s.split()))


def _norm(text: str) -> str:
    return re.sub(r"\d+", "#", " ".join(str(text).split()))[:90]          # digits vary with the data; the wording does not


def collect(at) -> list[tuple[str, str]]:
    """[(kind, text)] for everything visible on an AppTest screen. Data tables are skipped (their cells are paper text)."""
    items: list[tuple[str, str]] = []
    for kind in ("title", "header", "subheader"):
        items += [(kind, plain(e.value)) for e in getattr(at, kind)]
    for e in at.markdown:
        raw = _STYLE.sub(" ", str(e.value or ""))
        items += [("heading", plain(m)) for m in _HEADING_MD.findall(raw) + _HEADING_HTML.findall(raw)]
        items.append(("text", plain(_HEADING_HTML.sub(" ", _HEADING_MD.sub(" ", raw)))))      # the rest, headings not repeated
    for kind in ("caption", "info", "warning", "success", "error"):
        items += [("text", plain(e.value)) for e in getattr(at, kind)]
    for kind in ("button", "expander", "checkbox", "selectbox", "multiselect", "radio", "text_input", "text_area",
                 "number_input", "toggle"):
        items += [("label", str(getattr(e, "label", "") or "")) for e in getattr(at, kind, [])]
    items += [("label", str(t.label)) for t in at.tabs]
    return [(k, t) for k, t in items if t.strip()]


def copy_problems(items, screen: str = "") -> list[str]:
    """Fingerprints of copy that breaks the tone rules: a long dash anywhere, an emoji in a heading or a label."""
    found = []
    for kind, text in items:
        why = []
        if EM_DASH in text:
            why.append("long dash")
        if kind in LABEL_KINDS and _EMOJI.search(text):
            why.append("emoji")
        for w in why:
            found.append(f"{screen} | {kind} | {w} | {_norm(text)}")
    return sorted(set(found))


# ── buttons ───────────────────────────────────────────────────────────────────────────────────────
def primary_buttons(at) -> list[str]:
    """Labels of the solid (primary) buttons in the main area, not the sidebar. A screen is about one action.
    A form's own submit button is not counted: it sits inside a closed feedback popover or expander and is the one
    action of that form."""
    return [b.label for b in at.main.button
            if getattr(b.proto, "type", "") == "primary" and not getattr(b.proto, "form_id", "")]
