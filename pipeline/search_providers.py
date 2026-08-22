"""
SearchProvider adapters (Clinova Phase 3, Epic 3.3, Story 3.3.1) --
class-based wrappers around pipeline/academic_search.py's existing,
already-tested `_search_semantic_scholar_with_status()`/
`_search_arxiv_with_status()` functions, satisfying
packages/contracts/search_provider.py's SearchProvider port structurally.

Deliberately thin: no new search logic, no changed behavior. This exists
so a future caller (e.g. a formalized query-family/rerank pipeline, Epic
3.3's remaining scope beyond what Epic 3.4 already needed, or Epic 3.5's
embedding-backed provider once Qdrant is available) can depend on
`SearchProvider` and swap providers without knowing which academic API is
underneath -- pipeline/gap_challenger.py's existing direct calls to the
underlying functions are UNCHANGED by this file, exactly like
llm_provider.py's introduction left azure_client.py untouched.
"""
from pipeline.academic_search import (
    _search_semantic_scholar_with_status, _search_arxiv_with_status,
)


class SemanticScholarProvider:
    """Adapter for pipeline/academic_search.py's Semantic Scholar search.
    `api_key` is bound at construction (optional -- the API works
    unauthenticated at a lower rate limit), matching AzureOpenAIClient's
    own pattern of binding credentials at __init__ rather than per-call."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def search(self, query: str, limit: int = 5) -> tuple[list, bool]:
        return _search_semantic_scholar_with_status(query, limit=limit, api_key=self.api_key)


class ArxivProvider:
    """Adapter for pipeline/academic_search.py's arXiv search. No API key
    needed -- arXiv's API is fully unauthenticated."""

    def search(self, query: str, limit: int = 5) -> tuple[list, bool]:
        return _search_arxiv_with_status(query, limit=limit)
