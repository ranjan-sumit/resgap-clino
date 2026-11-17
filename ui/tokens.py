"""The app's colour tokens and a contrast checker.

Every colour used for TEXT must reach a 4.5:1 contrast ratio against the surface it sits on (WCAG AA).
`REQUIRED_PAIRS` lists the text/background combinations the app really uses, and tests/test_design_system.py
fails if any of them drops below the line.
"""
from __future__ import annotations

TEXT = "#0b1f3a"
MUTED = "#4a6580"            # captions and secondary text (was #697689 / #55708f: below 4.5:1 on the page background)
ACCENT = "#0066cc"
ACCENT_STRONG = "#004b93"    # text on tinted accent backgrounds (selected tab)
GOOD = "#087f5b"
WARN = "#8a5a00"             # amber text (was #b7791f: 3.2:1)
BAD = "#c81e1e"

SURFACE = "#ffffff"
PAGE = "#f5f9ff"
SOFT = "#edf6ff"
ACCENT_TINT = "#c4dcf5"      # the selected segment of the section selector
WARN_TINT = "#fff7e6"
GOOD_TINT = "#e7f8f1"
BAD_TINT = "#fff1f1"

AA_TEXT = 4.5

REQUIRED_PAIRS = [
    ("body text", TEXT, SURFACE), ("body text on page", TEXT, PAGE),
    ("captions", MUTED, SURFACE), ("captions on page", MUTED, PAGE), ("captions on soft", MUTED, SOFT),
    ("links and accents", ACCENT, SURFACE), ("accent on page", ACCENT, PAGE),
    ("selected section", ACCENT_STRONG, ACCENT_TINT), ("accent strong on soft", ACCENT_STRONG, SOFT),
    ("good", GOOD, SURFACE), ("good badge", GOOD, GOOD_TINT),
    ("warning", WARN, SURFACE), ("warning badge", WARN, WARN_TINT), ("warning on page", WARN, PAGE),
    ("bad", BAD, SURFACE), ("bad badge", BAD, BAD_TINT),
    ("planner: a check that is switched off", "#5f7389", SURFACE),     # was #9aa5b1 (2.5:1); axe flagged it on Settings > Models
]


def _channel(c: int) -> float:
    v = c / 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return round((hi + 0.05) / (lo + 0.05), 2)
