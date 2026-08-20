---
baseline_commit: 87fa503c8dfa33652c667ab659a276ce9c26a3b0
---

# Story 2.5: Academic-API calls raise on failure and retry

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a ResGap user,
I want Semantic Scholar and arXiv search calls to actually retry on a rate-limit or transient failure,
so that a gap isn't wrongly marked "no relevant papers found" because of a 429.

## Scope note (read first)

The architecture spine's AD-5 "Binds" list is broader than this story: it also names `reference_extractor.py`'s lookup functions (`_ss_by_doi`, `_crossref_by_doi`, etc.) as governed by the same resilience rule. **This story is scoped to `academic_search.py` only**, matching `epics.md`'s literal Story 2.5 acceptance criteria — a deliberate, explicit scope decision confirmed with the project owner, not an oversight. `reference_extractor.py`'s lookup-function resilience is real, un-scheduled work that satisfies the remainder of AD-5; it needs its own future story (there is no slot for it in Epic 2 as currently numbered) — flag it if you notice it, do not fold it into this story.

## Acceptance Criteria

1. **Given** `_search_semantic_scholar` and `_search_arxiv` currently return `[]` silently on any non-200 response, **When** this story ships, **Then** both raise on a non-2xx response (`resp.raise_for_status()`) instead of silently falling through.
2. **Given** a raised exception from a non-2xx response, **When** the call is made, **Then** it is wrapped in a `tenacity` retry with exponential backoff and jitter, retrying before finally falling back to an empty result.
3. **Given** a Semantic Scholar call, **When** it is made, **Then** it includes a user-supplied API key header (stored the same way the existing NVIDIA NIM key is handled — a Streamlit sidebar `st.text_input(type="password")`, never hardcoded, never persisted to disk) when the user has provided one, rather than always calling unauthenticated. **Confirmed with the project owner:** unlike the NVIDIA key (which blocks the app via `st.stop()` if missing), the Semantic Scholar key is **optional, not blocking** — Semantic Scholar's API works unauthenticated at a lower rate limit (1 req/sec vs. 100 req/sec with a key), so this is a rate-limit upgrade, not a login wall. The app must remain usable with no Semantic Scholar key entered.

## Tasks / Subtasks

