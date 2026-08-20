---
baseline_commit: ce012b33e34ba7c8806c4fd881d70614ebc270aa
---

# Story 2.2: Cache extracted parameters

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a ResGap user,
I want a paper's extracted quantitative parameters to be cached,
so that re-analyzing a previously-uploaded paper doesn't re-spend the parameter-extraction LLM call.

## Acceptance Criteria

1. **Given** `utils/database.py`, **When** this story ships, **Then** a new `parameters` table exists with columns `cache_key` (PK), `content_hash`, `stage_logic_version`, `params_json` — no `domain_hash` column, since parameter extraction is domain-invariant per AD-3 (`PARAM_EXTRACTION_PROMPT` has no `inject_domain_into_*` call anywhere in `param_extractor.py` — confirmed by reading the file in full).
2. **Given** `extract_parameters` processes a paper, **When** a matching `cache_key` already has a row, **Then** the cached `params_json` is returned for that paper and no `chat_json` call is made for it.
3. **Given** no matching `cache_key` exists, **When** extraction completes with a `Success` result, **Then** the result is cached; a `Failure`/`LLMCallError` path is never cached.

## Tasks / Subtasks

- [x] Task 1: Add the `parameters` table and cache read/write functions to `utils/database.py` (AC: #1, #2, #3)
  - [x] Add `CREATE TABLE IF NOT EXISTS parameters (cache_key TEXT PRIMARY KEY, content_hash TEXT, stage_logic_version INTEGER, params_json TEXT)` to `init_db()`'s executescript, alongside `wiki_pages`
  - [x] Add `def get_cached_parameters(cache_key: str) -> list | None:` — call `init_db()` first, `SELECT params_json FROM parameters WHERE cache_key = ?`; return `json.loads(row["params_json"])` on a hit, `None` on a miss **or on a corrupted row** (wrap the `json.loads` in `try/except json.JSONDecodeError: return None`, matching `get_cached_wiki_page`'s Story-2.1-review-hardened pattern — don't reintroduce the bug that was just fixed there)
  - [x] Add `def save_cached_parameters(cache_key: str, content_hash: str, stage_logic_version: int, params_json: list) -> None:` — call `init_db()` first, `INSERT OR REPLACE INTO parameters (...) VALUES (...)`, `json.dumps(params_json, default=str)`
  - [x] Reuse `compute_cache_key()` from Story 2.1 unmodified — call it with `relevant_domain_keys=[]` (domain-invariant), which correctly produces `domain_hash == "none"` per that story's review-tightened contract; the returned `domain_hash` is simply not persisted (this table has no column for it)
- [x] Task 2: Wire caching into `extract_parameters` (`pipeline/param_extractor.py`) (AC: #2, #3)
  - [x] Add module constant `PARAM_STAGE_VERSION = 1`
  - [x] **Critical design point — read before implementing:** the cache key's `content` must be the exact `context` string this stage builds and sends to the LLM (`context = "\n\n".join(context_parts)`, built from the wiki page's `key_findings`/`limitations`/`methods`/`datasets`/`contributions` fields plus filtered paper sections/tables) — **not** `paper["full_text"]`. Unlike Story 2.1's wiki-compilation stage, this stage's actual LLM input is *derived from the compiled wiki page*, not the raw paper text. If the wiki page changes (e.g. a different domain selection produces different `key_findings`), the parameter-extraction input changes too even though `full_text` is identical — hashing `full_text` would incorrectly cache-hit on stale wiki-derived content. Compute the cache key **after** `context` is built, immediately before constructing `user_prompt`.
  - [x] Check the cache: `cache_key, content_hash, _ = compute_cache_key(context, None, [], PARAM_STAGE_VERSION); cached = get_cached_parameters(cache_key)`. On a hit, use `params = cached` and skip the `chat_json` call entirely for this paper.
  - [x] On a cache miss, proceed exactly as today (`unwrap(client.chat_json(...))`, `_robust_parse`), and on `Success`, call `save_cached_parameters(cache_key, content_hash, PARAM_STAGE_VERSION, params)` with the **raw** `params` list as returned by `_robust_parse` — i.e. cache it **before** the per-call augmentation described in the next bullet, not after.
  - [x] **Do not cache (or read from cache into) the per-call augmentation.** The existing loop sets `p["paper_index"] = i` and `p["source_paper"] = p.get("source_paper") or title`. Apply this augmentation **after** the cache read/write, unconditionally, to whatever `params` list is in hand (whether it came from the cache or a fresh LLM call).
  - [x] **`paper_index` vs. `source_paper` are not the same kind of field — treat them differently, and don't over-correct.** `paper_index` (this paper's position in *this run's* `zip(wiki_pages, papers)`) is pure bookkeeping with no connection to extracted content — it must be unconditionally overwritten (`p["paper_index"] = i`) every time, cached or fresh, exactly as the existing code already does. `source_paper`, by contrast, is part of the *extracted content itself* — the LLM may legitimately attribute a parameter to a specific comparison paper mentioned in the text, not just "this paper's own title" — so its existing `p.get("source_paper") or title` fallback is correct and must **not** be changed to force-override on a cache hit. Applying that same single augmentation block after the cache check (as this task already specifies) naturally gives both fields their correct behavior with no special-casing needed: `paper_index` gets freshly overwritten every time by virtue of being unconditional; `source_paper`'s fallback runs identically whether `params` came from cache or a fresh call, which *is* the correct, consistent behavior — a cached extraction's LLM-determined attribution isn't "stale" the way a raw filename would be. (This is *not* the same category of bug Story 2.1 fixed for `source_file`/`char_count` — those were pure upload-identity fields with no extracted-content meaning; caught during this story's own review, not deferred to a second round.)
  - [x] `LLMCallError` handling is unchanged from Story 1.2 (`params = []`, skip this paper) — just don't cache that empty-list outcome; only the `save_cached_parameters` call is new, gated the same way Story 2.1 gated `save_cached_wiki_page`
- [x] Task 3: Add targeted tests (AC: #1, #2, #3)
  - [x] `extract_parameters` cache miss then hit: for a single paper, first call invokes `chat_json` once; a second call with identical `wiki`/`papers`/`client` does not call `chat_json` again and returns equal parameter data
  - [x] Cache hit re-applies `paper_index` for the *current* call rather than trusting a cached value — fetch the same cached params for a paper at a different `i` than when they were cached, and assert the returned `paper_index` reflects the *current* call's position, not the original. **Do not** write an equivalent test asserting `source_paper` gets force-overridden — that would encode the incorrect behavior identified during this story's own review (see Task 2's `paper_index` vs. `source_paper` note); a correct test may assert `source_paper`'s existing `or title` fallback behaves identically on a cache hit vs. a fresh call, if useful, but not that it's overridden
  - [x] `LLMCallError` during extraction: `params = []` for that paper (existing Story 1.2 behavior, unchanged), and a direct `get_cached_parameters(cache_key)` lookup confirms nothing was cached
  - [x] A change to the wiki page's fields (e.g. different `key_findings`) for the same underlying paper produces a different `cache_key` and triggers a real second LLM call — proves the design point in Task 2 (hashing `context`, not `full_text`) actually matters and is correctly implemented
  - [x] Use the same real-SQLite-via-monkeypatched-`DB_PATH` test pattern established in `tests/test_database_cache.py`/`tests/test_wiki_compiler_cache.py`

### Review Findings

Edge Case Hunter and Blind Hunter independently converged on the same class of risk (unvalidated/unparseable cached content), each catching a different half of it; Acceptance Auditor found zero spec violations.

- [x] [Review][Patch] **A malformed/truncated "successful" LLM response permanently caches an empty params list.** `_robust_parse(raw, list)` returns `[]` both for a genuine empty extraction and for a `Success` response that fails every parse strategy (garbled/truncated JSON) — the new caching wiring cached that `[]` unconditionally on the Success path, freezing a transient parse failure as "no params" forever for that content hash. **Fixed:** added `_is_confidently_empty(raw)` and only cache when `params` is non-empty or the raw response is a confidently-parsed literal `[]`. [pipeline/param_extractor.py:161-166]
- [x] [Review][Patch] **`get_cached_parameters` didn't validate the parsed value was actually a list, and would crash on a NULL `params_json` column.** A tampered/migrated row with valid-but-wrong-typed JSON (e.g. `{}` or `42`) would flow through as a "hit" and crash the `for p in params` stamping loop; `json.loads(None)` raises an uncaught `TypeError` instead of the documented graceful miss. **Fixed:** now catches `TypeError` alongside `json.JSONDecodeError`, and returns `None` unless the parsed value is actually a `list`. [utils/database.py:151-165]
- [x] [Review][Patch] **`test_llm_call_error_is_never_cached` hardcoded the expected `context` string instead of deriving it from the same construction path `extract_parameters` uses** — if the context-building formula changes elsewhere, this test could silently stop testing what it claims to test. **Fixed:** test now spies on `compute_cache_key` to capture the real cache key production code computed, instead of duplicating the context-building formula. [tests/test_param_extractor_cache.py]
- [x] [Review][Patch] **No test exercised `PARAM_STAGE_VERSION` bump invalidating a previously-cached `parameters` entry** — the module comment's stated purpose (Story 2.1 precedent: `test_stage_version_bump_bypasses_a_previously_cached_entry`) was never verified for this table specifically. **Fixed:** added `test_stage_version_bump_bypasses_a_previously_cached_entry`.
- [x] [Review][Patch] **No test covered a same-run, duplicate-paper cache hit** (a write followed immediately by a read within a single `extract_parameters` call, rather than across two separate top-level calls as all four original tests do). **Fixed:** added `test_duplicate_paper_in_same_run_is_a_cache_hit`.
- [x] [Review][Defer] `get_cached_parameters`/`save_cached_parameters` have no `try/finally` around their SQLite calls, so a `sqlite3.OperationalError` (locked DB, disk full) would propagate out and abort the whole per-paper loop, contradicting the file's own "never abort the batch for one failure" philosophy (B6/B12 comments). Deferred — identical to Story 2.1's deferred finding for `get_cached_wiki_page`/`save_cached_wiki_page`; this is the existing convention throughout every function in `database.py`, and fixing only the two new functions here would be inconsistent. Broader file-wide fix is out of scope for this story.
- [x] [Review][Defer] **Residual collision risk**: two different papers whose `context` happens to be byte-identical (e.g. identical filenames both hitting the B6 zip-padding stub with empty wiki fields) would share a cached (empty) params result. Deferred — the Dev Notes already reasoned about and accepted this risk (unlike Story 2.1's empty-`full_text` collision, `context` always starts with `f"Paper: {title}"`, making a genuine collision require matching titles AND matching wiki-derived content); the realistic collision case (two identically-titled unparseable stub papers) has negligible blast radius since both would legitimately extract to an empty list anyway. Tracked for awareness, not an unambiguous code fix.
- [x] [Review][Defer] `content_hash` column is write-only — stored on every `save_cached_parameters` call but never read back or validated by any test. Deferred — mirrors the identical pre-existing gap in `wiki_pages.content_hash` from Story 2.1; this diff perpetuates rather than introduces it, and fixing both tables' dead-data columns is a broader change out of this story's scope.
- [x] [Review][Defer] Per-paper cache calls run a full `init_db()` executescript plus a fresh `sqlite3.connect`/close on every `get_cached_parameters`/`save_cached_parameters` call, with no connection reuse or batching across the loop. Deferred — this is the same architecture Story 2.1 already introduced for the wiki-cache stage; connection pooling/batching is a broader performance change out of this story's scope.
- [x] [Review][Defer] `derive_cross_paper_parameters` and `check_sufficiency` (same file) still call `unwrap(client.chat_json(...))` with no `try/except LLMCallError`, so a transient failure on either crashes the downstream stage uncaught. Deferred — explicitly out of scope per this story's own Dev Notes (only `extract_parameters`'s per-paper call is bound by AD-2's caching requirement); the LLMCallError-handling gap on these two functions is a pre-existing issue belonging to Story 1.2's lineage, not something this story introduced.
- [x] [Review][Defer] The `parameters` table (like `wiki_pages`) has no `run_id`/per-user namespace, so any two runs anywhere that produce byte-identical `context` share cached output. Deferred — this is an architecture-level decision (AD-3's domain-invariant, content-addressed caching design) inherited from Story 2.1's precedent, not something newly introduced or reconsidered by this story.
- [x] [Review][Defer] No cache-corruption observability (log line, counter) — a repeatedly-corrupted cache table degrades silently to "always miss" with no signal other than an unexplained drop in hit rate. Deferred — identical reasoning to Story 2.1's deferred finding: no established logging convention exists anywhere in this codebase yet.
- [x] [Review][Dismiss] "`save_cached_parameters(..., params_json: list)` — confusing naming, the arg is a Python list not a JSON string." Valid but cosmetic, and explicitly consistent with the existing `save_cached_wiki_page(..., wiki_json: dict)` naming precedent from Story 2.1 — not a new inconsistency, not worth a partial rename that would leave the two functions using different conventions.
- [x] [Review][Dismiss] "Every task checkbox is pre-marked `[x]` with no independent signal distinguishing dev-agent self-certification from reviewer verification." This finding is answered by the review step that produced it — the independent 3-layer review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) *is* that independent verification, running against a fresh, uninformed context each time.

**Post-review suite:** 57/57 tests passing (was 53; +4 new: malformed-response-not-cached, confidently-empty-response-is-cached [companion boundary test], stage-version-bump-for-parameters-table, same-run-duplicate-paper-cache-hit; existing hardcoded-context test rewritten to spy on `compute_cache_key` instead of duplicating its formula).

## Dev Notes

- **This story reuses `compute_cache_key()` from Story 2.1 unmodified** — no changes to that helper are needed or expected. If Story 2.1's tests still pass unmodified after this story, that's a good sign nothing was disturbed.
- **The `context`-not-`full_text` design point (Task 2) is this story's single most important, easy-to-get-wrong decision** — a dev agent pattern-matching on Story 2.1 without reading this section carefully could reasonably default to hashing `full_text` again, producing a cache that silently serves stale parameters after a wiki-page update. Get this right.
- **Collision risk considered and judged acceptable:** unlike Story 2.1's empty-`full_text` collision (fixed via a skip-cache guard), `context` here always starts with `f"Paper: {title}"` before any other content — two genuinely different papers producing an identical `context` string would require identical titles *and* identical wiki-derived fields *and* identical filtered sections/tables, which is not a realistic collision risk worth a special-case guard the way Story 2.1's fully-empty-string case was. No equivalent "skip cache" guard is needed here.
- **Not in scope:** `derive_cross_paper_parameters` and `check_sufficiency` (same file) are single-shot, non-looped calls — per the architecture spine and `epics.md`, only `extract_parameters`'s per-paper call is bound by the caching requirement (AD-2). Do not add caching to those two functions in this story.
- **The `# B6 FIX` zip-padding stub** (lines 107-118, pre-existing) already ensures every paper gets *some* wiki page, even a stub with empty fields, before this stage runs — no interaction with this story's caching logic beyond `context` naturally reflecting that stub's emptiness for whichever paper it applies to.

### Current State of `extract_parameters` (file being modified — read in full)

```python
def extract_parameters(wiki: dict, papers: list, client) -> list:
    all_params = []
    wiki_pages = wiki.get("pages", [])
    # ... B6 FIX zip-padding, unchanged, not shown ...

    for i, (page, paper) in enumerate(zip(wiki_pages, papers)):
        title = page.get("title", page.get("source_file", f"Paper {i+1}"))
        context_parts = [f"Paper: {title}"]
        # ... builds context_parts from page fields, paper sections, paper tables ...
        context = "\n\n".join(context_parts)                    # ← Task 2: hash THIS
        user_prompt = f"Extract ALL quantitative parameters...\n\n{context}"

        try:
            raw = unwrap(client.chat_json(PARAM_EXTRACTION_PROMPT, user_prompt, max_tokens=6000))
            params = _robust_parse(raw, list)                    # ← Task 2: cache THIS (raw, pre-augmentation)
        except LLMCallError:
            params = []                                          # ← never cache this

        for p in params:                                         # ← Task 2: augmentation — apply AFTER
            if not isinstance(p, dict):                           #   cache read/write, to whichever params
                continue                                          #   list is in hand (cached or fresh)
            p["paper_index"]  = i
            p["source_paper"] = p.get("source_paper") or title
            p.setdefault("is_derived", False)
            p.setdefault("derivation_note", None)

        all_params.extend(params)

    return all_params
```

### Project Structure Notes

- Two files touched: `utils/database.py` (new table + 2 new functions), `pipeline/param_extractor.py` (cache-check/cache-write wiring in `extract_parameters`).
- No `.gitignore` changes needed — Story 2.1 already covers the SQLite file and its sidecars.
- Aligns with AD-1 — `pipeline/param_extractor.py` already imports from `utils/*` (Story 1.2 added `unwrap`/`LLMCallError`); adding `compute_cache_key`/`get_cached_parameters`/`save_cached_parameters` from `utils.database` doesn't change the dependency direction.

### Testing Standards

- Continues the established convention: stdlib `unittest`, `tests/` directory, real-SQLite-via-monkeypatched-`DB_PATH` pattern (see `tests/test_database_cache.py`'s `setUp`/`tearDown` for the exact isolation approach — copy it, don't reinvent it).

### References

- [Source: `_bmad-output/planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md#AD-2`, `#AD-3`]
- [Source: `_bmad-output/planning-artifacts/epics.md#Epic-2-Story-2.2`]
- [Source: `_bmad-output/implementation-artifacts/2-1-cache-compiled-wiki-pages.md` — established `compute_cache_key()` contract and the stale-cached-field lesson this story applies proactively]
- [Source: `pipeline/param_extractor.py` — full file read, current `extract_parameters` implementation post-Story-1.2]
- [Source: `utils/database.py` — full file read, current schema/conventions post-Story-2.1]

## Change Log

- 2026-08-04: `utils/database.py` — added the `parameters` table (no `domain_hash` column, per AD-3 domain-invariance) and `get_cached_parameters()`/`save_cached_parameters()`, reusing `compute_cache_key()` from Story 2.1 unmodified. `pipeline/param_extractor.py` — `extract_parameters` now checks the cache (keyed on the wiki-derived `context` string, not `full_text`) before each paper's `chat_json` call and writes back only the raw, pre-augmentation params on a genuine `Success` (`# B16 fix`); never caches on `LLMCallError`. The `paper_index`/`source_paper` augmentation loop runs unconditionally after the cache read/write, on whichever `params` list is in hand. Added `tests/test_param_extractor_cache.py` (4 tests) and extended `tests/test_database_cache.py` with `ParametersCacheTests` (4 tests, mirroring `WikiPagesCacheTests`).
- 2026-08-05 (code review pass): fixed a malformed/truncated-but-"successful" LLM response permanently caching an empty params list (added `_is_confidently_empty()` gate — only caches non-empty params or a confidently-parsed literal `[]`). Hardened `get_cached_parameters` against a NULL `params_json` column and against a row whose JSON parses but isn't a list. Rewrote `test_llm_call_error_is_never_cached` to spy on `compute_cache_key` instead of hardcoding the expected context string. Added 4 more tests. Final: 57/57 passing.

## Dev Agent Record

### Agent Model Used

Claude (BMAD dev-story workflow)

### Debug Log References

- RED confirmed per task group: `tests/test_database_cache.py`'s `ParametersCacheTests` failed with `AttributeError: module 'utils.database' has no attribute 'get_cached_parameters'` before Task 1; `tests/test_param_extractor_cache.py` failed with `AttributeError: module 'pipeline.param_extractor' has no attribute 'PARAM_STAGE_VERSION'`, then call-count mismatches (`2 != 1`), before Task 2.
- Task 2's design correction was caught during this story's own create-story review (fresh-context reviewer), before any code was written: the original draft instructed force-overriding `source_paper` on every cache hit, mirroring Story 2.1's `source_file` fix. That's wrong — `source_paper` is extracted LLM content (may legitimately reference a different comparison paper), not pure upload-identity bookkeeping like `source_file`/`char_count` were. Corrected the story text to distinguish `paper_index` (unconditional overwrite, pure bookkeeping) from `source_paper` (existing `or title` fallback is correct, must not be forced) before implementation began.
- Full suite: `uv run --python 3.11 --with openai --with pdfplumber --with PyMuPDF --with numpy --with scipy --with reportlab --with requests python -m unittest discover -s tests -v` → 53/53 pass (was 45 before this story).
- `py_compile` clean on both modified files; `import pipeline; import utils.database` smoke test clean.
- Code review (3-layer, all completed): Acceptance Auditor found zero spec violations. Edge Case Hunter and Blind Hunter independently converged on the same class of risk (unvalidated/unparseable cached content) via different methods. 5 patches applied, 7 items deferred (all matching Story 2.1 precedent or explicitly out of this story's scope), 2 dismissed as noise.
- Post-review full suite: 57/57 pass (was 53). `py_compile` and import smoke test re-confirmed clean after patches.

### Completion Notes List

- Both tasks complete; 8 new tests total (4 `ParametersCacheTests` in `test_database_cache.py`, 4 in the new `test_param_extractor_cache.py`); 53/53 suite passing pre-review.
- `compute_cache_key()` reused unmodified from Story 2.1, called with `relevant_domain_keys=[]` (domain-invariant per AD-3, since `param_extractor.py` never calls any `inject_domain_into_*` function) — confirms the generic-reuse design Story 2.1 anticipated for this exact case.
- The `context`-not-`full_text` cache-key design point (Dev Notes' single most important, easy-to-get-wrong decision) was implemented and directly tested via `test_different_wiki_content_for_same_paper_is_a_cache_miss` — a wiki-page change (different `key_findings`) for the same underlying paper correctly triggers a real second LLM call.
- No design risk required a second implementation pass at the story-creation stage — the one identified there (the `source_paper` force-override mistake) was caught and corrected before dev-story began. Code review did catch a real implementation gap: caching an empty params list for a garbled/unparseable-but-technically-"Success" LLM response, which would have permanently frozen a transient failure. This is the same class of bug Story 2.1's review caught for the wiki-compiler's malformed-JSON path, just manifesting differently here because `_robust_parse` swallows parse failures into `[]` rather than raising.
- 4 of 5 patch findings were test-coverage gaps (missing PARAM_STAGE_VERSION-bump test, missing same-run-duplicate test, a brittle hardcoded-string test) rather than production-code bugs — only the malformed-response-caching gap and the `get_cached_parameters` type/None-safety gap were genuine production code fixes.

### File List

- Modified: `utils/database.py`
- Modified: `pipeline/param_extractor.py`
- Modified: `tests/test_database_cache.py`
- Added: `tests/test_param_extractor_cache.py` (created during initial implementation, extended during code review)
