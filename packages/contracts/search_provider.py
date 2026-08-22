"""
SearchProvider port (Clinova Phase 3, Epic 3.3, Story 3.3.1): the
provider abstraction 04-ai-research-architecture.md §1 calls for search,
extracted behind the existing `(results, succeeded)` shape
pipeline/academic_search.py's `_search_semantic_scholar_with_status()`/
`_search_arxiv_with_status()` already return (Epic 3.4's Gap Challenger
introduced that shape specifically because Search Coverage Score needs
"did the provider respond" as a signal distinct from "how many results
came back") -- reused here rather than inventing a second convention.

Same AD-2 justification as packages/contracts/llm_provider.py: this port
is introduced now, not deferred, because two real, independently-tuned
provider implementations already exist with real usage history (Semantic
Scholar and arXiv, both live in pipeline/academic_search.py and
pipeline/gap_challenger.py) -- a second implementation's worth of real
usage patterns, not a speculative one-implementation abstraction.

pipeline/academic_search.py's module-level functions and
pipeline/gap_challenger.py's direct calls to them are UNCHANGED by this
port -- exactly like llm_provider.py's introduction left azure_client.py
untouched. This file adds a new, independently-defined shape describing
existing behavior; nothing about runtime behavior changes for any
existing caller (proven by the full test suite passing unmodified).
"""
from typing import Protocol, runtime_checkable


@runtime_checkable
class SearchProvider(Protocol):
    """Structural interface -- any object exposing `search()` with this
    call shape satisfies SearchProvider without inheriting from it.
    Returns (results, succeeded): `succeeded=False` means the request
    itself failed (network error, non-2xx, timeout); `succeeded=True`
    with an empty `results` list means the request genuinely found
    nothing -- the same distinction Search Coverage Score's formula
    (04-ai-research-architecture.md §5.2) needs, and the reason this
    shape was chosen over the older bare-list convention still used by
    validate_gaps()'s original (unmodified) call path."""

    def search(self, query: str, limit: int = 5) -> tuple[list[dict], bool]:
        ...