- [x] Task 1: Add `tenacity` as a project dependency (AC: #2)
  - [x] Add `tenacity>=9.1.4` to `requirements.txt`, alongside the existing pins (matches the architecture spine's verified-current version).
  - [x] Use `--with tenacity` in every `uv run` test invocation for this story, same convention as `--with openai --with pdfplumber` etc.
- [x] Task 2: Fix `_search_semantic_scholar` (`pipeline/academic_search.py`) (AC: #1, #2, #3)
  - [x] **Critical design point — read before implementing:** the current function wraps its entire body in `try: ... except Exception: pass; return []`. Simply adding `resp.raise_for_status()` *inside that same try block* would accomplish nothing — the raised `HTTPError` would be caught by the function's own `except Exception: pass` immediately, before `tenacity` (which sits *outside* this function, wrapping a call to it) ever sees it. **The retryable HTTP call must be split into its own inner function** that `tenacity`'s `@retry` decorator wraps directly; the outer `_search_semantic_scholar` catches only the *final* exception after all retries are exhausted, and only there falls back to `[]`.
    ```python
    def _is_retryable_search_error(exc: BaseException) -> bool:
        """Only retry genuinely transient conditions -- a network blip or a
        429 -- not a permanent 4xx client error that retrying can't fix
        (matches AD-5's stated intent: "a transient rate-limit or network
        blip", not "any failure whatsoever")."""
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
        resp = requests.get(SEMANTIC_SCHOLAR_BASE, params={"query": query, "limit": limit, "fields": FIELDS},
                             headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()


    def _search_semantic_scholar(query: str, limit: int = 5, api_key: str = "") -> list:
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
    ```
  - [x] `api_key: str = ""` is a new parameter — `headers = {"x-api-key": api_key} if api_key else {}` (verified: Semantic Scholar's Graph API reads an optional `x-api-key` header; the API works unauthenticated at 1 req/sec, and an API key raises the limit to 100 req/sec). **Confirmed optional, not mandatory** — see AC #3.
- [x] Task 3: Fix `_search_arxiv` (`pipeline/academic_search.py`) (AC: #1, #2)
  - [x] Same split-function pattern as Task 2 — arXiv has no API key concept (AC #3 only applies to Semantic Scholar), so this is simpler:
    ```python
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


    def _search_arxiv(query: str, limit: int = 3) -> list:
        params = {"search_query": f"all:{urllib.parse.quote(query)}", "start": 0,
                  "max_results": limit, "sortBy": "relevance", "sortOrder": "descending"}
        try:
            content = _fetch_arxiv(params)
        except Exception:
            return []
        entries = re.findall(r'<entry>(.*?)</entry>', content, re.DOTALL)
        results = []
        for entry in entries:
            # ... unchanged parsing logic ...
        return results
    ```
    **Reuse `_is_retryable_search_error` from Task 2 unmodified** — it's generic over any `requests` exception, not Semantic-Scholar-specific.
  - [x] Do **not** touch `_build_search_query` (the unquoted `all:` query bug is Story 2.6, explicitly out of scope here even though you'll be looking straight at the line that constructs `params["search_query"]`).
- [x] Task 4: Thread the Semantic Scholar API key from the UI through to `_search_semantic_scholar` (AC: #3)
  - [x] `pipeline/academic_search.py`'s `validate_gaps(gaps: list, client, domain_config: dict = None) -> list` gains a new parameter: `ss_api_key: str = ""`. Pass it through to the one call site of `_search_semantic_scholar(query, limit=5)` → `_search_semantic_scholar(query, limit=5, api_key=ss_api_key)`.
  - [x] `app.py`: add a second sidebar input mirroring the existing NVIDIA key input pattern (`app.py` lines ~604-608), placed directly below it, before the `st.markdown("---")` separator:
    ```python
    ss_api_key = st.text_input("Semantic Scholar API Key (optional)", type="password",
                                placeholder="Leave blank to use the free, rate-limited tier")
    st.markdown('<div style="font-family:\'DM Mono\',monospace;font-size:0.62rem;color:#484f58;">'
                '🔗 <a href="https://www.semanticscholar.org/product/api" target="_blank" style="color:#58a6ff;">'
                'Get key → semanticscholar.org/product/api</a></div>', unsafe_allow_html=True)
    ```
  - [x] Update the single `validate_gaps(...)` call site (`app.py` line ~833) to pass `ss_api_key=ss_api_key.strip()`.
- [x] Task 5: Add targeted tests (AC: #1, #2, #3)
  - [x] New `tests/test_academic_search_resilience.py`:
    - `_search_semantic_scholar` on a 429 response retries (mock `requests.get` with a `side_effect` list: two 429 responses then a 200) and eventually returns real results — proves retry-then-succeed.
    - `_search_semantic_scholar` on a persistent 429 (all attempts fail) falls back to `[]` after exhausting retries, not an unhandled exception — proves the "finally falling back to an empty result" half of AC #2.
    - `_search_semantic_scholar` on a 404 (a permanent, non-retryable client error) does **not** retry — mock `requests.get` and assert `call_count == 1` after a single 404 response, proving `_is_retryable_search_error` correctly excludes non-transient errors (a design point beyond the AC's literal text — verify it, since a naive "retry on everything" implementation would fail this test by retrying 3 times instead of 1).
    - `_search_semantic_scholar` sends the `x-api-key` header when `api_key` is provided, and omits it (empty headers dict) when not — inspect the `headers` kwarg on the mocked `requests.get` call.
    - `_search_arxiv` on a 429 retries and eventually succeeds; on a persistent failure falls back to `[]`; on a 404 does not retry. Mirror the same three tests as `_search_semantic_scholar`'s first three, reusing `_is_retryable_search_error`.
    - `validate_gaps` passes `ss_api_key` through to `_search_semantic_scholar` — patch `pipeline.academic_search._search_semantic_scholar` and assert it was called with the `api_key` kwarg matching what was passed into `validate_gaps`.
  - [x] Use `unittest.mock.patch("pipeline.academic_search.requests.get")` with a `side_effect` list of mock response objects (`status_code`, `.raise_for_status()` that raises `requests.exceptions.HTTPError(response=<mock response with matching status_code>)` when `status_code` is not 2xx — **must** attach the mock response via `response=...`, not a bare `HTTPError()`, since `_is_retryable_search_error` reads `exc.response.status_code` and a bare `HTTPError` has `exc.response is None`, which would make the 429-retry test fail by evaluating as non-retryable; `.json()`/`.text` as needed) to simulate the retry sequence — do not make real network calls, and do not real-sleep between retries (patch `pipeline.academic_search.time.sleep` — this also intercepts `tenacity`'s own internal sleep calls, since `tenacity` calls the same shared `time.sleep` — confirm test runtime stays sub-second before considering the task done).
  - [x] Add `from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception` to the top of `pipeline/academic_search.py` (easy to forget while focused on the retry logic itself — the code blocks in Tasks 2/3 use these names without this import).
- [x] Task 6: Bump `GAP_VALIDATION_STAGE_VERSION` to invalidate stale cache entries (AC: none directly, but resolves a named cross-story risk)
  - [x] Change `GAP_VALIDATION_STAGE_VERSION = 1` to `GAP_VALIDATION_STAGE_VERSION = 2` in `pipeline/academic_search.py`, **only after** Tasks 1-5 are complete and tested. Story 2.4's own `deferred-work.md` entry explicitly asks for this: entries cached under version 1 may have recorded a false "open, no evidence" verdict caused by a transient search failure that looked identical to a genuine empty result — this story is what fixes that root cause, so bumping the version here invalidates any pre-fix entries rather than leaving them to serve stale false negatives indefinitely.
  - [x] No test required for this bump specifically — `tests/test_academic_search_cache.py`'s existing `test_stage_version_bump_bypasses_and_repopulates` (Story 2.4) already proves a version change causes a real cache miss; this task just performs that bump for real, once, as this story's final step.

### Review Findings

**Reduced-coverage review — 2 of 3 layers unavailable.** Blind Hunter and Edge Case Hunter both failed to complete (session usage limit, resets 4pm Asia/Colombo — a hard resource cap, not a content/timeout issue that a same-session retry would fix). Only the Acceptance Auditor completed. Per the code-review skill's own `failed_layers` protocol, this is presented as a reduced-coverage pass, not a full clean review — proceeding on it was an explicit user decision ("continue"), matching this session's established precedent (Story 1.2 hit the same situation with 2 interrupted reviewers and proceeded the same way).

- [x] [Review][Patch] **Task 5's top-level checkbox was unchecked despite all 6 of its subtasks being checked** — a documentation bookkeeping slip, not a code defect. Caught by the Acceptance Auditor. **Fixed:** checkbox corrected.
- [x] [Review][Dismiss] No other findings — Acceptance Auditor confirmed all 3 ACs and all 6 explicit Dev Notes/Tasks design points are satisfied exactly as specified, with no violations, deviations, or missing behavior.

**Not independently verified by this review pass** (would normally be Blind Hunter/Edge Case Hunter's job): adversarial edge cases in the retry/backoff logic, mechanical path coverage of `_is_retryable_search_error`'s branches, resource-leak or race-condition concerns, and anything requiring a skeptical outside read rather than a spec-compliance check. **Recommend re-running `bmad-code-review` for this story once the session limit resets**, to get the coverage this pass missed — flagged here so it isn't silently forgotten.

**Post-review suite:** 103/103 tests passing (unchanged — the one fix was documentation-only).

## Dev Notes

- **This is the first story in Epic 2 that isn't a caching story** — it's resilience, per AD-5, not AD-2/AD-3. No `utils/database.py` changes at all.
- **The split-function pattern (Task 2/3) is this story's single most important, easy-to-get-wrong point.** A dev agent pattern-matching "just call `resp.raise_for_status()`" without noticing the enclosing `try/except Exception: pass` would produce code that compiles, passes a shallow read, and does *nothing* — the exact kind of silent-no-op bug AD-5 exists to eliminate. Get the inner/outer function split right.
- **Retry selectivity (`_is_retryable_search_error`) is a deliberate design choice beyond the AC's literal text**, justified directly by AD-5's own "Prevents" rationale ("a transient rate-limit (429) or network blip") — retrying a permanent 404/401/403 wastes time and doesn't fix anything. Do not simplify this to `retry_if_exception_type(Exception)` ("retry on anything") — that would be technically AC-compliant but misses AD-5's actual intent, and Task 5's 404-doesn't-retry test would catch the difference.
- **`ss_api_key` is optional, not required** (Task 2's note) — this preserves ResGap's today's zero-friction "just paste your NVIDIA key and go" flow for users who haven't separately obtained a Semantic Scholar key. Verified via Semantic Scholar's own API docs: unauthenticated requests work at 1 req/sec, an API key raises that to 100 req/sec — this is a rate-limit upgrade, not an authentication requirement.
- **Cross-story follow-up already logged**: Story 2.4's `deferred-work.md` entry notes that `GAP_VALIDATION_STAGE_VERSION` should be bumped when Story 2.5 ships — see Task 6, which is the actual, checkbox-tracked implementation of this note (do not treat this Dev Notes paragraph as sufficient on its own; Task 6 is authoritative).
- **Not in scope:** `reference_extractor.py`'s lookup functions (see Scope note above) and `_search_arxiv`'s query-construction bug (Story 2.6, unquoted `all:` query). Both are adjacent, easy to notice while reading these files, and out of scope here.

### Current State of `academic_search.py` (file being modified — read in full)

```python
import requests
import urllib.parse
import time
import re
import json
from utils.azure_client import unwrap
from utils.database import compute_cache_key, get_cached_gap_validation, save_cached_gap_validation

GAP_VALIDATION_STAGE_VERSION = 1          # ← Task 6: bump to 2 as the final step

SEMANTIC_SCHOLAR_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
ARXIV_BASE = "http://export.arxiv.org/api/query"
FIELDS = "title,year,abstract,citationCount,authors"


def _search_semantic_scholar(query: str, limit: int = 5) -> list:      # ← Task 2/4: gains api_key param
    params = {"query": query, "limit": limit, "fields": FIELDS}
    try:                                                                # ← Task 2: this try/except is the trap --
        resp = requests.get(SEMANTIC_SCHOLAR_BASE, params=params, timeout=10)  #   see Dev Notes
        if resp.status_code == 200:
            data = resp.json()
            papers = data.get("data", [])
            results = []
            for p in papers:
                results.append({...})
            return results
    except Exception:
        pass
    return []


def _search_arxiv(query: str, limit: int = 3) -> list:                 # ← Task 3: same trap, no api_key needed
    params = {"search_query": f"all:{urllib.parse.quote(query)}", ...}  # ← Task 3: leave query construction alone (Story 2.6)
    try:
        resp = requests.get(ARXIV_BASE, params=params, timeout=10)
        if resp.status_code == 200:
            content = resp.text
            entries = re.findall(r'<entry>(.*?)</entry>', content, re.DOTALL)
            results = []
            for entry in entries:
                ...
            return results
    except Exception:
        pass
    return []


def validate_gaps(gaps: list, client, domain_config: dict = None) -> list:  # ← Task 4: gains ss_api_key param
    ...
    for gap in gaps:
        ...
        ss_papers = _search_semantic_scholar(query, limit=5)            # ← Task 4: pass api_key=ss_api_key
        time.sleep(0.5)
        arxiv_papers = _search_arxiv(query, limit=3)
        ...
```

### Project Structure Notes

- Two files touched: `pipeline/academic_search.py` (both search functions + `validate_gaps`'s new parameter), `app.py` (new sidebar input + one call-site update). Plus `requirements.txt` (one line).
- Aligns with AD-1 — no new cross-boundary imports; `tenacity` is a third-party package, not a project module.
- `validate_gaps`'s signature grows by one optional, defaulted parameter (`ss_api_key: str = ""`) — backward compatible with the existing single call site if the default is used, though this story updates that call site anyway.

### Testing Standards

- Continues the established convention: stdlib `unittest`, `tests/` directory. This story introduces the project's first use of `tenacity` in a test context — mock at the `requests.get` level (not by disabling `tenacity` itself) so the retry behavior is genuinely exercised, not bypassed.
- Keep retry tests fast: 3 attempts with real exponential-jitter waits could add real seconds per test if not mocked/overridden — confirm test runtime stays in the sub-second-per-test range established by every prior Epic 2 test file before considering the task done.

### References

- [Source: `_bmad-output/planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md#AD-5` — binding list, rationale, and the tenacity/requests.raise_for_status()/SS-API-key rule]
- [Source: `_bmad-output/planning-artifacts/epics.md#Epic-2-Story-2.5`]
- [Source: `_bmad-output/implementation-artifacts/2-4-cache-gap-validation-results.md` Dev Notes/deferred-work.md — the accepted-risk note this story directly resolves via the `GAP_VALIDATION_STAGE_VERSION` bump]
- [Source: `pipeline/academic_search.py` — full file read, current `_search_semantic_scholar`/`_search_arxiv`/`validate_gaps` implementation post-Story-2.4]
- [Source: `app.py` lines 590-619, 833 — existing NVIDIA API key sidebar input pattern and the one `validate_gaps` call site]
- [Source: Semantic Scholar Academic Graph API tutorial (semanticscholar.org/product/api/tutorial), web-verified 2026-08-05 — confirms `x-api-key` header name, optional-key behavior (1 req/sec unauthenticated vs. 100 req/sec with a key)]
- [Source: Tenacity documentation (tenacity.readthedocs.io), web-verified 2026-08-05 — confirms `stop_after_attempt`, `retry_if_exception_type`, `retry_if_exception`, and `wait_exponential_jitter(initial=, max=)` are current, real APIs matching the architecture spine's pinned `tenacity>=9.1.4`]

## Change Log

- 2026-08-05: `requirements.txt` — added `tenacity>=9.1.4`. `pipeline/academic_search.py` — `_search_semantic_scholar`/`_search_arxiv` split into an inner `tenacity`-wrapped fetch function (raises via `resp.raise_for_status()`, retries only transient conditions via `_is_retryable_search_error`: `ConnectionError`, `Timeout`, HTTP 429, HTTP 5xx) and an outer function that catches only the final post-retry exception and falls back to `[]`. `_search_semantic_scholar` gains an optional `api_key` parameter, sent as an `x-api-key` header when provided. `validate_gaps` gains an optional `ss_api_key` parameter, threaded through. `GAP_VALIDATION_STAGE_VERSION` bumped `1` → `2` (Task 6), invalidating any Story 2.4-era cache entries that may have recorded a false "open, no evidence" verdict caused by a transient search failure this story now fixes. `app.py` — new optional Semantic Scholar API key sidebar input, mirroring the existing NVIDIA key input pattern; the one `validate_gaps` call site updated to pass it through. Added `tests/test_academic_search_resilience.py` (9 tests).
- 2026-08-05 (code review pass, reduced coverage — 2 of 3 layers unavailable due to a session usage limit): fixed a documentation-only bookkeeping slip (Task 5's parent checkbox). No code changes. Recommend re-running the full 3-layer review once the session limit resets.

## Dev Agent Record

### Agent Model Used

Claude (BMAD dev-story workflow)

### Debug Log References

- RED confirmed per task group: `tests/test_academic_search_resilience.py` failed with call-count mismatches (e.g. `1 != 3` for the retry-then-succeed test) before Tasks 2/3 — the old code never actually raised, so `requests.get` was only ever called once regardless of the mocked status codes.
- **Real test-isolation bug caught and fixed during this story, not a pre-existing issue**: the first version of `ValidateGapsApiKeyThreadingTests` didn't monkeypatch `utils.database.DB_DIR`/`DB_PATH` (missed the `setUp`/`tearDown` pattern every other test class in this epic uses), so it ran against the *real* production `data/run_history.db` — the one the locally-running Streamlit dev server uses. Because `client` was a bare `MagicMock()`, `_assess_coverage`'s `unwrap(client.chat_json(...))` call raised (a `MagicMock` isn't a `Success`), caught by `_assess_coverage`'s own `except Exception`, but the search functions were mocked to return `[]`, so `_assess_coverage`'s empty-`found_papers` path fired first and returned a genuine, `cacheable=True` "open, no evidence" result — which got written into the real database with the test's fixture title/description as `search_query_used`. Caught when the full suite (not just this file in isolation) failed with `Called 0 times` — a second run of the same test hit the leftover cache entry from the first. Fixed by adding proper `setUp`/`tearDown` isolation to the test class, and manually deleted the one polluted row from `data/run_history.db` (verified via direct SQLite query before and after deletion).
- A second, expected test breakage: Story 2.4's own `test_stage_version_bump_bypasses_and_repopulates` hardcoded `patch.object(academic_search, "GAP_VALIDATION_STAGE_VERSION", 2)` to simulate "the bumped version" — once Task 6 made `2` the *real* value, that patch became a no-op (patching a value to itself), turning the test's expected cache-miss assertion into a failure. Fixed by computing the patched value relative to the current one (`academic_search.GAP_VALIDATION_STAGE_VERSION + 1`) instead of hardcoding `2`.
- Full suite: `uv run --python 3.11 --with openai --with pdfplumber --with PyMuPDF --with numpy --with scipy --with reportlab --with requests --with tenacity python -m unittest discover -s tests -v` → 103/103 pass (was 94 before this story).
- `py_compile` clean on `pipeline/academic_search.py` and `app.py`; `import pipeline; import utils.database` smoke test clean.

### Completion Notes List

- All 6 tasks complete; 9 new tests in `tests/test_academic_search_resilience.py`; 103/103 suite passing.
- Two scope/design ambiguities were resolved with explicit project-owner confirmation before implementation, not decided silently: (1) this story covers only `academic_search.py`, not `reference_extractor.py`'s lookup functions, despite AD-5's broader binding list — real backlog debt, no story slot exists for it yet; (2) the Semantic Scholar API key is optional, not a blocking requirement like the NVIDIA key, since the SS API works unauthenticated at a lower rate limit rather than requiring a login.
- The split-function retry pattern (Tasks 2/3) was implemented exactly as specified — a fresh-context reviewer independently traced the pre-existing `try/except Exception: pass` trap against the real code before implementation began and confirmed the design was necessary, not over-engineering.
- This story's own test suite caught a real bug in itself (see Debug Log) before it could pollute shared state further — a timely reminder that "isolate the test database" isn't optional boilerplate even for a story whose main focus is HTTP retry logic, not caching.

### File List

- Modified: `requirements.txt`
- Modified: `pipeline/academic_search.py`
- Modified: `app.py`
- Modified: `tests/test_academic_search_cache.py` (Story 2.4's version-bump test adjusted for the new real `GAP_VALIDATION_STAGE_VERSION`)
- Added: `tests/test_academic_search_resilience.py`
