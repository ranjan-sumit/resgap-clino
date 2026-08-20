---
baseline_commit: fb823be9b8c7a72656bab7258cfd85b9378f4fa3
---

# Story 2.6: Correct arXiv query construction

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a ResGap user,
I want the arXiv fallback search to match the actual topic of a gap,
so that validation results aren't polluted by off-topic papers matched on a single shared word.

## Acceptance Criteria

1. **Given** `_search_arxiv` currently builds an unquoted, space-separated `all:` query, **When** this story ships, **Then** the query groups the gap's search terms as explicit `AND`-joined terms (not a single quoted phrase — see Dev Notes for why phrase-quoting the whole query was rejected as the wrong choice of the AC's two allowed options).
2. **Given** a known multi-concept gap query (e.g. "Mendelian Randomization ADHD brain structure"), **When** searched, **Then** the constructed `search_query` requires every term to be present (`all:Mendelian AND all:Randomization AND all:ADHD AND all:brain AND all:structure`), not matched on any single word in isolation.

## Tasks / Subtasks

- [x] Task 1: Fix `_search_arxiv`'s query construction (`pipeline/academic_search.py`) (AC: #1, #2)
  - [x] **Design point — read before implementing: AND-joined terms, not a quoted phrase.** The AC allows either "a quoted phrase or explicit `AND`-joined terms" (both are valid arXiv syntax, verified below). This story uses **AND-joined terms**, not phrase-quoting, for a concrete, load-bearing reason: `query` here is not a natural short phrase — it comes from `_build_search_query()` (title + `missing_connection`/description, truncated to 120 chars) possibly further extended with a domain boost term (up to 150 chars total, in `validate_gaps`). A real paper's title/abstract will essentially never contain that entire string as an exact, contiguous, in-order phrase — wrapping the whole thing in `all:"..."` would make `_search_arxiv` return **zero results for almost every realistic query**, which is a worse outcome than today's bug (wrong-but-nonzero results). AND-joining individual terms guarantees every concept word is present somewhere in the paper, without requiring exact adjacency — this actually fixes AD-7's stated problem ("matches papers actually about the combined topic rather than any paper containing any one word") while keeping the search functional.
  - [x] **Verified arXiv query syntax** (web-verified against the official arXiv API User's Manual, 2026-08-05 — do not guess at this, it's easy to get subtly wrong): field-prefixed terms are joined with the literal `AND` operator between them, e.g. the manual's own example `au:del_maestro AND ti:checkerboard` (space-encoded as `+` becomes `au:del_maestro+AND+ti:checkerboard` in the URL). Phrase search is `field:"multi word phrase"` (quotes encode to `%22`, spaces to `+`) — confirms both AC options are real, valid syntax; this story deliberately picks the AND-join option per the reasoning above. Repeating the same field prefix (`all:`) for each ANDed term, rather than mixing different fields, is a direct, conservative extension of the manual's own demonstrated pattern.
  - [x] Add a new helper:
    ```python
    def _build_arxiv_query(query: str) -> str:
        """Group search terms so arXiv matches papers about the combined
        concept, not any paper containing any single word (AD-7). AND-joins
        each whitespace-split term under its own all: field prefix -- NOT a
        single quoted phrase; see Story 2.6 Dev Notes for why phrase-quoting
        a full multi-concept query would return zero results in practice."""
        terms = [t for t in query.split() if t]
        if not terms:
            return "all:"
        return " AND ".join(f"all:{t}" for t in terms)
    ```
  - [x] Replace `"search_query": f"all:{urllib.parse.quote(query)}"` with `"search_query": _build_arxiv_query(query)`. **Do not manually call `urllib.parse.quote()` on the query content at all** — `requests`' own `params=` dict handles all URL encoding (spaces → `+`, matching the manual's documented format) when it builds the final request URL. **This also fixes a separate, pre-existing double-encoding bug**: the old code called `urllib.parse.quote()` manually and then passed the *already-percent-encoded* string into `params=`, which `requests` encodes *again* — turning e.g. `%20` into `%2520`. This wasn't AD-7's stated bug, but it's a real defect in the exact line this story touches, worth fixing alongside the AND/OR fix rather than leaving it for someone to rediscover later.
  - [x] `import urllib.parse` at the top of `pipeline/academic_search.py` becomes unused once this fix lands (confirmed via full-file read: nothing else in this file uses it). Remove the import.
  - [x] Do **not** touch `_build_search_query` (the function that builds the *input* to `_search_arxiv` — title/missing_connection/description truncation) or the boost-term logic in `validate_gaps`. This story is scoped to how the query is *encoded for arXiv specifically*, not how the query content itself is assembled.
  - [x] **Known, accepted limitation — do not fix in this story**: individual terms containing Lucene-significant characters (e.g. a term starting with `-`, or containing `:`/`"`/`(`/`)`) are inserted into the query unescaped and could be misinterpreted by arXiv's parser (a leading `-` reads as "NOT", for instance). This bug predates this story (the old code had the identical exposure inside its single unquoted blob) and AD-7's stated scope is specifically the OR-vs-AND grouping problem, not general Lucene-syntax injection safety. Flag it if you notice it; do not build a sanitizer for it here.
