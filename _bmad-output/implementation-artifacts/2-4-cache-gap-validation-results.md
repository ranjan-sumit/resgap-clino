---
baseline_commit: 1372430bc94fb73e4d596d4465da7a2e81a4cd3e
---

# Story 2.4: Cache gap validation results

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a ResGap user,
I want a gap's academic-search validation result to be cached,
so that re-validating the same gap under the same domain doesn't re-spend the search/LLM assessment calls.

## Acceptance Criteria

1. **Given** `utils/database.py`, **When** this story ships, **Then** a new `gap_validations` table exists with columns `cache_key` (PK), `gap_hash`, `domain_hash`, `stage_logic_version`, `validation_json` — **with** a `domain_hash` column (unlike `parameters`/`references`), since gap validation IS domain-conditioned per AD-3 (`validate_gaps` reads `domain_config.get("search_boost_terms")` via `get_search_boost_terms()` to boost the search query — confirmed by reading `domain_config.py` in full — and a different boost term can surface different papers for the same gap, changing the assessment).
2. **Given** a gap is validated, **When** a matching `cache_key` already has a row, **Then** the cached validation result (status, reasoning, found papers, and the search query used) is restored onto the gap and **neither the academic-search calls (`_search_semantic_scholar`/`_search_arxiv`) nor the LLM assessment call are made** — not just the LLM call. (This is broader than a literal reading of AD-2's binding list, which names only `academic_search._assess_coverage` — see Dev Notes for why the cache gate cannot live inside `_assess_coverage` alone and still satisfy this AC or the User Story's own stated goal of not re-spending the *search* calls either.)
3. **Given** no matching `cache_key` exists, **When** validation completes with a genuine, confident result (the LLM returned a cleanly-parsed assessment, **or** no papers were found at all — both are real, non-degraded conclusions), **Then** the result is cached. **When** the LLM call fails, or succeeds but returns no parseable JSON, **Then** the resulting heuristic fallback (`"partial"` if ≥2 recent papers were found, else `"open"`) is **never cached** — per AD-2, a degraded fallback must never be frozen into the cache as if it were a real assessment.

## Tasks / Subtasks

