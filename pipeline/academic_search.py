"""
Stage 6: Academic Search Validator
Validates each identified gap against Semantic Scholar and arXiv APIs.
Determines if the gap is: Open / Partially Addressed / Already Solved.
"""
import requests
import time
import re
import json   # B3 fix — moved from inside _assess_coverage to module level
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception
from utils.azure_client import unwrap
from utils.database import compute_cache_key, get_cached_gap_validation, save_cached_gap_validation

# Bumped whenever the assessment prompt or search-query-construction logic
# changes, so old cached entries don't silently keep serving stale-logic
# results (AD-3).
GAP_VALIDATION_STAGE_VERSION = 3

SEMANTIC_SCHOLAR_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
ARXIV_BASE = "http://export.arxiv.org/api/query"

FIELDS = "title,year,abstract,citationCount,authors"


def _is_retryable_search_error(exc: BaseException) -> bool:
    """Only retry genuinely transient conditions -- a network blip or a
    429/5xx -- not a permanent 4xx client error that retrying can't fix
    (matches AD-5's "a transient rate-limit or network blip", not "any
    failure whatsoever"). Story 2.5."""
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status == 429 or (status is not None and status >= 500)
    return False


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=10),
    retry=retry_if_exception(_is_retryable_search_error),
    reraise=True,
)
def _fetch_semantic_scholar(query: str, limit: int, headers: dict) -> dict:
    resp = requests.get(
        SEMANTIC_SCHOLAR_BASE,
        params={"query": query, "limit": limit, "fields": FIELDS},
        headers=headers, timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _search_semantic_scholar(query: str, limit: int = 5, api_key: str = "") -> list:
    """Search Semantic Scholar for papers related to a gap. `api_key` is
    optional -- the API works unauthenticated at a lower rate limit."""
    headers = {"x-api-key": api_key} if api_key else {}
    try:
        data = _fetch_semantic_scholar(query, limit, headers)
    except Exception:
        return []
    papers = data.get("data", [])
    results = []
    for p in papers:
        results.append({
            "title": p.get("title", ""),
            "year": p.get("year"),
            "abstract": (p.get("abstract") or "")[:300],
            "citations": p.get("citationCount", 0),
            "authors": [a.get("name", "") for a in (p.get("authors") or [])[:3]],
            "source": "Semantic Scholar",
        })
    return results


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=10),
    retry=retry_if_exception(_is_retryable_search_error),
    reraise=True,
)
def _fetch_arxiv(params: dict) -> str:
    resp = requests.get(ARXIV_BASE, params=params, timeout=10)
    resp.raise_for_status()
    return resp.text


_ARXIV_RESERVED_CHARS = re.compile(r'[():"]')
_ARXIV_BOOLEAN_WORDS = {"AND", "OR", "NOT"}


def _build_arxiv_query(query: str) -> str:
    """Group search terms so arXiv matches papers about the combined
    concept, not any paper containing any single word (AD-7). AND-joins
    each whitespace-split term under its own all: field prefix -- NOT a
    single quoted phrase; a realistic multi-concept gap query would almost
    never appear as an exact contiguous phrase in a real paper, which
    would likely make the search return zero results in practice (Story
    2.6). Review fix: strips Lucene-reserved characters (: ( ) ") from
    each term and drops any term that is itself a literal boolean operator
    word -- both would otherwise corrupt the query structure (e.g. a
    gap title containing "Gap: (LLMs) reasoning" or the literal word
    "AND")."""
    terms = []
    for t in query.split():
        t = _ARXIV_RESERVED_CHARS.sub("", t)
        if t and t.upper() not in _ARXIV_BOOLEAN_WORDS:
            terms.append(t)
    if not terms:
        return "all:"
    return " AND ".join(f"all:{t}" for t in terms)


