---
baseline_commit: 53e5b93e269ce562c0e7f2b81b90309b201dd24c
---

# Story 2.3: Cache enriched reference metadata

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a ResGap user,
I want enriched reference metadata (from Semantic Scholar/CrossRef/etc.) to be cached,
so that a reference cited across multiple uploaded corpora isn't re-fetched from external APIs every run.

## Acceptance Criteria

1. **Given** `utils/database.py`, **When** this story ships, **Then** a new `references` table exists with columns `cache_key` (PK), `doi_or_title_hash`, `stage_logic_version`, `enriched_json` — no `domain_hash` column, since reference enrichment is domain-invariant per AD-3 (`enrich_reference` and every helper it calls never touch `domain_config` — confirmed by reading `pipeline/reference_extractor.py` in full; matches the architecture spine's own ER diagram, which shows `REFERENCES.cache_key PK "doi_or_title_hash:none:version"`).
2. **Given** `enrich_reference` is called for a reference whose input `ref` dict carries a resolvable identity (DOI, else arXiv ID, else title), **When** a matching `cache_key` already has a row, **Then** the cached enriched dict is returned and **no external API call is made at all** (not even the first lookup attempt).
3. **Given** no matching `cache_key` exists, **When** enrichment finds real metadata from any API (`meta` is truthy — a genuine "Tier 2" result), **Then** the result is cached keyed by the input `ref`'s DOI (if present), else its arXiv ID (if present), else its normalized title. **When** every API lookup is exhausted and no metadata is found (the existing "Tier 3 / `parsed_only`" fallback), **Then** that fallback is never cached — per AD-2, a filter that falls back to a degraded result on failure must never cache that fallback (a transient network/API issue must not get permanently frozen as "this reference has no metadata").

## Tasks / Subtasks

- [x] Task 1: Add the `references` table and cache read/write functions to `utils/database.py` (AC: #1, #2, #3)
  - [x] Add `CREATE TABLE IF NOT EXISTS "references" (cache_key TEXT PRIMARY KEY, doi_or_title_hash TEXT, stage_logic_version INTEGER, enriched_json TEXT)` to `init_db()`'s executescript, alongside `parameters`. **`references` is a genuine SQL reserved word — verified empirically that SQLite rejects it unquoted (`CREATE TABLE references (...)`, `INSERT INTO references`, and `SELECT ... FROM references` all fail with a syntax error). Always double-quote it as `"references"` in every SQL statement that touches this table** (`CREATE TABLE`, the `SELECT` in `get_cached_reference`, the `INSERT OR REPLACE` in `save_cached_reference`) — there is no unquoted fallback path, don't waste a debug cycle testing one. The Python-side identifiers (table name in comments, function names, dict keys) are unaffected — only the SQL text itself needs the quotes.
  - [x] Add `def get_cached_reference(cache_key: str) -> dict | None:` — call `init_db()` first, `SELECT enriched_json FROM "references" WHERE cache_key = ?`; return `None` on a miss, on a corrupted/unparseable row, on a `NULL` row, **and** on a row whose JSON parses to something other than a `dict` (apply Story 2.2's review-hardened pattern from day one — its code review found `get_cached_parameters` needed `except (json.JSONDecodeError, TypeError): return None` plus an `isinstance(parsed, list)` check; here the equivalent is `isinstance(parsed, dict)`, since `enriched_json` stores a single reference dict, not a list. Don't repeat the two-pass bug Story 2.2 needed a review cycle to catch — bake the full hardened version in immediately.)
  - [x] Add `def save_cached_reference(cache_key: str, doi_or_title_hash: str, stage_logic_version: int, enriched_json: dict) -> None:` — call `init_db()` first, `INSERT OR REPLACE INTO "references" (...) VALUES (...)`, `json.dumps(enriched_json, default=str)`
  - [x] Reuse `compute_cache_key()` from Story 2.1 unmodified — call it with `relevant_domain_keys=[]` (domain-invariant, same as Story 2.2's `parameters` table), which correctly produces `domain_hash == "none"`; the `content_hash` it returns **is** the `doi_or_title_hash` value for this table — pass it straight into `save_cached_reference`'s `doi_or_title_hash` parameter, no separate computation needed
- [x] Task 2: Wire caching into `enrich_reference` (`pipeline/reference_extractor.py`) (AC: #2, #3)
  - [x] Add module constant `REFERENCE_STAGE_VERSION = 1`
  - [x] **Critical design point — read before implementing:** compute a single `identity` string **once, at the top of `enrich_reference`, from the input `ref` dict only** — never from anything an API call later resolves. Priority order (matches AD-3's own definition: "DOI/arXiv-id/normalized-title"): `identity = doi or arxiv_id.lower() or title.lower()`, reusing the `doi`/`arxiv_id`/`title` local variables `enrich_reference` already computes at its top (`doi` is already `.strip().lower()`'d; `arxiv_id` and `title` are only `.strip()`'d today — lowercase them for the identity computation without changing the variables used elsewhere in the function for API calls, which expect their original casing/form). This is the **read key** for the pre-call cache check.
  - [x] **This story deliberately does NOT use a "resolved" post-enrichment identity for the cache write** (e.g. a DOI discovered via `resolved_doi = doi or (meta.get("externalIds") or {}).get("DOI", "") or meta.get("doi", "")`, which already exists in the current code for the *returned dict's* `doi` field, unrelated to caching). The write uses the **same `identity`/`cache_key` computed at the top**, not `resolved_doi`. **Why:** using a resolved identity for the write while the read only ever checks the input-known identity would let the read/write keys silently diverge — a title-only lookup that later resolves a DOI would write under the DOI key, then a second call with the same title-only `ref` would miss again forever (write key ≠ read key). Keeping read and write keys identical avoids that class of bug entirely, at the accepted cost that this story does **not** achieve cross-corpus dedup between "paper A cites this work with a DOI in the raw text" and "paper B cites the same work by title only" — those enrich independently and cache under separate keys. This is a real, accepted scope limitation (analogous to Story 2.2's own accepted `context`-collision-risk reasoning) — do not build resolved-identity dual-write caching to "fix" this without a corresponding AC update; it is out of scope for this story.
  - [x] **Empty-identity guard (mirrors Story 2.1's empty-`full_text` fix):** if `identity` is the empty string (a `ref` with no `doi`, no `arxiv_id`, and no/empty `title` — should be rare given upstream filtering in `extract_and_enrich_references`, but not provably impossible), **skip the cache entirely** — never read, never write — exactly like Story 2.1 skips caching for empty `full_text`, to avoid two genuinely-unrelated blank references silently sharing a cache entry.
  - [x] Check the cache first (when `identity` is non-empty): `cache_key, content_hash, _ = compute_cache_key(identity, None, [], REFERENCE_STAGE_VERSION); cached = get_cached_reference(cache_key); if cached is not None: return cached` — **before any of the existing `if doi: meta = _ss_by_doi(doi); time.sleep(delay)` lookup chain runs.** A cache hit must skip every API call and every `time.sleep`, not just some of them.
  - [x] On a cache miss, proceed exactly as today through the full lookup chain and the `if meta:` success branch. **Only inside the `if meta:` branch** (never in the Tier-3 fallback branch below it), after building the `result` dict that branch already returns, call `save_cached_reference(cache_key, content_hash, REFERENCE_STAGE_VERSION, result)` before returning it (only when `identity` was non-empty, per the guard above).
  - [x] **The Tier-3 `parsed_only` fallback (the function's final `return {...}` when `meta` stayed `None` after every lookup) must never be cached — no `save_cached_reference` call anywhere near it.** This is this story's AD-2 "never cache a fallback" case: `meta is None` here isn't an `LLMCallError` (this function has no LLM calls at all, only HTTP lookups each already wrapped in their own `try/except Exception: pass`), but it is structurally the same thing — a degraded, un-enriched result produced because every real lookup failed or found nothing, exactly the shape AD-2 says must never be frozen into the cache.
- [x] Task 3: Add targeted tests (AC: #1, #2, #3)
  - [x] New `tests/test_database_cache.py` class `ReferencesCacheTests`, mirroring `ParametersCacheTests` exactly (same `setUp`/`tearDown` real-SQLite-via-monkeypatched-`DB_PATH` pattern): cache miss returns `None`; save-then-get round-trips; `INSERT OR REPLACE` overwrites; a corrupted row is a miss; **plus two Story-2.2-review-derived cases this table should get right from the start:** a `NULL` `enriched_json` column is a miss (not a crash), and a row whose JSON parses to something other than a `dict` (e.g. a list or int) is a miss (not a crash-inducing type mismatch downstream).
  - [x] New `tests/test_reference_extractor_cache.py`: `enrich_reference` cache miss then hit for a DOI-bearing `ref` — mock `requests.get` (patch `pipeline.reference_extractor.requests.get`) to return a fake 200 response once; first call makes the real lookup chain and caches; second call with the identical `ref` makes **zero** `requests.get` calls and returns the same enriched dict.
  - [x] A title-only `ref` (no `doi`, no `arxiv_id`) that resolves to a real metadata hit is cached under its title identity — a second call with the identical title-only `ref` is a cache hit (zero `requests.get` calls); a *different* title is a cache miss (proves the identity, not some incidental accident, drives the key).
  - [x] The Tier-3 fallback (mock every `requests.get` call to return a non-200 status, or patch each `_ss_*`/`_crossref_*`/etc. lookup to return `None`) is never cached: a first call attempts real lookups and returns the `parsed_only` stub; a second call with the identical `ref` attempts real lookups again (non-zero `requests.get` call count on the second call too) — proves the fallback wasn't frozen into the cache.
  - [x] DOI takes priority over title when both are present on the same `ref`: cache a result under a `ref` with both `doi` and `title` set, then call again with the **same `doi`** but a **different `title`** — still a cache hit (identity is DOI-driven, title changing doesn't matter once DOI is present). Add the equivalent check for the arXiv-ID tier: a `ref` with `arxiv_id` set (no `doi`) caches under the arxiv identity, and changing `title` alone (arxiv_id unchanged, still no `doi`) is still a cache hit — proves the full three-tier priority chain (`doi or arxiv_id.lower() or title.lower()`), not just the DOI-vs-title ends of it.
  - [x] Empty-identity `ref` (no `doi`, no `arxiv_id`, and no/empty `title`): none of `enrich_reference`'s existing lookup branches (`if doi:`, `if arxiv_id:`, `if title and len(title) > 10:`) fire for such a `ref` regardless of caching, so assert **zero** `requests.get` calls on *each* of two calls with this `ref` (not "attempts real lookups") and confirm no row exists in the `references` table afterward — proving the skip-cache guard runs cleanly without needing an API response to exercise.
  - [x] `PARAM_STAGE_VERSION`-bump-style regression check: bump `REFERENCE_STAGE_VERSION` between two calls for the same cached `ref` — the second call is a real cache miss (mirrors Story 2.1/2.2's `test_stage_version_bump_bypasses_a_previously_cached_entry`, don't let this table be the one that skips it and needs a review cycle to add it back, as happened in Story 2.2).

### Review Findings

Edge Case Hunter and Blind Hunter independently converged on the same headline finding (no type-tag on the identity string before hashing); Acceptance Auditor found zero spec violations.

- [x] [Review][Patch] **No type-prefix on the cache identity before hashing.** `identity = doi or arxiv_id.lower() or title.lower()` mixes three different kinds of strings into one hash space with no tag distinguishing which kind it is — a pathological title that happens to exactly match another reference's DOI or arXiv-ID string would collide on the same `cache_key` and silently return the wrong cached metadata. [pipeline/reference_extractor.py:435]
- [x] [Review][Patch] **A cache read/write failure inside `enrich_reference` can discard an already-successful, expensive multi-API enrichment, or abort a lookup before it starts.** Neither the cache check nor the cache write is guarded — `extract_and_enrich_references`'s outer `try/except` wraps the *entire* `enrich_reference()` call, so an exception from `save_cached_reference` (locked DB, disk full) *after* real metadata was already fetched converts a genuine Tier-2 result into a fabricated `"enrichment_failed"` Tier-3 stub, throwing away real work; symmetrically, a failing cache *read* would abort the lookup before any API call is even attempted. This directly contradicts the file's own established resilience philosophy (the `# B6 FIX`/`# B12 fix` comments: never let one failure abort processing that could otherwise succeed).
- [x] [Review][Patch] **`test_stage_version_bump_bypasses_a_previously_cached_entry` only proves the miss, not the repopulation** — it never makes a third call under the bumped version to confirm the new entry was actually written and is now itself a hit.
- [x] [Review][Patch] **`test_title_only_ref_is_cached_under_title_identity`'s `different_ref` branch is only checked for triggering a real miss, never for its own caching** — "the first title caches" is well tested; "the second, distinct title also caches" is not.
- [x] [Review][Defer] **Title-only cache identity risks silent cross-reference collisions** — two genuinely different papers sharing an exact title (surveys, common chapter titles, reprints) collide on the same `cache_key`; whichever is enriched first silently and permanently donates its DOI/abstract/authors to every other reference with that title. Deferred — fixing this would mean adding author/year disambiguation to the identity, which is a real design change beyond AC3's literal "DOI hash, else normalized-title hash" scope; needs a corresponding AC update, not a same-story patch.
- [x] [Review][Defer] Ref-derived fallback fields (`year`, `authors` via `ref.get(...)`, and `arxiv_id`) get frozen into the cached entry at first-write time and replayed verbatim for every later reference sharing the same identity, even if a later citation's local data differs. Deferred — inherent to identity-keyed caching (the whole point is that the first successful resolution becomes canonical for that identity); narrow, low-severity, and not fixable without abandoning simple identity-keyed caching.
- [x] [Review][Defer] Time-varying fields (`citations`/`citationCount`, `open_access_url`) are baked into the same permanent cache entry with no TTL or per-field refresh — the only invalidation path is a full `REFERENCE_STAGE_VERSION` bump that wipes the entire table. Deferred — matches Story 2.1's already-deferred "cache growth/retention policy" item (`ARCHITECTURE-SPINE.md` Deferred section) and AD-3's own version-bump-only invalidation design; not specific to this story.
- [x] [Review][Defer] `get_cached_reference`/`save_cached_reference` call a full `init_db()` executescript on every invocation, with no connection reuse across the per-reference loop. Deferred — identical to Story 2.2's deferred finding for `get_cached_parameters`/`save_cached_parameters`; same architecture Story 2.1 introduced, broader performance change out of scope for a single story.
- [x] [Review][Defer] `get_cached_reference`/`save_cached_reference` have no `try/finally` around their SQLite calls (distinct from the enrich_reference-level guard above, which is being patched) — an exception mid-call skips `conn.close()`. Deferred — identical to Story 2.1/2.2's deferred finding for the equivalent wiki_pages/parameters functions; existing file-wide convention, not introduced by this story.
- [x] [Review][Defer] `doi_or_title_hash` column is populated but never read back or verified by any test. Deferred — mirrors Story 2.2's identically-deferred `content_hash`-write-only finding for the `parameters` table; same broader dead-data-column issue, not new here.
- [x] [Review][Defer] A reference that will never resolve (deleted preprint, unfixable title typo) pays the full 4-8-call API waterfall on every single future run, forever, since Tier-3 is never cached (by design, per AD-2) — and nothing measures or surfaces this recurring cost. Deferred — matches Story 2.1's already-deferred "no cache hit/miss observability" finding (no logging convention exists yet); the never-cache-fallback behavior itself is correct per AD-2, only the lack of cost visibility is new territory, and it's the same gap as the existing deferred item.
- [x] [Review][Defer] `extract_and_enrich_references`'s in-run duplicate-skip normalization (`_norm`: lowercase + strip + truncate to 60 chars) and the new cross-run cache identity normalization (`title.lower()` only, untruncated) are two different, unshared implementations of "same title." Deferred — a code-quality/consistency observation (risk of future drift if one is changed without the other), not a bug; no AC requires unifying them, and the in-run dedup logic is out of this story's stated scope.
- [x] [Review][Dismiss] "No type-prefixing... wait, see Patch above." *(merged into the Patch item, not a separate dismiss.)*
- [x] [Review][Dismiss] "`get_cached_reference` doesn't validate the parsed dict has expected keys (e.g. `'tier' in parsed`), only that it's a dict." The table's only writer is `enrich_reference`'s own well-formed `result` dict — there is no code path that produces a malformed-but-valid-JSON dict under normal operation, only via direct DB tampering, which the existing type check already degrades gracefully (returns `None`, not a crash). Adding key-schema validation would introduce a stricter validation tier than Story 2.1/2.2 established for the equivalent tables (type-only checks); inconsistent with precedent, not a real gap for this story.
- [x] [Review][Dismiss] Thread/process safety (no WAL mode, no `busy_timeout` pragma) — already explicitly out of scope per `ARCHITECTURE-SPINE.md`'s own Deferred section: "Concurrent/multi-user access to the SQLite cache — out of scope; ResGap is a single-user Streamlit session today." Not a new finding, already on record at the architecture level.

**Post-review suite:** 73/73 tests passing (was 70; +3 new: identity type-prefix prevents title/DOI collision, cache-read-failure doesn't abort enrichment, cache-write-failure doesn't discard a successful result; plus 2 existing tests extended in place — stage-version-bump repopulation check, different-title-also-caches check).

## Dev Notes

- **This is the third of four cache-table stories in Epic 2** (2.1 wiki pages — done, 2.2 parameters — done, 2.3 references — this story, 2.4 gap validations — next). `compute_cache_key()` (written in Story 2.1, reused unmodified in Story 2.2) is reused unmodified again here.
- **Per AD-3, reference enrichment is domain-invariant** (like Story 2.2's parameter extraction, unlike Story 2.1's wiki compilation) — `enrich_reference` and every helper it calls (`_ss_by_doi`, `_crossref_by_doi`, `_openalex_by_title`, etc., all read in full above) never reference `domain_config` anywhere. Call `compute_cache_key` with `domain_config=None, relevant_domain_keys=[]`, correctly producing `domain_hash = "none"`, matching the architecture spine's ER diagram (`REFERENCES.cache_key PK "doi_or_title_hash:none:version"`) exactly.
- **This story's single most important, easy-to-get-wrong decision is the identity/cache-key design** (Task 2's first three bullets) — read them carefully before implementing. In short: compute the identity **once, from the input `ref` only, before any API call**, and use that **same** identity for both the pre-call read and the post-call write. Do not use a post-enrichment "resolved" DOI for the write — that would let read and write keys diverge and silently defeat caching for any reference whose DOI is only discovered via API lookup rather than present in the original citation text.
- **Never-cache-the-fallback (Task 2's last two bullets) is this story's AD-2 obligation**, structurally identical in spirit to Story 2.1's "never cache an `LLMCallError` fallback or malformed-JSON stub" and Story 2.2's "never cache an `LLMCallError`" — except here there is no `LLMCallError` at all (`enrich_reference` makes only HTTP calls via `requests`, each already defensively wrapped in its own `try/except Exception: pass` inside helpers like `_ss_by_doi`). The "failure" this story must never cache is `meta` staying `None` after every lookup attempt is exhausted — the existing Tier-3 `parsed_only` return branch.
- **Not in scope:** `parse_references_with_llm` (same file) is a genuine LLM call (`unwrap(client.chat_json(...))`) but is a single per-paper batch call over the whole references section, not a per-reference loop — per the architecture spine and `epics.md`, only `enrich_reference`'s per-reference lookup is bound by AD-2's caching requirement for this story. Do not add caching to `parse_references_with_llm`. It also has no `try/except LLMCallError` guard today (a pre-existing gap, same lineage as Story 2.2's `derive_cross_paper_parameters`/`check_sufficiency` finding) — out of scope here too; note it if you notice it, don't fix it.
- **`extract_and_enrich_references`'s own `try/except Exception` around its `enrich_reference(ref, delay=0.25)` call** (producing an `"enrichment_failed"` tier-3 dict when `enrich_reference` itself raises unexpectedly) is a separate, outer safety net — it does not need any special handling for this story's caching logic. Because caching lives *inside* `enrich_reference` and only writes after a genuine success, any path where `enrich_reference` raises before returning normally can't have triggered a cache write by construction (same protection pattern Stories 2.1/2.2 already rely on).
- **`references` as a SQL table name is a genuine reserved word — SQLite rejects it unquoted** (verified: `CREATE TABLE references (...)`, `INSERT INTO references`, and `SELECT ... FROM references` all fail with a syntax error). Task 1's SQL always uses the double-quoted form `"references"` — every statement touching this table (`CREATE TABLE`, `SELECT`, `INSERT OR REPLACE`) must use it consistently. This is not optional or conditional; there is no unquoted path that works.

### Current State of `enrich_reference` (file being modified — read in full)

```python
def enrich_reference(ref: dict, delay: float = 0.3) -> dict:
    """
    Try multiple APIs to get title + abstract for one reference.
    Priority: Semantic Scholar (DOI) → SS (arxiv) → CrossRef → OpenAlex → SS (title)
    """
    doi      = (ref.get("doi") or "").strip().lower()
    arxiv_id = (ref.get("arxiv_id") or "").strip()
    title    = (ref.get("title") or "").strip()
    # ← Task 2: compute `identity` HERE, from doi/arxiv_id/title above,
    #   before any of the lookups below run. Check cache; return on hit.

    meta = None
    if doi:
        meta = _ss_by_doi(doi)
        time.sleep(delay)
    if not meta and arxiv_id:
        meta = _ss_by_arxiv(arxiv_id)
        time.sleep(delay)
    if not meta and doi:
        meta = _crossref_by_doi(doi)
        time.sleep(delay)
    if not meta and doi:
        meta = _pubmed_search(doi=doi)
        time.sleep(delay)
    if not meta and title and len(title) > 10:
        meta = _openalex_by_title(title)
        time.sleep(delay)
    if not meta and title and len(title) > 10:
        meta = _crossref_search(title)
        time.sleep(delay)
    if not meta and title and len(title) > 10:
        meta = _ss_search_by_title(title)
        time.sleep(delay)
    if not meta and title and len(title) > 10:
        meta = _pubmed_search(title=title)
        time.sleep(delay)

    if meta:
        resolved_doi = doi or (meta.get("externalIds") or {}).get("DOI", "") or meta.get("doi", "")
        open_access_url = None
        if resolved_doi:
            open_access_url = _unpaywall_by_doi(resolved_doi)
        return {
            "title": meta.get("title") or title,
            # ... full normalized Tier-2 dict, unchanged ...
            "tier": 2,
            "source": meta.get("source_api", "api_lookup"),
        }                                       # ← Task 2: cache THIS return value
                                                  #   (using the identity/cache_key
                                                  #   computed at the top, NOT resolved_doi)

    return {
        "title": title or "Unknown",
        # ... Tier-3 "parsed_only" stub, unchanged ...
        "tier": 3,
        "source": "parsed_only",
    }                                           # ← Task 2: NEVER cache this path
```

### Project Structure Notes

- Two files touched: `utils/database.py` (new table + 2 new functions), `pipeline/reference_extractor.py` (cache-check/cache-write wiring in `enrich_reference`).
- No `.gitignore` changes needed — Story 2.1 already covers the SQLite file and its sidecars.
- Aligns with AD-1 — `pipeline/reference_extractor.py` already imports from `utils/*` (`from utils.azure_client import unwrap`); adding `compute_cache_key`/`get_cached_reference`/`save_cached_reference` from `utils.database` doesn't change the dependency direction.
- `enrich_reference`'s public signature (`enrich_reference(ref: dict, delay: float = 0.3) -> dict`) is unchanged — its only caller, `extract_and_enrich_references` in the same file, needs no changes. No other file in the codebase calls `enrich_reference` directly (confirmed via full-repo search).

### Testing Standards

- Continues the established convention: stdlib `unittest`, `tests/` directory, real-SQLite-via-monkeypatched-`DB_PATH` pattern (see `tests/test_database_cache.py`'s `setUp`/`tearDown` for the exact isolation approach — copy it, don't reinvent it).
- No test file exists yet for `pipeline/reference_extractor.py` — this story creates the first one (`tests/test_reference_extractor_cache.py`), scoped only to the caching behavior added here (not a general-purpose test suite for the whole file's parsing/regex logic, which is out of scope).
- Mock `requests.get` via `unittest.mock.patch("pipeline.reference_extractor.requests.get")` with a `MagicMock` returning a fake response object (`status_code`, `.json()`) — do not make real network calls in tests.

### References

- [Source: `_bmad-output/planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md#AD-2`, `#AD-3` — including the ER diagram's `REFERENCES` table shape and the `content_hash` = "DOI/arXiv-id/normalized-title" definition, which is more precise than `epics.md`'s summary (DOI/title only) and is treated as the source of record here]
- [Source: `_bmad-output/planning-artifacts/epics.md#Epic-2-Story-2.3`]
- [Source: `_bmad-output/implementation-artifacts/2-2-cache-extracted-parameters.md` — established the `compute_cache_key()`-reuse pattern for a domain-invariant table, and its code review is the direct source of this story's day-one-hardened `get_cached_reference` design (type validation + `TypeError` catch, not just `JSONDecodeError`)]
- [Source: `pipeline/reference_extractor.py` — full file read, current `enrich_reference`/`extract_and_enrich_references` implementation]
- [Source: `utils/database.py` — full file read, current schema/conventions post-Story-2.2]

## Change Log

- 2026-08-05: `utils/database.py` — added the `"references"` table (double-quoted throughout, since `references` is a genuine SQL reserved word — verified empirically that SQLite rejects it unquoted) and `get_cached_reference()`/`save_cached_reference()`, hardened from day one (per Story 2.2's review learnings) to treat a NULL row or a non-`dict` parsed value as a miss, not a crash. `pipeline/reference_extractor.py` — `enrich_reference` now computes a single `identity` (`doi or arxiv_id.lower() or title.lower()`) once from the input `ref`, checks the cache before any external API call, and writes back only on a genuine Tier-2 metadata hit (`# B17 fix`); the Tier-3 `parsed_only` fallback is never cached. Added `tests/test_reference_extractor_cache.py` (7 tests) and extended `tests/test_database_cache.py` with `ReferencesCacheTests` (6 tests, mirroring `ParametersCacheTests` plus the two NULL/non-dict hardening cases).
- 2026-08-05 (code review pass): tagged the cache identity with its source type (`doi:`/`arxiv:`/`title:`) before hashing, so a title that happens to equal another reference's raw DOI/arXiv-ID string can no longer collide on the same `cache_key`. Wrapped the cache read and cache write in `enrich_reference` so a broken cache (locked DB, disk full) degrades to "no cache" instead of either aborting a lookup before it starts or discarding an already-successful multi-API enrichment. Strengthened two existing tests to verify cache *repopulation*, not just the miss (stage-version bump, distinct-title). Added 3 new tests. Final: 73/73 passing.

## Dev Agent Record

### Agent Model Used

Claude (BMAD dev-story workflow)

### Debug Log References

- RED confirmed per task group: `tests/test_database_cache.py`'s `ReferencesCacheTests` failed with `sqlite3.OperationalError: no such table: references` / `AttributeError: module 'utils.database' has no attribute 'save_cached_reference'` before Task 1; `tests/test_reference_extractor_cache.py` failed with `AttributeError: ... does not have the attribute 'get_cached_reference'` / `'REFERENCE_STAGE_VERSION'` plus call-count mismatches before Task 2.
- One test-design correction made during RED, before implementation: initial call-count assumptions for DOI/arXiv-based test fixtures didn't account for `enrich_reference`'s existing (pre-this-story) Unpaywall open-access lookup, which fires an extra `requests.get` call whenever a DOI is resolved (input-provided or `meta`-derived) — not a bug, just an existing code path the test fixtures needed to account for. Fixed by using `first_call_count = mock_get.call_count` captured after the real call rather than a hardcoded literal, and by giving the OpenAlex title-only fixture an empty `doi` field so that path stays at exactly one call.
- Full suite: `uv run --python 3.11 --with openai --with pdfplumber --with PyMuPDF --with numpy --with scipy --with reportlab --with requests python -m unittest discover -s tests -v` → 70/70 pass (was 57 before this story).
- `py_compile` clean on both modified files; `import pipeline; import utils.database` smoke test clean.
- Code review (3-layer, all completed): Acceptance Auditor found zero spec violations. Edge Case Hunter and Blind Hunter independently converged on the same headline finding (no type-prefix on the cache identity). 4 patches applied, 9 items deferred (all matching Story 2.1/2.2 precedent or requiring an AC-level scope change), 2 dismissed (one merged into the patch, one already covered by the architecture spine's own explicit single-user-session scope).
- Post-review full suite: 73/73 pass (was 70). `py_compile` and import smoke test re-confirmed clean after patches.

### Completion Notes List

- Both tasks complete; 13 new tests total (6 `ReferencesCacheTests` in `test_database_cache.py`, 7 in the new `test_reference_extractor_cache.py`); 70/70 suite passing.
- `compute_cache_key()` reused unmodified from Story 2.1 again, called with `relevant_domain_keys=[]` (domain-invariant per AD-3, matching Story 2.2's `parameters` precedent) — `content_hash` doubles as `doi_or_title_hash` with no separate computation, exactly as the story's Dev Notes anticipated.
- This story's key design point — a single identity computed once from the input `ref`, used identically for both the cache read and write, deliberately not a post-enrichment "resolved" DOI — was implemented exactly as specified and directly tested via the DOI-priority and arXiv-priority tests (same identity holds across a changed `title`) and the title-only vs. different-title test (different identity is a real miss).
- The story's fresh-context creation review caught one concrete, empirically-verified bug before any code was written: `references` is a genuine SQLite reserved word (confirmed by actually running `CREATE TABLE references (...)` — it fails), so all SQL in `utils/database.py` uses the double-quoted `"references"` form from the start. No equivalent issue surfaced during implementation itself.
- Applied Story 2.2's review-derived hardening (`isinstance` type check + `TypeError` catch) to `get_cached_reference` from day one rather than needing a second review cycle to add it, as the story's Dev Notes instructed.
- Code review found two real gaps not anticipated by the story text: (1) no type-tag on the identity before hashing, independently caught by both Edge Case Hunter and Blind Hunter — fixed by prefixing `doi:`/`arxiv:`/`title:`; (2) a cache I/O failure inside `enrich_reference` could silently discard an already-successful, expensive multi-API enrichment via the outer catch-all in `extract_and_enrich_references` — fixed by swallowing cache read/write failures at the `enrich_reference` call site, treating a broken cache as equivalent to no cache rather than a fatal error. Both fixes are directly tested.
- Most deferred findings (7 of 9) are near-identical restatements of already-deferred issues from Story 2.1/2.2 (init_db overhead, missing try/finally, write-only hash column, no cache observability) — the caching pattern's known trade-offs are consistent across all three cache tables, not story-specific regressions.

### File List

- Modified: `utils/database.py`
- Modified: `pipeline/reference_extractor.py`
- Modified: `tests/test_database_cache.py`
- Added: `tests/test_reference_extractor_cache.py`
