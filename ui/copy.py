"""Wording rules applied when something is drawn (UI-05). Pure functions, no Streamlit.

Stored data keeps its original text: a saved run's trace rows carry emoji statuses and stage names with long dashes, and old runs
must keep opening exactly as they were saved. Only what is drawn on screen is cleaned here.
"""
from __future__ import annotations

import re

# Colour pictographs. Text-style marks that carry meaning stay (check, cross, star, arrows, middle dot, en dash).
_PICTOGRAPH = re.compile("[\U0001F000-\U0001FAFF☀-⛿✀-➿⬀-⯿⌀-⏿ℹ️‍]")
KEEP = frozenset("✓✗★☆→←↔·–")        # check, cross, stars, arrows, dot, en dash

# The statuses a pipeline trace stores, as the plain marks the screens draw (an emoji renders in colour and in a different
# size on every platform; a text mark follows the surrounding font and colour).
STATUS_MARKS = {"✅": "✓", "⚠️": "!", "⚠": "!", "❌": "✗", "\U0001F6D1": "✗",
                "⛔": "✗", "ℹ️": "i"}
STATUS_WORDS = {"✓": "OK", "!": "Warning", "✗": "Failed", "i": "Note"}


def strip_emoji(text) -> str:
    """The text without colour pictographs (and the joiners that build them), spaces tidied."""
    kept = "".join(ch for ch in str(text or "") if ch in KEEP or not _PICTOGRAPH.match(ch))
    return " ".join(kept.split())


def status_mark(raw) -> str:
    """'✓', '!' or '✗' for a stored status (an emoji, or nothing, which means it went fine)."""
    s = str(raw or "").strip()
    if not s:
        return "✓"
    return STATUS_MARKS.get(s) or STATUS_MARKS.get(s.replace("️", "")) or (strip_emoji(s) or "✓")


def status_word(mark: str) -> str:
    return STATUS_WORDS.get(mark, "")


def plain_stage(name) -> str:
    """A pipeline stage name for display: no emoji, and a hyphen where the pipeline wrote a long dash."""
    return strip_emoji(name).replace(" — ", " - ").replace("—", "-")
