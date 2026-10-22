"""One way to tell the user something went wrong, needs attention, or is worth knowing.

Every message goes through here so the wording rules hold everywhere: no leading emoji doubling, a plain
next step when the cause is recognisable, and the technical text kept behind "Technical details" rather
than in the sentence. The elements are Streamlit's native alerts, which carry role="alert" for screen readers.
"""
from __future__ import annotations

import re

import streamlit as st

# (pattern on the lower-cased text) -> plain-language cause and next step. First match wins.
_HINTS = [
    (r"timed? ?out|timeout|deadline", "The model took too long to answer. Try again; if it keeps happening, choose a "
                                      "faster model in Settings → Models."),
    (r"\b429\b|rate.?limit|quota|resource_exhausted|too many requests",
     "The provider's rate limit or quota was reached. Wait a minute and try again, or pick another model in "
     "Settings → Models."),
    (r"\b401\b|\b403\b|api key|unauthori[sz]ed|permission denied|invalid.*key|authentication",
     "The provider did not accept the API key. Check it in Settings → API keys."),
    (r"model.*not found|\b404\b.*model|unknown model|does not exist",
     "That model is not available for your key. Choose another in Settings → Models."),
    (r"connection|connect timeout|name or service|dns|network|unreachable",
     "The provider could not be reached. Check your internet connection and try again."),
    (r"jsondecode|json|could not be read|unparseable|malformed",
     "The model's answer could not be read. Running it again usually fixes this."),
    (r"database is locked|locked", "The database was busy. Try again in a moment."),
    (r"no such file|filenotfound|permission|read-only|disk",
     "A file could not be accessed on disk. Check that the data folder exists and is writable."),
]


def hint_for(text: str) -> str:
    low = (text or "").lower()
    for pattern, hint in _HINTS:
        if re.search(pattern, low):
            return hint
    return ""


def clean(message: str) -> str:
    """The message without a leading warning sign (the alert already has its own icon)."""
    return re.sub(r"^\s*(?:⚠️|⚠|❌|ℹ️)\s*", "", str(message or "")).strip()


def show_error(message: str, *, exc: BaseException | None = None, hint: str | None = None,
               details: str | None = None) -> None:
    """An error in a sentence, the likely fix when we recognise the cause, and the raw text on request."""
    text = clean(message)
    tech = details or (f"{type(exc).__name__}: {exc}" if exc is not None else "")
    fix = hint if hint is not None else hint_for(f"{text} {tech}")
    st.error(f"{text}. {fix}" if fix and not text.endswith((".", "!", "?")) else (f"{text} {fix}" if fix else text))
    if tech:
        with st.expander("Technical details"):
            st.code(tech, language=None)


def show_warning(message: str) -> None:
    st.warning(clean(message))


def show_info(message: str) -> None:
    st.info(clean(message))