- [x] Task 1: Add the `gap_validations` table and cache read/write functions to `utils/database.py` (AC: #1, #2, #3)
  - [x] Add `CREATE TABLE IF NOT EXISTS gap_validations (cache_key TEXT PRIMARY KEY, gap_hash TEXT, domain_hash TEXT, stage_logic_version INTEGER, validation_json TEXT)` to `init_db()`'s executescript, alongside `"references"`. No reserved-word issue here — `gap_validations` is an ordinary identifier, unlike Story 2.3's `"references"`.
  - [x] Add `def get_cached_gap_validation(cache_key: str) -> dict | None:` — call `init_db()` first, `SELECT validation_json FROM gap_validations WHERE cache_key = ?`; return `None` on a miss, a corrupted/unparseable row, a `NULL` row, **and** a row whose JSON parses to something other than a `dict` (apply the same hardened pattern used for `get_cached_reference` in Story 2.3 — `except (json.JSONDecodeError, TypeError): return None` plus `isinstance(parsed, dict)` — from day one, no second review cycle needed).
  - [x] Add `def save_cached_gap_validation(cache_key: str, gap_hash: str, domain_hash: str, stage_logic_version: int, validation_json: dict) -> None:` — call `init_db()` first, `INSERT OR REPLACE INTO gap_validations (...) VALUES (...)`, `json.dumps(validation_json, default=str)`
  - [x] Reuse `compute_cache_key()` from Story 2.1 unmodified — call it with `relevant_domain_keys=["search_boost_terms"]` (the one and only domain_config key `validate_gaps` actually reads, via `get_search_boost_terms()`) so an unrelated domain_config change (e.g. `wiki_focus`, relevant only to Story 2.1's stage) doesn't cause a spurious cache miss here. This table gets a **real** `domain_hash`, not `"none"` — the first Epic 2 table since Story 2.1's `wiki_pages` to do so.
- [x] Task 2: Give `_assess_coverage` an unambiguous success/fallback signal (`pipeline/academic_search.py`) (AC: #3)
  - [x] **Read this before touching anything — this is the story's single most important, easy-to-get-wrong point.** `_assess_coverage`'s current code has **four** distinct paths that converge on returning a dict, but only **two** are genuine, cacheable results:
    ```python
    def _assess_coverage(gap: dict, found_papers: list, client) -> dict:
        if not found_papers:
            return {"status": "open", "reasoning": "No relevant papers found in academic search."}  # (a) GENUINE — confident "no evidence" conclusion, no LLM even attempted

        prompt = f"""..."""
        try:
            raw   = unwrap(client.chat_json("You are a research gap validator.", prompt, max_tokens=200))
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                result = json.loads(match.group())
                return result          # (e) GENUINE — cleanly-parsed LLM assessment
            # if match is None: falls through silently, NO exception raised -- (c)
        except Exception:
            pass                        # (b) LLMCallError or any other exception -- (d) json.loads raised inside the try, also lands here

        # Fallback heuristic -- reached by (b), (c), AND (d), which are indistinguishable from each other by return shape alone:
        recent = [p for p in found_papers if p.get("year") and p["year"] >= 2022]
        if len(recent) >= 2:
            return {"status": "partial", "reasoning": "Related recent work found but gap may still exist."}
        return {"status": "open", "reasoning": "No directly relevant recent papers found."}
    ```
    Paths (b) LLM call failed, (c) LLM responded but with no `{...}`-shaped content, and (d) LLM responded with content that looked like JSON but failed to parse, **all fall through to the same two heuristic return statements** — from the caller's point of view, `_assess_coverage` *never raises*, so there is no way to tell "genuine heuristic-shaped result" apart from "degraded fallback that happens to look the same" just by calling it and checking what comes back. Do **not** try to infer cacheability by pattern-matching the returned `reasoning` string or re-deriving it from `found_papers` — that's fragile and exactly the kind of trap this note exists to prevent.
  - [x] **Fix: change `_assess_coverage`'s return type to `tuple[dict, bool]`** — `(result, cacheable)`. Set `cacheable=True` only on paths (a) and (e) above (the two genuine outcomes); `cacheable=False` on both fallback return statements (reached by b/c/d). This is an unambiguous, structural fix — no heuristics, no string-sniffing.
  - [x] `_assess_coverage` is a private (`_`-prefixed), single-call-site function — confirmed via full-repo search, its only caller is `validate_gaps` in the same file. Changing its return type is safe and requires updating exactly one call site (Task 3).
- [x] Task 3: Wire caching into `validate_gaps` (`pipeline/academic_search.py`) (AC: #2, #3)
  - [x] Add module constant `GAP_VALIDATION_STAGE_VERSION = 1`
  - [x] **The cache gate must sit in `validate_gaps`'s per-gap loop, BEFORE `_search_semantic_scholar`/`_search_arxiv` are called — not just before `_assess_coverage`.** AD-2's binding list names only `academic_search._assess_coverage`, but `_assess_coverage` doesn't receive `domain_config` (needed for AD-3's `domain_hash`) and is called *after* the search API calls already ran — gating only `_assess_coverage` would leave AC #2's "no search calls are made" unsatisfied and would defeat the User Story's own stated goal of not re-spending the *search* calls either. `validate_gaps` is where `domain_config`, the gap, and the full per-gap sequence (search → assess) all meet, so that's where the check-before-call happens.
  - [x] Compute the cache key from **the gap's title+description** (AD-3's literal definition for this table — not `_build_search_query`'s output, which also mixes in `missing_connection` when present): `gap_content = f"{gap.get('title', '')}\n{gap.get('description', '')}"`. **Known, accepted limitation** (do not try to fix in this story): AD-3 explicitly scopes `gap_hash` to title+description only, so two gaps sharing identical title+description but a different `missing_connection` would share a cache entry even though their actual search query (and therefore found papers) could differ. This is a direct consequence of following the architecture spine's literal `content_hash` definition for this table, not an implementation shortcut — flag it if you notice it, don't silently "fix" it by hashing something AD-3 doesn't specify.
  - [x] Empty-content guard (mirrors Story 2.1/2.3's pattern): if `gap_content.strip()` is empty (a gap with no title and no description — should not happen in practice, but not provably impossible), skip the cache entirely for that gap — never read, never write.
  - [x] `cache_key, gap_hash, domain_hash = compute_cache_key(gap_content, domain_config, ["search_boost_terms"], GAP_VALIDATION_STAGE_VERSION)`. Check `get_cached_gap_validation(cache_key)` — on a hit, restore **all four** fields the cache-miss path would otherwise set on the gap (`validation_status`, `validation_reasoning`, `existing_papers`, `search_query_used` — see next bullet for why all four, not just the two AC #2 names parenthetically), append to `validated`, and `continue` to the next gap **without** calling `_build_search_query`, the boost-term logic, either search function, or `_assess_coverage`.
  - [x] **Cache the full effective per-gap output, not just `status`+`reasoning`.** AC #2 parenthetically says "(status + reasoning)" when describing what a cache hit restores, but a cache hit that skips the search calls entirely has no other way to populate `gap["existing_papers"]`/`gap["search_query_used"]` — those fields would otherwise be silently missing or stale on a cache hit. Store all four (`validation_status`, `validation_reasoning`, `existing_papers`, `search_query_used`) in `validation_json`, matching the precedent set by Story 2.1 (caching the full wiki dict, not a subset) and Story 2.2 (full params list). This is the story author's deliberate reading of the AC's intent, not a literal restatement — flagging it so it reads as a considered choice.
  - [x] On a cache miss, proceed exactly as today (`_build_search_query`, boost-term logic, both search calls, `time.sleep(0.5)` between them) through to `_assess_coverage`. **Update the call site**: `assessment, cacheable = _assess_coverage(gap, all_papers, client)` (was `assessment = _assess_coverage(...)`, per Task 2's signature change). Set `gap["validation_status"]`/`gap["validation_reasoning"]`/`gap["existing_papers"]`/`gap["search_query_used"]` exactly as today. **Only when `cacheable` is `True`** (and the empty-content guard didn't already skip caching for this gap), call `save_cached_gap_validation(cache_key, gap_hash, domain_hash, GAP_VALIDATION_STAGE_VERSION, {...the same four fields...})`.
  - [x] The existing `time.sleep(0.3)` at the end of each loop iteration and `time.sleep(0.5)` between the two search calls are both part of the "real work" path — a cache hit must skip **both** sleeps entirely, not just the API calls, since they exist to rate-limit real external requests that a cache hit doesn't make.
- [x] Task 4: Add targeted tests (AC: #1, #2, #3)
  - [x] New `tests/test_database_cache.py` class `GapValidationsCacheTests`, mirroring `ReferencesCacheTests`: cache miss returns `None`; save-then-get round-trips; `INSERT OR REPLACE` overwrites; a corrupted row is a miss; a `NULL` row is a miss; a row whose JSON parses to something other than a `dict` is a miss.
  - [x] New `tests/test_academic_search_cache.py`: `_assess_coverage` returns `(result, True)` when `found_papers` is empty, and `(result, True)` when the LLM call succeeds and returns cleanly-parsed JSON. Returns `(result, False)` when the mocked `client.chat_json` returns a `Failure` (LLMCallError path), when it returns a `Success` with no `{...}`-shaped content, and when it returns a `Success` with malformed JSON inside `{...}` — three separate tests, since these are three genuinely different code paths that happen to produce the same *shape* of degraded output.
  - [x] `validate_gaps` cache miss then hit for a single gap: mock `_search_semantic_scholar`/`_search_arxiv` (patch `pipeline.academic_search._search_semantic_scholar`/`_search_arxiv`) to return papers once and a mocked `client.chat_json` returning a clean `Success`; first call invokes both search functions and the LLM once each; second call with an identical gap (same title/description, same `domain_config`) invokes **neither** search function nor the LLM, and the gap's `validation_status`/`validation_reasoning`/`existing_papers`/`search_query_used` all match the first call's values.
  - [x] A cache-miss result where `_assess_coverage` falls back (mocked LLM failure) is never cached: a first call attempts the real search+LLM sequence and returns the heuristic result; a second call with the identical gap attempts the real sequence again (search functions and LLM called again, not skipped).
  - [x] A different `domain_config` (different `search_boost_terms`) for the same gap is a cache miss, proving the `domain_hash` actually participates in the key (this table is domain-conditioned, unlike `parameters`/`references`) — mirrors Story 2.1's `test_different_domain_config_is_a_cache_miss`.
  - [x] An unrelated `domain_config` key changing (e.g. a hypothetical `wiki_focus`-only change, `search_boost_terms` unchanged) does **not** cause a cache miss — mirrors Story 2.1's `test_unrelated_domain_keys_do_not_affect_key`, proving `relevant_domain_keys=["search_boost_terms"]` is actually scoping the hash correctly.
  - [x] `GAP_VALIDATION_STAGE_VERSION` bump bypasses a previously-cached entry, **and** the bumped-version entry itself becomes a hit on a third call (apply Story 2.3's review-learned lesson: test full repopulation, not just the miss, from the start).
  - [x] Empty-content gap (no title, no description) is never cached and never crashes — two calls with such a gap both attempt the real search+assess sequence.
  - [x] A gap where both search functions return zero papers is cached (path (a)'s confident "open, no evidence" verdict is `cacheable=True`) — a first `validate_gaps` call with mocked-empty search results writes a cache entry; a second call with the identical gap is a hit (neither search function nor the LLM called). This exercises the miss→hit path when *no* papers are found, complementing the existing found-papers test.
  - [x] Use the same real-SQLite-via-monkeypatched-`DB_PATH` test pattern established in `tests/test_database_cache.py`.

### Review Findings

All three layers independently converged on the cache-hit restore's `KeyError` risk (Acceptance Auditor flagged it as a minor observation; Blind Hunter and Edge Case Hunter both raised it as an actionable bug) — treated as the headline finding alongside a second, related convergent finding (Blind Hunter + Edge Case Hunter) on malformed-but-parseable LLM JSON.

- [x] [Review][Patch] **Cache-hit restore uses direct dict indexing (`cached["validation_status"]` etc.), not `.get()` with defaults.** A cached row missing any of the four expected keys (partially-written row, future schema drift, hand-edited DB) raises `KeyError` and crashes the entire `validate_gaps` run — a harder failure than no cache at all, and inconsistent with the defensive `.get(..., default)` style already used on the fresh-compute path a few lines below. Independently flagged by all three review layers. [pipeline/academic_search.py:167-170]
- [x] [Review][Patch] **`_assess_coverage`'s `cacheable=True` signal only checks that the LLM's response parsed as *some* JSON object, not that it has the expected shape.** A syntactically valid but off-schema response (e.g. `{"foo": "bar"}`, no `status`/`reasoning` keys) parses cleanly, returns `(result, True)`, and the caller's `assessment.get("status", "open")` silently substitutes a default that then gets written to the cache as if it were a genuine, confident assessment — indistinguishable from a real success. [pipeline/academic_search.py:128-130]
- [x] [Review][Patch] **`get_cached_gap_validation` validates only `isinstance(parsed, dict)`, not that the four expected keys are present.** Closes the same class of bug at the cache-read boundary too (defense-in-depth alongside the `.get()`-default fix above) — a structurally-corrupt-but-still-a-dict row should degrade to a miss, not be accepted as a hit and crash downstream.
- [x] [Review][Patch] **`compute_cache_key`'s `domain_hash` computation (`utils/database.py`, shared helper from Story 2.1) sorts dict keys via `sort_keys=True` but not list *values*.** `search_boost_terms` is a list; two domain configs carrying the identical set of boost terms in a different order hash to different `domain_hash` values, causing a spurious cache miss. This story is the first caller to pass a list-valued key through `relevant_domain_keys` — Stories 2.1-2.3 never triggered this latent gap in the shared helper.
- [x] [Review][Patch] **`gap.get('title', '')`/`gap.get('description', '')` don't handle an explicit `None` value**, only a missing key — `gap.get('title', '')` returns `None`, not `''`, when `gap['title'] is None`. The literal string `"None"` then enters the cache-key hash, and the empty-content guard (`gap_content.strip()`) fails to catch it since `f"{None}"` is non-empty. [pipeline/academic_search.py:159-160]
- [x] [Review][Patch] **No test asserts `time.sleep` is *not* called on the cache-hit path.** Every cache-hit test patches `pipeline.academic_search.time.sleep` and never inspects its call count, so a regression reintroducing sleeps on a cache hit would go undetected despite Dev Notes explicitly calling this out as a requirement.
- [x] [Review][Defer] The search functions' failure-swallowing (`except Exception: pass; return []`, no distinction from a genuine zero-results search) means a transient rate-limit/outage on both searches during one gap's evaluation gets cached as a confident `cacheable=True` "open, no evidence" verdict — permanently, until `GAP_VALIDATION_STAGE_VERSION` is bumped. Already identified and documented as an accepted, known limitation in this story's own Dev Notes before implementation began (Story 2.5's resilience fix is the actual remedy); re-affirmed here as a named risk for Story 2.5 to consider bumping the cache version when it ships. Not a new finding.
- [x] [Review][Defer] No TTL or per-entry invalidation for `gap_validations` — the only recovery from one bad cached entry is a full `GAP_VALIDATION_STAGE_VERSION` bump invalidating every gap, not just the affected one. Deferred — matches Story 2.1's already-deferred "cache growth/retention policy" item (`ARCHITECTURE-SPINE.md` Deferred section); not specific to this story.
- [x] [Review][Defer] `gap_validations` has no `run_id`/project-scoping column — two unrelated projects whose gaps happen to produce byte-identical title+description and identical `search_boost_terms` would silently share a cache entry. Deferred — matches Story 2.2/2.3's identically-deferred "global unscoped cache shared across all users/runs" finding, an architecture-level (AD-3) decision inherited from Story 2.1's precedent, not reconsidered by this story.
- [x] [Review][Defer] `get_cached_gap_validation`/`save_cached_gap_validation` have no `try/finally` around their SQLite calls. Deferred — identical to Story 2.1/2.2/2.3's identically-deferred finding for the equivalent functions; existing file-wide convention, not introduced by this story.
- [x] [Review][Defer] `gap_hash`/`domain_hash` columns are persisted but write-only — no way to bulk-invalidate "every cached validation for one domain" without recomputing exact hashes. Deferred — mirrors Story 2.2/2.3's identically-deferred write-only-hash-column finding.
- [x] [Review][Dismiss] "A blank-title/blank-description gap is never cached and re-runs the full pipeline every time, receiving zero caching benefit." This is the deliberate, precedent-matching trade-off of the empty-content guard (identical to Story 2.1's empty-`full_text` guard) — the alternative (caching blank gaps) reintroduces exactly the collision risk the guard exists to prevent. Not a new issue; a considered design choice, not a bug.
- [x] [Review][Dismiss] "No regression tripwire test confirms today's accepted empty-`found_papers`-caching behavior." Already covered: `test_no_papers_found_is_cacheable` (`test_academic_search_cache.py`) and `test_no_papers_found_is_cached` (`ValidateGapsCacheTests`) both directly encode and would break on any change to this exact behavior — the tripwire already exists, just not framed as one.
- [x] [Review][Dismiss] "Two concurrent `validate_gaps` calls racing on the same not-yet-cached gap would both redo search+LLM work (TOCTOU on check-then-save)." Already explicitly out of scope per `ARCHITECTURE-SPINE.md`'s own Deferred section: "Concurrent/multi-user access to the SQLite cache — out of scope; ResGap is a single-user Streamlit session today." Not a new finding, matches Story 2.3's identical dismiss for thread-safety.

**Post-review suite:** 94/94 tests passing (was 91; +3 new: cache-hit skips both sleeps, off-schema LLM JSON is not cacheable, a cached row missing a required key is a miss not a crash; existing production code hardened against KeyError, off-schema LLM JSON, list-ordering hash instability, and None-vs-missing gap fields).

## Dev Notes

- **This is the fourth and final cache-table story in Epic 2** (2.1 wiki pages — done, 2.2 parameters — done, 2.3 references — done, 2.4 gap validations — this story). `compute_cache_key()` (Story 2.1) is reused unmodified for the fourth time.
- **This story's design has two hard parts, and they're different in kind:** (1) `_assess_coverage`'s success/fallback ambiguity (Task 2) is a *code-correctness* problem — the function's current return contract makes it structurally impossible for a caller to know whether a result is genuine or degraded, so the fix changes its signature. (2) The cache gate's placement in `validate_gaps` rather than `_assess_coverage` (Task 3) is a *scope-interpretation* problem — AD-2 names `_assess_coverage` as the bound filter, but satisfying AC #2's "no search calls are made" requires gating earlier in the call chain. Both are explained in full above; read them before writing code, not after something breaks.
- **Not in scope:** `_search_semantic_scholar` and `_search_arxiv`'s own resilience (raising on non-2xx, `tenacity` retry, Semantic Scholar API key) is Story 2.5. `_search_arxiv`'s query-construction bug (unquoted multi-word `all:` query) is Story 2.6. This story only adds the cache-aside wrapper around the existing search+assess sequence — do not fix either of those in this story, even though you'll be reading both functions closely enough to notice them.
- **Known, accepted limitation this story introduces (do not try to fix here):** `_search_semantic_scholar`/`_search_arxiv` currently swallow every failure into `except Exception: pass; return []` with no `raise_for_status()` (that's Story 2.5). A transient 429/timeout on **both** search calls today produces `found_papers == []`, which `_assess_coverage` path (a) treats as a confident, `cacheable=True` "open, no evidence found" verdict — this story will cache that false negative. `GAP_VALIDATION_STAGE_VERSION` only covers prompt/query-construction changes per AD-3, so Story 2.5's resilience fix won't automatically invalidate these entries when it lands. This is a real, pre-existing interaction between AD-2 (this story) and AD-5 (Story 2.5), not a defect introduced by this story's design — flag it in this story's Change Log / deferred-work.md rather than silently absorbing extra scope; Story 2.5 should consider bumping `GAP_VALIDATION_STAGE_VERSION` when it ships to invalidate any bad "open" entries cached before search resilience existed.
- **Why `domain_hash` is real here (unlike Stories 2.2/2.3):** wiki compilation (2.1) and gap validation (2.4) are the two domain-conditioned stages per AD-3; parameter extraction (2.2) and reference enrichment (2.3) are domain-invariant. Passing `relevant_domain_keys=["search_boost_terms"]` (confirmed the only domain_config key `validate_gaps`/`get_search_boost_terms` reads) means an unrelated domain_config field changing does not cause a spurious cache miss, exactly like Story 2.1's `["wiki_focus", "wiki_entity_examples"]` scoping.
- **The `gap_hash` content is title+description only, per AD-3's literal wording** — not `_build_search_query`'s full query string (which also folds in `missing_connection`). This is a deliberate, spine-literal choice with a documented, accepted edge case (see Task 3) — do not "fix" it by hashing something AD-3 doesn't specify without a spine update.

### Current State of `academic_search.py` (file being modified — read in full)

```python
def _assess_coverage(gap: dict, found_papers: list, client) -> dict:
    if not found_papers:
        return {"status": "open", "reasoning": "No relevant papers found in academic search."}
    prompt = f"""..."""
    try:
        raw   = unwrap(client.chat_json("You are a research gap validator.", prompt, max_tokens=200))
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
            return result
    except Exception:
        pass
    recent = [p for p in found_papers if p.get("year") and p["year"] >= 2022]
    if len(recent) >= 2:
        return {"status": "partial", "reasoning": "Related recent work found but gap may still exist."}
    return {"status": "open", "reasoning": "No directly relevant recent papers found."}


def validate_gaps(gaps: list, client, domain_config: dict = None) -> list:
    boost_terms = []
    if domain_config:
        from domain_config import get_search_boost_terms
        boost_terms = get_search_boost_terms(domain_config)      # ← Task 3: only domain_config key read

    validated = []
    for gap in gaps:                                              # ← Task 3: cache check goes HERE,
        query = _build_search_query(gap)                          #   before query/boost/search/assess

        if boost_terms:
            gap_lower = gap.get("title", "").lower()
            relevant_boosts = [t for t in boost_terms if any(w in gap_lower for w in t.split())]
            boost = relevant_boosts[0] if relevant_boosts else boost_terms[0]
            query = f"{query} {boost}"
            query = query[:150]

        ss_papers = _search_semantic_scholar(query, limit=5)       # ← Task 3: must be skipped on a cache hit
        time.sleep(0.5)
        arxiv_papers = _search_arxiv(query, limit=3)

        all_papers = ss_papers + arxiv_papers

        assessment = _assess_coverage(gap, all_papers, client)     # ← Task 2: becomes (assessment, cacheable)

        gap["validation_status"] = assessment.get("status", "open")
        gap["validation_reasoning"] = assessment.get("reasoning", "")
        gap["existing_papers"] = all_papers[:5]
        gap["search_query_used"] = query

        validated.append(gap)                                      # ← Task 3: cache write goes HERE,
        time.sleep(0.3)                                             #   gated on `cacheable`

    return validated
```

### Project Structure Notes

- One file touched for logic (`pipeline/academic_search.py`, both `_assess_coverage`'s signature and `validate_gaps`'s loop), plus `utils/database.py` (new table + 2 new functions).
- Aligns with AD-1 — `pipeline/academic_search.py` already imports from `utils/*` (`from utils.azure_client import unwrap`); adding `compute_cache_key`/`get_cached_gap_validation`/`save_cached_gap_validation` from `utils.database` doesn't change the dependency direction.
- `validate_gaps`'s public signature (`validate_gaps(gaps: list, client, domain_config: dict = None) -> list`) is unchanged. `_assess_coverage`'s signature changes (`-> dict` becomes `-> tuple[dict, bool]`), but it is private and has exactly one caller in the same file, updated in the same task.

### Testing Standards

- Continues the established convention: stdlib `unittest`, `tests/` directory, real-SQLite-via-monkeypatched-`DB_PATH` pattern.
- No test file exists yet for `pipeline/academic_search.py` — this story creates the first one (`tests/test_academic_search_cache.py`), scoped to the caching/signature behavior added here, not a general-purpose test suite for query-building or the raw HTTP search functions (those are Story 2.5/2.6 territory).
- Mock `_search_semantic_scholar`/`_search_arxiv` directly (patch `pipeline.academic_search._search_semantic_scholar`/`pipeline.academic_search._search_arxiv`) rather than mocking `requests.get` — simpler given these two functions' return shape is well-defined and their own HTTP internals aren't this story's concern.

### References

- [Source: `_bmad-output/planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md#AD-2`, `#AD-3` — including the ER diagram's `GAP_VALIDATIONS` table shape (the only Epic 2 cache table with both `gap_hash` AND `domain_hash`) and the explicit "gap title+description" content_hash definition]
- [Source: `_bmad-output/planning-artifacts/epics.md#Epic-2-Story-2.4`]
- [Source: `_bmad-output/implementation-artifacts/2-3-cache-enriched-reference-metadata.md` — established the `"references"`-quoting lesson (not applicable here, but the hardened `get_cached_*` pattern is reused), and its own review's "verify repopulation, not just the miss" test lesson, applied here from the start]
- [Source: `_bmad-output/implementation-artifacts/1-2-callers-raise-a-distinct-exception-on-llm-failure.md` Task 3 — confirms `_assess_coverage` already uses `unwrap()` inside its existing `except Exception: pass` block, by deliberate Story 1.2 design ("safe drop-in... no other change needed") — this story does not revisit that decision, only adds the `cacheable` signal alongside it]
- [Source: `pipeline/academic_search.py` — full file read, current `_assess_coverage`/`validate_gaps` implementation]
- [Source: `domain_config.py` line 428-430 (`get_search_boost_terms`) — confirms only `search_boost_terms` is read from `domain_config` by this stage]
- [Source: `utils/database.py` — full file read, current schema/conventions post-Story-2.3]

## Change Log

- 2026-08-05: `utils/database.py` — added the `gap_validations` table (with a real `domain_hash` column, since gap validation is domain-conditioned per AD-3 — the first Epic 2 table since `wiki_pages` to have one) and `get_cached_gap_validation()`/`save_cached_gap_validation()`, hardened from day one (type check + `TypeError` catch, per Story 2.3's lesson). `pipeline/academic_search.py` — `_assess_coverage`'s return type changed from `dict` to `tuple[dict, bool]` (`# B18 fix`) so callers can distinguish a genuine, confident result (no papers found, or a cleanly-parsed LLM response) from a degraded heuristic fallback (LLM call failed, or succeeded with no parseable JSON) — previously indistinguishable by return shape alone. `validate_gaps` now checks the cache (keyed on gap title+description, domain-scoped to `search_boost_terms`) before either the academic-search calls or the LLM assessment, restoring all four effective output fields on a hit and writing back only on a genuine, cacheable result. Added `tests/test_academic_search_cache.py` (12 tests) and extended `tests/test_database_cache.py` with `GapValidationsCacheTests` (6 tests).

- 2026-08-05 (code review pass): fixed a `KeyError` risk on the cache-hit restore path (now `.get()` with defaults, not direct indexing) — independently flagged by all three review layers. Fixed `_assess_coverage` treating a syntactically valid but off-schema LLM response as a genuine cacheable result — now requires a recognized `status` value. Hardened `get_cached_gap_validation` to require all four expected keys, not just `isinstance(dict)`. Fixed `compute_cache_key`'s `domain_hash` computation to sort list-valued domain_config fields before hashing (this story was the first caller to pass a list-valued key). Fixed `gap.get('title', '')` not handling an explicit `None` value. Added 3 more tests. Final: 94/94 passing.

## Dev Agent Record

### Agent Model Used

Claude (BMAD dev-story workflow)

### Debug Log References

- RED confirmed per task group: `tests/test_database_cache.py`'s `GapValidationsCacheTests` failed with `sqlite3.OperationalError: no such table: gap_validations` / `AttributeError: module 'utils.database' has no attribute 'save_cached_gap_validation'` before Task 1; `tests/test_academic_search_cache.py`'s `AssessCoverageCacheableSignalTests` failed with `TypeError: string indices must be integers` (old code still returned a bare dict) before Task 2; `ValidateGapsCacheTests` failed with `AttributeError: ... 'GAP_VALIDATION_STAGE_VERSION'` plus call-count mismatches before Task 3.
- The story's own fresh-context creation review caught a real cross-story interaction before any code was written: `_search_semantic_scholar`/`_search_arxiv` still silently swallow failures into `[]` (Story 2.5's job to fix), so a transient outage on both search calls today gets cached as a confident "open, no evidence" verdict via `_assess_coverage`'s empty-`found_papers` path. Documented in Dev Notes as a known, accepted limitation rather than fixed here — fixing it would mean pulling Story 2.5's scope into this story.
- Full suite: `uv run --python 3.11 --with openai --with pdfplumber --with PyMuPDF --with numpy --with scipy --with reportlab --with requests python -m unittest discover -s tests -v` → 91/91 pass (was 73 before this story).
- `py_compile` clean on both modified files; `import pipeline; import utils.database` smoke test clean.
- Code review (3-layer, all completed): all three layers independently converged on the cache-hit `KeyError` risk (Acceptance Auditor as a minor observation, Blind Hunter and Edge Case Hunter as an actionable bug) — the strongest cross-layer convergence signal of any story so far in this epic. 6 patches applied, 5 items deferred (all matching prior-story precedent or already documented in this story's own Dev Notes), 3 dismissed (2 as deliberate precedent-matching design choices, 1 as already covered by the architecture spine's explicit single-user-session scope).
- Post-review full suite: 94/94 pass (was 91). `py_compile` and import smoke test re-confirmed clean after patches.

### Completion Notes List

- All 4 tasks complete; 18 new tests total (6 `GapValidationsCacheTests` in `test_database_cache.py`, 12 in the new `test_academic_search_cache.py`); 91/91 suite passing.
- `compute_cache_key()` reused unmodified from Story 2.1 for the fourth time, this time with a non-empty `relevant_domain_keys=["search_boost_terms"]` — the first domain-conditioned reuse since Story 2.1 itself introduced the helper.
- This story's two hardest design points — `_assess_coverage`'s four-path success/fallback ambiguity (fixed via a `tuple[dict, bool]` return-type change) and the cache gate's placement in `validate_gaps` rather than literally inside `_assess_coverage` (required to satisfy "no search calls made") — were both identified and fully specified during story creation, verified independently by a fresh-context reviewer against the actual code, and implemented exactly as planned with no mid-implementation surprises.
- `validate_gaps`'s public signature is unchanged; `_assess_coverage`'s return type changed, but as a private, single-call-site function (confirmed via full-repo grep both at story-creation time and again during implementation) this required updating exactly one call site.
- Code review found one bug in the shared `compute_cache_key()` helper itself (list-value ordering not accounted for in the domain_hash computation) — latent since Story 2.1 introduced the helper, only surfaced now because this is the first story to pass a list-valued `domain_config` field through `relevant_domain_keys`. Fixed at the shared-helper level, benefiting all four Epic 2 cache tables going forward.

### File List

- Modified: `utils/database.py`
- Modified: `pipeline/academic_search.py`
- Modified: `tests/test_database_cache.py`
- Added: `tests/test_academic_search_cache.py`
