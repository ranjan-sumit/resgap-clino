---
baseline_commit: bfeac27170d61fec025be55e7c4e1125064c09ca
---

# Story 2.1: Cache compiled wiki pages

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a ResGap user,
I want a paper's compiled wiki page to be cached,
so that re-analyzing a previously-uploaded paper doesn't re-spend an LLM call.

## Acceptance Criteria

1. **Given** `utils/database.py`, **When** this story ships, **Then** a new `wiki_pages` table exists with columns `cache_key` (PK), `content_hash`, `domain_hash`, `stage_logic_version`, `wiki_json`.
2. **Given** `compile_wiki_page` is called for a paper, **When** a matching `cache_key` (`content_hash:domain_hash:stage_logic_version`, SHA-256, `domain_hash` from canonical JSON of the relevant `domain_config` subset) already has a row, **Then** the cached `wiki_json` is returned and no `chat_json` call is made.
3. **Given** no matching `cache_key` exists, **When** `compile_wiki_page` completes with a genuine `Success`-and-clean-parse result, **Then** the result is written to the cache before being returned; a `Failure`/`LLMCallError` — or a `Success` that failed to parse as valid JSON — is never cached.

## Tasks / Subtasks

- [x] Task 1: Add a shared cache-key helper to `utils/database.py` (AC: #1, #2, reused by later Epic 2 stories)
  - [x] Add `def compute_cache_key(content: str, domain_config: dict | None, relevant_domain_keys: list[str], stage_logic_version: int) -> tuple[str, str, str]:` returning `(cache_key, content_hash, domain_hash)`
  - [x] `content_hash = hashlib.sha256(content.encode()).hexdigest()`
  - [x] If `domain_config` and `relevant_domain_keys` are both truthy: `domain_hash = hashlib.sha256(json.dumps({k: domain_config.get(k) for k in relevant_domain_keys}, sort_keys=True, default=str).encode()).hexdigest()`. Otherwise `domain_hash = "none"` (the literal string, per AD-3)
  - [x] `cache_key = f"{content_hash}:{domain_hash}:{stage_logic_version}"`
  - [x] This helper is intentionally generic — Stories 2.2/2.3/2.4 (parameters/references/gap_validations caching) will reuse it rather than reimplementing hash logic
- [x] Task 2: Add the `wiki_pages` table and cache read/write functions to `utils/database.py` (AC: #1, #2, #3)
  - [x] Add `CREATE TABLE IF NOT EXISTS wiki_pages (cache_key TEXT PRIMARY KEY, content_hash TEXT, domain_hash TEXT, stage_logic_version INTEGER, wiki_json TEXT)` to the existing `init_db()` executescript, alongside `runs`/`papers`
  - [x] Add `def get_cached_wiki_page(cache_key: str) -> dict | None:` — call `init_db()` first (every existing function in this file does — `save_run`, `list_runs`, `load_run`, `delete_run`, `get_run_papers` all call it defensively; don't rely on `app.py`'s startup call being the only path in), then `SELECT wiki_json FROM wiki_pages WHERE cache_key = ?`; return `json.loads(row["wiki_json"])` on a hit, `None` on a miss
  - [x] Add `def save_cached_wiki_page(cache_key: str, content_hash: str, domain_hash: str, stage_logic_version: int, wiki_json: dict) -> None:` — call `init_db()` first (same reasoning), then `INSERT OR REPLACE INTO wiki_pages (...)  VALUES (...)`, `json.dumps(wiki_json, default=str)` for storage (matches the existing `_compress`/`save_run` convention of `default=str` for non-JSON-native types)
- [x] Task 3: Wire caching into `compile_wiki_page` (`pipeline/wiki_compiler.py`) (AC: #2, #3)
  - [x] Add module constant `WIKI_STAGE_VERSION = 1`
  - [x] At the top of `compile_wiki_page`, compute the cache key from `paper.get("full_text", "")` (the complete extracted paper text — not the `excerpt`, which is a lossy derived subset) and `["wiki_focus", "wiki_entity_examples"]` as the relevant domain keys (the only two keys `inject_domain_into_wiki_prompt` actually reads — confirmed by reading `domain_config.py`; do not hash the whole `domain_config` dict, it would cause needless cache misses from unrelated key changes like `gap_priorities`)
  - [x] Check the cache first: `cached = get_cached_wiki_page(cache_key); if cached is not None: return cached` — before building the excerpt/tree outline/calling the LLM at all
  - [x] On a cache miss, proceed exactly as today (excerpt, prompt, `unwrap(client.chat_json(...))`)
  - [x] **Caching boundary — read carefully:** only cache on the genuine-success-and-clean-parse path, i.e. only when `wiki = json.loads(raw)` succeeds directly (no `JSONDecodeError`). Do **not** cache: the `LLMCallError` fallback stub (already returns early, per Story 1.2/AD-2), **and do not cache the malformed-JSON fallback stub either** (`{"title": ..., "raw_response": raw}`) — that's also a degraded result, not the clean structured wiki AD-2's "genuine Success-path result" means. Call `save_cached_wiki_page(...)` only in the `try: wiki = json.loads(raw)` success branch, after `source_file`/`char_count` are attached, right before the `return wiki` at the end of the clean-parse path
- [x] Task 4: Repo hygiene — the SQLite file this table lives in isn't gitignored yet (AC: none, but directly relevant — this story is what starts writing real content into it)
  - [x] Add `data/*.db` to `.gitignore`
- [x] Task 5: Add targeted tests (AC: #1, #2, #3)
  - [x] `compute_cache_key`: same content+domain+version → same key; different content → different key; different domain subset → different key; `domain_config=None` → `domain_hash == "none"`
  - [x] `compile_wiki_page` cache miss: calls `chat_json` once, then a second call with the identical paper/tree/domain_config does **not** call `chat_json` again and returns the same wiki dict
  - [x] `compile_wiki_page` on `LLMCallError`: returns the fallback stub (existing Story-1.2 behavior, unchanged) and does **not** write anything to the cache — verify via a follow-up call that a cache lookup for that key still misses
  - [x] `compile_wiki_page` on a `Success` with unparseable JSON: returns the `raw_response` stub and does **not** cache it either — same follow-up-lookup-still-misses check
  - [x] Use a real (temp-file or in-memory-via-monkeypatched `DB_PATH`) SQLite connection for these tests, not a mocked `utils.database` module — the whole point is verifying the actual read/write round-trip works; see Dev Notes for the exact test-isolation approach

### Review Findings

Blind Hunter and Edge Case Hunter independently converged on the same critical gap (empty-content cache collision) using different methods — treated as the headline finding.

- [x] [Review][Patch] **CRITICAL: empty/whitespace-only `full_text` (scanned/image-only PDFs) produces a cache-key collision across unrelated papers** — every such paper hashes to the same `cache_key`, so the second paper silently receives the first paper's cached wiki (wrong title, wrong everything), no error. **Fixed:** `compile_wiki_page` now skips the cache entirely (never reads, never writes) whenever `full_text.strip()` is empty — these papers always recompile, exactly as before this story existed.
- [x] [Review][Patch] **A cache hit returned a stale `source_file`/`char_count`** when two uploads share identical content under different filenames (the story's own "re-analyzing a previously-uploaded paper" scenario covers exactly this, including renames). **Fixed:** on a cache hit, the current call's `paper["filename"]`/`char_count` are re-stamped onto a copy of the cached dict before returning, rather than returning the cached dict verbatim.
- [x] [Review][Patch] `content=None` (not just missing) would crash `.encode()` inside `compute_cache_key`. **Fixed:** `hashlib.sha256((content or "").encode())`.
- [x] [Review][Patch] `get_cached_wiki_page` had no guard against a corrupted/unparseable `wiki_json` cell — would raise `json.JSONDecodeError` out of what's supposed to be a transparent cache-miss path, crashing the caller harder than having no cache at all. **Fixed:** wrapped in `try/except json.JSONDecodeError`, treated as a miss.
- [x] [Review][Patch] `compute_cache_key`'s domain-invariant contract (`"none"` domain_hash) was gated on `domain_config` being truthy, not just `relevant_domain_keys` — a real `domain_config` dict that simply doesn't contain the relevant keys would compute a spurious real hash instead of the documented `"none"`. Since this helper is reused unmodified by Stories 2.2-2.4, tightened now. **Fixed:** condition changed to `if relevant_domain_keys:` alone, using `(domain_config or {})` inside.
- [x] [Review][Patch] `.gitignore`'s `data/*.db` didn't cover SQLite sidecar files (`-journal`/`-wal`/`-shm`) that an interrupted transaction can leave behind. **Fixed:** added all three patterns.
- [x] [Review][Patch] Cache-hit test only asserted one field (`title`), not the full returned dict — a bug dropping/mutating other keys would have passed. **Fixed:** now asserts full dict equality (adjusted for the filename-re-stamping fix above).
- [x] [Review][Patch] "Never cached" tests inferred non-caching only from LLM call-count, never a direct `get_cached_wiki_page(cache_key) is None` check — weaker than the task spec asked for. **Fixed:** both tests now assert the direct lookup too.
- [x] [Review][Patch] No test exercised `WIKI_STAGE_VERSION` bump at the integration level (only unit-tested in `compute_cache_key` directly) — the module comment's stated purpose was asserted only at the helper level, never at the point it protects. **Fixed:** added `test_stage_version_bump_bypasses_a_previously_cached_entry`.
- [x] [Review][Patch] No test combined a real `domain_config` with the never-cache-on-failure path (all failure/malformed tests used `domain_config=None`) — a plausible gap since `domain_hash` computation sits in the same code path. **Fixed:** added `test_llm_call_error_is_never_cached_with_a_real_domain_config`.
- [x] [Review][Defer] `get_cached_wiki_page`/`save_cached_wiki_page` have no `try/finally` around their SQLite calls, so an exception mid-call (locked DB, disk full) would skip `conn.close()`. **Deferred** — this is the existing convention throughout every function in `database.py` (`save_run`, `list_runs`, `load_run`, `delete_run`, `get_run_papers` all have the identical gap); fixing only the two new functions would be inconsistent, and fixing the whole file is a broader change out of this story's scope.
- [x] [Review][Defer] No cache hit/miss observability (log line, counter) anywhere — the entire feature exists to save LLM spend but nothing currently confirms it's working in production. **Deferred** — no established logging convention exists anywhere in this codebase yet; introducing one is a bigger, separately-scoped decision, not a one-line fix.
- [x] [Review][Defer] Rows from a superseded `WIKI_STAGE_VERSION` are shadowed, not cleaned up — they sit in the table forever. **Deferred** — this is a specific instance of the architecture spine's already-deferred "cache growth/retention policy" item (`ARCHITECTURE-SPINE.md` Deferred section), not a new gap.
- [x] [Review][Dismiss] "No test verifies the `default=str` serialization path" — checked: `wiki_json` values always come from `json.loads(raw)`, which only ever produces JSON-native types. `default=str` is defensive padding matching the existing `save_run` convention but is genuinely unreachable for this specific table; a contrived test would test nothing real.
- [x] [Review][Dismiss] "AD-2 enforced only by a hand-rolled `cache_write_ok` flag, no shared mechanism preventing future misuse" — valid observation, but not an actionable code change for this story (would require a type-level redesign). Noted as guidance for Stories 2.2-2.4's implementers rather than dismissed outright: read this story's Dev Notes on the caching boundary before reusing the pattern.

**Post-review suite:** 45/45 tests passing (was 38; +7 new: empty-content collision, filename-re-stamp on hit, None-content safety, domain-invariant-contract tightening, corrupted-row-as-miss, stage-version-bump integration, domain_config+failure-path combination).

## Dev Notes

- **This is the first of four cache-table stories in Epic 2** (2.1 wiki pages, 2.2 parameters, 2.3 references, 2.4 gap validations). `compute_cache_key` (Task 1) is written once here and reused by all three remaining stories — get its contract right now.
- **Per AD-3, `domain_hash` is only computed for domain-conditioned stages.** Wiki compilation is domain-conditioned (confirmed: `inject_domain_into_wiki_prompt` reads `wiki_focus`/`wiki_entity_examples` from `domain_config`) — this story computes a real `domain_hash`. Story 2.2 (parameter extraction) is **not** domain-conditioned (`param_extractor.py` never calls any `inject_domain_into_*` function) — when that story reuses `compute_cache_key`, it will pass `domain_config=None`, correctly producing `domain_hash = "none"`.
- **Why `full_text`, not `excerpt`:** `get_smart_excerpt()` is a lossy, prioritized subset of the paper (limitations/future-work/results/abstract sections, capped at 10000 chars) — two different papers, or the same paper re-parsed slightly differently, could produce the same excerpt while having different full text, or vice versa near truncation boundaries. `paper["full_text"]` (set by `pdf_parser.parse_pdf`) is the authoritative, complete extracted text and is what should determine cache identity.
- **Why not hash the PageIndex `tree` too:** `tree` is deterministically derived from the same parsed paper structure `full_text` comes from — if `full_text` is identical, `tree` will be too. Hashing it separately would be redundant, not more correct.
- **The caching boundary (Task 3's last bullet) is the single most important, easy-to-get-wrong part of this story.** There are three distinct outcomes from a cache-miss attempt: (a) `LLMCallError` → fallback stub, never cache; (b) `Success` but `json.loads` fails → malformed stub, never cache; (c) `Success` and `json.loads` succeeds → real wiki, cache it. Only (c) is a cache-write. Getting this wrong in either direction is bad: caching (a) or (b) would permanently freeze a transient failure or a bad parse into the cache (worse than not caching at all, since a retry might have succeeded); never caching (c) would defeat the entire story.
- **Note on (b) vs. AD-2's literal text:** `ARCHITECTURE-SPINE.md`'s AD-2 rule explicitly discusses the `LLMCallError` case (a) but doesn't literally say what to do about a `Success` response that fails to parse as JSON (b). Treating (b) as "also never cache" is this story's own reasoned extension of AD-2's spirit ("only cache genuine good results"), not a literal restatement of the spine — flagging this so it reads as a deliberate interpretation, not a claim that the spine already spelled it out.

### Current State of `compile_wiki_page` (file being modified — read in full)

```python
def compile_wiki_page(paper: dict, tree, client, domain_config: dict = None) -> dict:
    excerpt = get_smart_excerpt(paper, max_chars=10000)
    tree_outline = tree_to_summary(tree, max_chars=1500)
    user_prompt = f"""..."""
    try:
        raw = unwrap(client.chat_json(
            inject_domain_into_wiki_prompt(WIKI_SYSTEM_PROMPT, domain_config or {}),
            user_prompt, max_tokens=2500
        ))
    except LLMCallError as e:
        wiki = {"title": paper['filename'], "raw_response": f"[LLM call failed: {e.error.kind}] {e.error.detail}"}
        wiki["source_file"] = paper["filename"]
        wiki["char_count"] = paper.get("char_count", 0)
        return wiki                                    # ← Task 3: never cache this path

    try:
        wiki = json.loads(raw)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                wiki = json.loads(match.group())
            except Exception:
                wiki = {"title": paper['filename'], "raw_response": raw}
        else:
            wiki = {"title": paper['filename'], "raw_response": raw}
        # ← Task 3: this whole except block's outcome is ALSO a "never cache" stub —
        #   even the nested match.group() success is still just recovered raw text,
        #   not confidently structured JSON from the primary path

    wiki["source_file"] = paper["filename"]
    wiki["char_count"] = paper.get("char_count", 0)
    return wiki                                        # ← Task 3: only cache when this
                                                         #   return was reached via the
                                                         #   `try: wiki = json.loads(raw)`
                                                         #   success line, not the except block
```

### Current State of `utils/database.py` (file being modified — read in full)

Already has `runs`/`papers` tables, `init_db()`, `_get_conn()`, and a `_compress`/`_decompress` pair (gzip, used only for the `runs.results_gz` blob — the new `wiki_pages.wiki_json` column stores plain `json.dumps(..., default=str)` text, not gzip-compressed, since individual wiki pages are small and don't need compression, and plain-text storage makes manual DB inspection/debugging easier). `DB_DIR`/`DB_PATH` resolve relative to `__file__` (`Path(__file__).parent.parent / "data"`), unchanged by this story.

### Project Structure Notes

- Two files touched: `utils/database.py` (new table + 3 new functions), `pipeline/wiki_compiler.py` (cache-check/cache-write wiring in `compile_wiki_page`). Plus `.gitignore` (one line).
- Aligns with AD-1 (dependency direction) — `pipeline/wiki_compiler.py` already imports from `utils/*`; adding an import from `utils.database` doesn't change that direction. `utils/database.py` gains no new imports beyond stdlib (`hashlib` — check if already imported; it is, for `_run_id`).

### Testing Standards

- Continues the established convention: stdlib `unittest`, `tests/` directory.
- **Database tests need real SQLite, not mocks** — patch `utils.database.DB_PATH`/`DB_DIR` to a temp directory per test (`tempfile.TemporaryDirectory()` in `setUp`/`tearDown`, or a pytest-style fixture equivalent under `unittest`) so tests don't touch the real `data/run_history.db` and don't leak state between test runs. Call `init_db()` explicitly at the start of each test needing the table.

### References

- [Source: `_bmad-output/planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md#AD-2`, `#AD-3`]
- [Source: `_bmad-output/planning-artifacts/epics.md#Epic-2-Story-2.1`]
- [Source: `utils/database.py` — full file read, existing schema/conventions]
- [Source: `pipeline/wiki_compiler.py` — full file read, current `compile_wiki_page` implementation post-Story-1.2]
- [Source: `pipeline/pdf_parser.py` lines 151-181 (`parse_pdf`) — confirms `paper["full_text"]` is the authoritative complete text]
- [Source: `domain_config.py` lines 381-391 (`inject_domain_into_wiki_prompt`) — confirms only `wiki_focus`/`wiki_entity_examples` are read for this stage]

## Change Log

- 2026-08-04: `utils/database.py` — added `compute_cache_key()` (shared AD-3 helper for all Epic 2 cache tables), the `wiki_pages` table, and `get_cached_wiki_page()`/`save_cached_wiki_page()`. `pipeline/wiki_compiler.py` — `compile_wiki_page` now checks the cache first and writes back only on a genuine, cleanly-parsed success (`# B14 fix`), never on an `LLMCallError` fallback or a malformed-JSON stub. `.gitignore` — added `data/*.db`. Added `tests/test_database_cache.py` and `tests/test_wiki_compiler_cache.py`.
- 2026-08-04 (code review pass, `# B15 fix`): fixed a critical cache-key collision for empty/whitespace-only `full_text` (scanned/image-only PDFs would silently share cached wiki data across unrelated papers) by skipping the cache entirely for such papers. Fixed a cache hit returning a stale `source_file`/`char_count` for a renamed re-upload of identical content, by re-stamping those two fields onto a copy of the cached dict. Hardened `compute_cache_key`/`get_cached_wiki_page` against `None` content and corrupted cache rows. Tightened the domain-invariant `"none"` contract to key off `relevant_domain_keys` alone. Extended `.gitignore` to cover SQLite sidecar files. Added 7 more tests. Final: 45/45 passing.

## Dev Agent Record

### Agent Model Used

Claude (BMAD dev-story workflow)

### Debug Log References

- RED confirmed twice, per task group: `tests/test_database_cache.py` failed with `AttributeError: module 'utils.database' has no attribute 'save_cached_wiki_page'` before Tasks 1-2; `tests/test_wiki_compiler_cache.py`'s `test_cache_miss_then_hit_skips_second_llm_call` failed (`2 != 1` calls) before Task 3.
- One test-fixture bug caught and fixed during RED (not a code bug): my own hand-rolled tree stub was missing a `word_count` key `tree_to_summary` requires — switched to the real `build_tree()` helper instead of a fragile hand-rolled fixture.
- Code review (3-layer, all completed): Blind Hunter and Edge Case Hunter independently found the empty-content cache-collision bug via different methods; Blind Hunter separately found the stale-filename-on-hit bug. Both fixed, 7 new tests added.
- Full suite: `uv run --python 3.11 --with openai --with pdfplumber --with PyMuPDF --with numpy --with scipy --with reportlab --with requests python -m unittest discover -s tests -v` → 45/45 pass (was 38 before review).
- `py_compile` clean on both modified files, before and after the review fixes; `import pipeline; import utils.database` smoke test clean.

### Completion Notes List

- All 5 tasks complete; 20 new tests total (13 from initial implementation + 7 from the review pass); 45/45 suite passing.
- `compute_cache_key()` is written generically per its Dev Notes rationale — Stories 2.2 (parameters, domain-invariant), 2.3 (references, domain-invariant), and 2.4 (gap validations, domain-conditioned) should reuse it directly rather than reimplementing hash logic. Its domain-invariant contract was tightened during review specifically because of this planned reuse.
- The two most important fixes from review (empty-content collision, stale-filename-on-hit) are both realistic production scenarios directly implied by this story's own premise ("re-analyzing a previously-uploaded paper" covers renamed re-uploads; ResGap explicitly handles 50+ paper corpora, some of which will be scanned/image-only PDFs) — worth the extra care for the stories that reuse this pattern next.

### File List

- Modified: `utils/database.py`
- Modified: `pipeline/wiki_compiler.py`
- Modified: `.gitignore`
- Added: `tests/test_database_cache.py`
- Added: `tests/test_wiki_compiler_cache.py`