def _search_arxiv(query: str, limit: int = 3) -> list:
    """Search arXiv as a backup academic source."""
    try:
        # Review fix: build `params` inside the try block -- a non-string
        # `query` (or any other unexpected failure building the request)
        # must degrade to [] like every other path here, not raise uncaught.
        params = {
            "search_query": _build_arxiv_query(query),
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        content = _fetch_arxiv(params)
    except Exception:
        return []
    entries = re.findall(r'<entry>(.*?)</entry>', content, re.DOTALL)
    results = []
    for entry in entries:
        title_match = re.search(r'<title>(.*?)</title>', entry, re.DOTALL)
        year_match = re.search(r'<published>(\d{4})', entry)
        summary_match = re.search(r'<summary>(.*?)</summary>', entry, re.DOTALL)
        if title_match:
            results.append({
                "title": title_match.group(1).strip().replace("\n", " "),
                "year": int(year_match.group(1)) if year_match else None,
                "abstract": (summary_match.group(1).strip()[:300] if summary_match else ""),
                "citations": None,
                "source": "arXiv",
            })
    return results


def _truncate_at_word_boundary(text: str, max_len: int) -> str:
    """Truncate to at most max_len chars without cutting a trailing word in
    half. A raw character slice can leave a mangled fragment that, under
    _build_arxiv_query's strict AND-join, becomes a mandatory search term
    and can single-handedly zero out arXiv results -- harmless noise under
    the old OR-style query, but not anymore (Story 2.6 review fix)."""
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    last_space = truncated.rfind(" ")
    return truncated[:last_space] if last_space > 0 else truncated


def _build_search_query(gap: dict) -> str:
    """Build a focused academic search query from a gap description."""
    title = gap.get("title", "")
    missing = gap.get("missing_connection", "")
    description = gap.get("description", "")[:150]

    # Use title + missing connection for best query
    if missing:
        return _truncate_at_word_boundary(f"{title} {missing}", 120)
    return _truncate_at_word_boundary(f"{title} {description}", 120)


def _assess_coverage(gap: dict, found_papers: list, client) -> tuple[dict, bool]:
    """
    Use LLM to assess if the found papers actually address the gap.
    Returns (result, cacheable). `cacheable` is True only for a genuine,
    confident result -- no papers found at all, or a cleanly-parsed LLM
    response -- and False for every degraded-heuristic-fallback path (LLM
    call failed, LLM response had no parseable JSON). Per AD-2, a transient
    failure must never be frozen into the cache as if it were a real
    assessment (Story 2.4).
    """
    if not found_papers:
        return {"status": "open", "reasoning": "No relevant papers found in academic search."}, True

    prompt = f"""Gap: {gap.get('title')}
Description: {gap.get('description')}

Papers found in academic search:
{json.dumps([{'title': p['title'], 'year': p['year'], 'abstract': p['abstract']} for p in found_papers[:5]], indent=2)}

Does the gap appear to be:
- "open": Not addressed by any of these papers
- "partial": Partially addressed but significant work remains
- "solved": Already thoroughly addressed

Return ONLY JSON: {{"status": "open|partial|solved", "reasoning": "1 sentence explanation"}}"""

    try:
        # B3 fix: client is passed in — use it directly, no re-import needed
        raw   = unwrap(client.chat_json("You are a research gap validator.", prompt, max_tokens=200))
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
            # Review fix: a syntactically valid but off-schema response
            # (e.g. {"foo": "bar"}) must not be treated as a genuine,
            # cacheable result -- only a recognized status counts.
            if isinstance(result, dict) and result.get("status") in ("open", "partial", "solved"):
                return result, True
    except Exception:
        pass

    # Fallback: if we found recent papers, call it partial. Never cache
    # this -- it's reached by an LLMCallError, a response with no JSON
    # match, AND malformed JSON alike, none of which are a real assessment.
    recent = [p for p in found_papers if p.get("year") and p["year"] >= 2022]
    if len(recent) >= 2:
        return {"status": "partial", "reasoning": "Related recent work found but gap may still exist."}, False
    return {"status": "open", "reasoning": "No directly relevant recent papers found."}, False


def validate_gaps(gaps: list, client, domain_config: dict = None, ss_api_key: str = "") -> list:
    """
    Validate all gaps against academic databases.
    Updates each gap with: validation_status, existing_papers, reasoning.
    """
    boost_terms = []
    if domain_config:
        from domain_config import get_search_boost_terms
        boost_terms = get_search_boost_terms(domain_config)

    validated = []
    for gap in gaps:
        # B18 fix: check the cache before the search calls OR the LLM
        # assessment (Story 2.4 / AD-2 / AD-3). gap_hash is title+description
        # only, per AD-3's literal definition -- see Story 2.4 Dev Notes for
        # the accepted missing_connection limitation this implies.
        # Review fix: `or ''` (not just `.get(key, '')`) so an explicit None
        # value doesn't slip the literal string "None" into the hash and
        # defeat the empty-content guard below.
        gap_content = f"{gap.get('title') or ''}\n{gap.get('description') or ''}"
        cacheable_gap = bool(gap_content.strip())
        if cacheable_gap:
            cache_key, gap_hash, domain_hash = compute_cache_key(
                gap_content, domain_config, ["search_boost_terms"], GAP_VALIDATION_STAGE_VERSION,
            )
            cached = get_cached_gap_validation(cache_key)
            if cached is not None:
                # Review fix: .get() with defaults, not direct indexing --
                # a cached row missing a key must degrade gracefully, not
                # crash the whole validate_gaps run.
                gap["validation_status"] = cached.get("validation_status", "open")
                gap["validation_reasoning"] = cached.get("validation_reasoning", "")
                gap["existing_papers"] = cached.get("existing_papers", [])
                gap["search_query_used"] = cached.get("search_query_used", "")
                validated.append(gap)
                continue

        query = _build_search_query(gap)

        # Boost query with 1-2 domain-specific terms for better precision
        if boost_terms:
            # Pick the most relevant boost term based on gap title
            gap_lower = gap.get("title", "").lower()
            relevant_boosts = [t for t in boost_terms if any(w in gap_lower for w in t.split())]
            boost = relevant_boosts[0] if relevant_boosts else boost_terms[0]
            query = f"{query} {boost}"
            query = _truncate_at_word_boundary(query, 150)  # keep query length reasonable

        # Search both sources
        ss_papers = _search_semantic_scholar(query, limit=5, api_key=ss_api_key)
        time.sleep(0.5)
        arxiv_papers = _search_arxiv(query, limit=3)

        all_papers = ss_papers + arxiv_papers

        assessment, cacheable = _assess_coverage(gap, all_papers, client)

        gap["validation_status"] = assessment.get("status", "open")
        gap["validation_reasoning"] = assessment.get("reasoning", "")
        gap["existing_papers"] = all_papers[:5]
        gap["search_query_used"] = query

        # B18 fix: only cache a genuine, confident assessment -- never the
        # degraded heuristic fallback (AD-2).
        if cacheable_gap and cacheable:
            save_cached_gap_validation(cache_key, gap_hash, domain_hash, GAP_VALIDATION_STAGE_VERSION, {
                "validation_status": gap["validation_status"],
                "validation_reasoning": gap["validation_reasoning"],
                "existing_papers": gap["existing_papers"],
                "search_query_used": gap["search_query_used"],
            })

        validated.append(gap)
        time.sleep(0.3)

    return validated
