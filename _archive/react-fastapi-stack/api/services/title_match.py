"""
Shared title normalisation for cross-screen linking (Clinova Phase 5, Epic 5.7).

Titles are the only join key the pipeline records between gaps, proposals and
papers -- there are no ids on any of them -- so every cross-link resolves by
comparing normalised titles.

This lived as two identical private copies (runs_service._normalise_title and
dashboard_service._normalise). Two copies of a matching rule is exactly how
cross-links silently stop matching later: one gets a fix, the other doesn't,
and the failure mode is an empty list rather than an error. One definition,
one test.
"""

# Real characters observed in this pipeline's own LLM-generated titles:
# U+2011 NON-BREAKING HYPHEN and U+2010 HYPHEN both render like an ASCII "-"
# but compare unequal to it, which produced zero cross-links under a naive
# equality check even though the titles looked identical on screen.
_DASHES = {
    "‑": "-",  # non-breaking hyphen
    "‐": "-",  # hyphen
    "‒": "-",  # figure dash
    "–": "-",  # en dash
    "—": "-",  # em dash
}


def normalise_title(title: str) -> str:
    """Lowercase, collapse whitespace, and fold typographic dashes to ASCII."""
    text = (title or "").lower()
    for source, replacement in _DASHES.items():
        text = text.replace(source, replacement)
    return " ".join(text.split())