- [x] Task 2: Add targeted tests (AC: #1, #2)
  - [x] New `tests/test_academic_search_query.py`: `_build_arxiv_query("Mendelian Randomization ADHD brain structure")` returns `"all:Mendelian AND all:Randomization AND all:ADHD AND all:brain AND all:structure"` — the exact AC #2 example, asserted literally.
  - [x] `_build_arxiv_query` on a single-word query returns `"all:word"` (no dangling ` AND `).
  - [x] `_build_arxiv_query` on an empty string returns `"all:"` (matches the pre-existing behavior of the old code, which would also degrade to an essentially-empty query rather than crashing — don't introduce a new crash on an edge case the old code tolerated).
  - [x] `_search_arxiv` passes the `_build_arxiv_query(query)` output as `params["search_query"]` unmodified (no manual pre-encoding) — patch `pipeline.academic_search.requests.get` and inspect `mock_get.call_args.kwargs["params"]["search_query"]` directly, proving the double-encoding bug is actually gone (assert it does **not** contain a literal `%20` or `%25` substring — those would only appear if manual pre-encoding were still happening before `requests`' own encoding).
  - [x] Existing `tests/test_academic_search_resilience.py`'s `ArxivResilienceTests` tests (retry-on-429, persistent-failure-fallback, 404-no-retry) must still pass unmodified — this story changes *what* `search_query` contains, not the retry/fallback mechanics Story 2.5 already covers; confirm no regression.

### Review Findings

Acceptance Auditor and Blind Hunter independently converged on the same headline finding (the missed `GAP_VALIDATION_STAGE_VERSION` bump); Blind Hunter and Edge Case Hunter independently converged on a second (unescaped Lucene-significant characters in individual terms).

- [x] [Review][Patch] **`GAP_VALIDATION_STAGE_VERSION` was not bumped despite this story changing exactly the kind of logic its own module comment says triggers a bump** ("Bumped whenever the assessment prompt or search-query-construction logic changes..."). Every gap already cached under the old, OR-semantics arXiv query keeps being served unchanged from `get_cached_gap_validation` — this fix is invisible for every already-cached gap until the version is bumped. Independently flagged by Acceptance Auditor and Blind Hunter. [pipeline/academic_search.py:18]
- [x] [Review][Patch] **Raw character-slice truncation (`_build_search_query`'s `[:120]`, and `validate_gaps`'s boost-term `[:150]`) can cut the final word in half, and under the new strict AND semantics a mangled trailing fragment becomes a *mandatory* term.** Under the old OR-style query a truncated fragment was harmless noise; now it can single-handedly zero out results on any query long enough to hit the truncation limit — precisely the "zero results" failure mode this story's own docstring claims to be avoiding, reintroduced through an untouched code path. [pipeline/academic_search.py — `_build_search_query`, and `validate_gaps`'s `query = query[:150]` line]
- [x] [Review][Patch] **Individual terms are interpolated into `all:{t}` with no escaping of Lucene-significant characters or boolean-operator words.** A term containing `:`, `(`, `)`, `"`, or a term that is literally `AND`/`OR`/`NOT` (plausible given gap titles are LLM-generated) can be parsed by arXiv as a new field prefix or a boolean operator rather than literal search text, corrupting the query structure. Independently flagged by Blind Hunter and Edge Case Hunter. [pipeline/academic_search.py — `_build_arxiv_query`]
- [x] [Review][Patch] **`test_search_query_param_is_and_joined_and_not_pre_encoded` is a tautology, not a real regression guard.** It asserts `%20`/`%25` are absent from the *pre-request Python string* `_build_arxiv_query` builds — which by construction only ever contains letters/spaces/colons/`AND`, so it can never contain a `%`-encoded sequence regardless of whether double-encoding happens at the transport layer. The test never inspects the actual outgoing (prepared) request URL, so it doesn't prove what its name claims.
- [x] [Review][Patch] **`_build_arxiv_query(query)` and the rest of `params` construction sit outside `_search_arxiv`'s `try/except Exception: return []`.** A non-string/`None` `query` would raise an uncaught exception, unlike every other failure path in this function (and in every sibling function in this file), which degrades to `[]`.
- [x] [Review][Defer] Stopword filtering under strict AND semantics — common filler words ("of", "in", "with") in a title+description query now must also match, trading the old false-positive problem for a potential false-negative (recall) problem on longer, stopword-laden queries. Deferred — a genuine future quality refinement, but beyond AD-7's stated scope (fixing the OR-vs-AND grouping bug specifically, not general search-quality tuning).
- [x] [Review][Defer] Duplicate terms (e.g. "gene gene expression" → `all:gene AND all:gene AND all:expression`) are not deduplicated. Deferred — cosmetic redundancy, not a correctness bug; low priority.
- [x] [Review][Defer] AND-joining makes the effective query string longer (each term now carries a 4-char `all:` prefix plus ` AND `) with no check against any arXiv API query-length limit. Deferred — no evidence of an actual limit being hit in practice; revisit if observed.
- [x] [Review][Defer] The Lucene-character sanitization being patched (colons/parens/quotes/boolean-operator-words) is a minimal, targeted set, not exhaustive Lucene-reserved-character escaping (`+`, `-`, `[`, `]`, `^`, `~`, `*`, `?`, `\` are not handled). Deferred — the patched set covers the most likely and most dangerous cases from LLM-generated gap titles; full Lucene escaping is a broader, more open-ended defensive-programming task.
- [x] [Review][Dismiss] "`_build_arxiv_query("")` returns the malformed fragment `\"all:\"`, sent to a live API with unknown behavior." This is unchanged, pre-existing behavior from before this story (the old code also produced `"all:"` for empty input via `f"all:{urllib.parse.quote('')}"`), explicitly matched on purpose per this story's own Task 2 note ("matches the pre-existing behavior of the old code... don't introduce a new crash on an edge case the old code tolerated"). Not a regression.
- [x] [Review][Dismiss] "The docstring's 'would return zero results' claim is asserted, not demonstrated via a live arXiv API call." A reasoned engineering judgment call, not empirically proven via a live network test — consistent with this entire project's testing convention (mocked tests only, no real network calls in the suite, established since Story 2.1). Not a gap specific to this story.

**Post-review suite:** 117/117 tests passing (was 108; +9 new across sanitization, real-PreparedRequest encoding verification, non-string-query safety, and word-boundary-truncation coverage; the tautological double-encoding test was replaced rather than merely supplemented. Production code hardened against the truncation-collision risk, unescaped terms, and the uncaught-exception path).

## Dev Notes

- **This is the last story in Epic 2.** After this, Epic 2 (`epic-2` in `sprint-status.yaml`) should be marked `done`.
- **The AND-vs-phrase choice (Task 1's first bullet) is this story's one real design decision** — both are valid arXiv syntax per the verified manual, so this isn't a "which one is technically correct" question, it's "which one actually works for this codebase's realistic query shapes." AND-joining was chosen because `_build_search_query`'s output (title + missing_connection/description, up to 150 chars after boost) is not phrase-shaped text — read that reasoning before considering phrase-quoting as an "equally valid alternative implementation," it isn't, for this specific input shape.
- **Not in scope:** `_search_semantic_scholar`'s query (already a single unquoted `query` param — Semantic Scholar's own search endpoint does substring/relevance matching across the query as a whole differently from arXiv's Lucene-style field:term parser, and AD-7 binds only `_search_arxiv`). `_build_search_query`'s own construction logic (title/missing_connection/description assembly) — untouched, this story only changes how the assembled string gets turned into arXiv's specific query syntax.
- **The double-encoding fix (Task 1) is a bonus correctness fix directly enabled by this story's changes, not scope creep** — it's the same one line of code this story has to touch anyway to fix AD-7's stated bug; leaving the double-encoding in place while fixing the OR/AND issue would be an odd half-fix of the exact same construction logic.

### Current State of `_search_arxiv` (file being modified — read in full, post-Story-2.5)

```python
def _search_arxiv(query: str, limit: int = 3) -> list:
    """Search arXiv as a backup academic source."""
    params = {
        "search_query": f"all:{urllib.parse.quote(query)}",      # ← Task 1: replace this line
        "start": 0,
        "max_results": limit,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    try:
        content = _fetch_arxiv(params)          # ← unchanged: Story 2.5's retry wrapper, don't touch
    except Exception:
        return []
    entries = re.findall(r'<entry>(.*?)</entry>', content, re.DOTALL)
    # ... unchanged parsing logic ...
    return results
```

### Project Structure Notes

- One file touched for logic: `pipeline/academic_search.py` (one line replaced with a call to a new helper function, plus an unused import removed).
- Aligns with AD-1 — no new imports beyond stdlib (`urllib.parse` is being *removed*, not added).
- `_search_arxiv`'s public signature is unchanged (`_search_arxiv(query: str, limit: int = 3) -> list`); `_build_arxiv_query` is a new private helper, no existing call sites to update beyond the one line inside `_search_arxiv` itself.

### Testing Standards

- Continues the established convention: stdlib `unittest`, `tests/` directory.
- This story's tests are pure query-construction unit tests (`_build_arxiv_query` in isolation) plus one integration-level check that `_search_arxiv` actually uses it correctly — no need to mock the full retry/response-parsing machinery Story 2.5's `test_academic_search_resilience.py` already covers.

### References

- [Source: `_bmad-output/planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md#AD-7` — binding, rationale (the live-reproduced CMB-polarisation-paper example), and the phrase-or-AND rule]
- [Source: `_bmad-output/planning-artifacts/epics.md#Epic-2-Story-2.6`]
- [Source: `pipeline/academic_search.py` — full file read, current `_search_arxiv`/`_build_search_query` implementation post-Story-2.5]
- [Source: arXiv API User's Manual, search query construction (info.arxiv.org/help/api/user-manual.html), web-verified 2026-08-05 — confirms `field:term AND field:term` and `field:"phrase"` syntax, and the `+`-for-space/`%22`-for-quote URL encoding convention the fix relies on]
- [Source: `_bmad-output/implementation-artifacts/2-5-academic-api-calls-raise-on-failure-and-retry.md` — established that `_build_search_query`/query-construction-adjacent code in this file was deliberately left untouched pending this story]

## Change Log

- 2026-08-05: `pipeline/academic_search.py` — added `_build_arxiv_query()`, which AND-joins each whitespace-split search term under its own `all:` field prefix (`all:term1 AND all:term2 ...`), replacing the old unquoted, space-separated `all:` blob that arXiv parsed as an OR across individual words. `_search_arxiv` no longer manually pre-encodes the query with `urllib.parse.quote()` — `requests`' own `params=` encoding handles it, fixing a separate pre-existing double-encoding bug (`%20` becoming `%2520`) in the same line. Removed the now-unused `import urllib.parse`. Added `tests/test_academic_search_query.py` (5 tests).
- 2026-08-05 (code review pass): bumped `GAP_VALIDATION_STAGE_VERSION` `2` → `3` (this story changes search-query-construction logic, exactly what the module's own comment says triggers a bump — missed initially, caught by two independent reviewers). Added `_truncate_at_word_boundary()` and applied it to both of `_build_search_query`'s truncation points and `validate_gaps`'s boost-term truncation, so a raw character-slice can no longer leave a mangled trailing word fragment that becomes a mandatory (and likely unmatchable) AND term. `_build_arxiv_query` now strips Lucene-reserved characters (`:`, `(`, `)`, `"`) from each term and drops literal `AND`/`OR`/`NOT` terms. `_search_arxiv` now builds `params` (including the `_build_arxiv_query` call) inside its `try/except`, so a non-string query degrades to `[]` like every other failure path instead of raising uncaught. Replaced a tautological test with one that inspects a real `requests.PreparedRequest` URL. Added 9 more tests. Final: 117/117 passing.

## Dev Agent Record

### Agent Model Used

Claude (BMAD dev-story workflow)

### Debug Log References

- RED confirmed: `tests/test_academic_search_query.py` failed with `ImportError: cannot import name '_build_arxiv_query'` before Task 1 (the function didn't exist yet).
- Full suite: `uv run --python 3.11 --with openai --with pdfplumber --with PyMuPDF --with numpy --with scipy --with reportlab --with requests --with tenacity python -m unittest discover -s tests -v` → 108/108 pass (was 103 before this story).
- `py_compile` clean on `pipeline/academic_search.py`; `import pipeline; import utils.database` smoke test clean.
- Code review (3-layer, all completed — session limit that blocked Story 2.5's review had cleared by this point): Acceptance Auditor and Blind Hunter independently converged on the missed `GAP_VALIDATION_STAGE_VERSION` bump; Blind Hunter and Edge Case Hunter independently converged on unescaped Lucene-reserved characters. 5 patches applied, 4 deferred, 2 dismissed. Post-review suite: 117/117 pass.
- The exact arXiv query syntax (AND-joining across repeated `all:` field prefixes, `+`-for-space/`%22`-for-quote URL encoding) was verified against the official arXiv API User's Manual before implementation, not assumed — this is the one place in this story where guessing wrong would have shipped a plausible-looking but non-functional fix.

### Completion Notes List

- Both tasks complete; 5 new tests in `tests/test_academic_search_query.py`; 108/108 suite passing.
- This story's one real design decision — AND-joined terms vs. a single quoted phrase, both valid arXiv syntax per the AC — was resolved in favor of AND-joining specifically because `_build_search_query`'s output (title + missing_connection/description, up to 150 chars after domain boost) is not phrase-shaped text; a literal phrase match would return zero results for nearly every realistic gap query, which is a worse outcome than the bug being fixed.
- Found and fixed a second, unrelated bug in the same line while implementing the AC's required fix: the old code manually pre-encoded the query with `urllib.parse.quote()` before handing it to `requests`' `params=` dict, which encodes it a second time — a genuine double-encoding defect, not scope creep, since it's the exact line this story has to touch anyway.
- This is the last story in Epic 2 — `epic-2` in `sprint-status.yaml` should be marked `done` once this story's review completes.
- Code review caught a real, severe interaction I hadn't considered while writing the story: this story's own fix (strict AND semantics) combined with an *untouched, pre-existing* code path (raw character-slice truncation) could reintroduce the exact "zero results" failure mode the story's docstring claims to prevent. Neither Task 1's original text nor its "do not touch `_build_search_query`" instruction anticipated this — a good example of why "don't touch adjacent code" boundaries need to be revisited when a reviewer demonstrates a real interaction, not held rigidly once new evidence appears.

### File List

- Modified: `pipeline/academic_search.py`
- Modified: `tests/test_academic_search_query.py`
