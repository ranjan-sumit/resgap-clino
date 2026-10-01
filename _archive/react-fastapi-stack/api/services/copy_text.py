"""
Reader-facing copy for API responses, sourced from packages/branding/copy.json
(Clinova Phase 5, Epic 5.7) -- the same file apps/web/lib/copy.ts reads, so a
sentence that reaches the user through an API `empty_reason` and the same
sentence rendered by a React empty state cannot say different things.

Why this exists: centralizing the web app's copy in Slice 12 caught that the
"runs only ever come from the Streamlit workspace" empty state had become
false the moment the web app grew its own New Run screen. That fix only
covered apps/web. The identical sentence was still hardcoded in SIX api
services (challenger, corpus, council, dashboard, evidence, graph), so the
API kept serving the false claim to every one of those screens -- the
duplication had simply moved one layer down instead of being removed.

tests/test_api_quality.py asserts no module under services/ contains that
sentence, including this one, which is why the paragraph above paraphrases
it rather than quoting it.
"""
import json
from functools import lru_cache

from apps.api import settings


@lru_cache(maxsize=1)
def _copy() -> dict:
    return json.loads((settings.BRANDING_DIR / "copy.json").read_text(encoding="utf-8"))


def common(key: str) -> str:
    """One `common.*` string from copy.json.

    Raises KeyError on an unknown key rather than returning "" -- a silently
    blank empty_reason would be a bare value with no basis, which is exactly
    what NFR-8 forbids, and it would look like a rendering bug rather than a
    missing string.
    """
    section = _copy().get("common") or {}
    if key not in section:
        raise KeyError(f"copy.json has no common.{key} (packages/branding/copy.json)")
    return section[key]


def no_runs_in_project() -> str:
    """`empty_reason` for any project-scoped screen whose basis run is absent."""
    return common("no_runs_body")
