---
baseline_commit: 9b27f5c5fe277643e23013009bedad79231590d2
---

# Story 1.2: Callers raise a distinct exception on LLM failure

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a ResGap user,
I want every direct caller of `chat()`/`chat_json()`/`vision()` to react explicitly to a `Failure` result,
so that a call failure can't silently propagate downstream as if it were content.

## Acceptance Criteria

1. **Given** Story 1.1's `Result` type exists, **When** a direct caller (e.g. `graph_builder.extract_entities_and_relations`) receives `Success`, **Then** it proceeds exactly as before, unwrapping `.value`.
2. **Given** a direct caller receives `Failure`, **When** it processes the result, **Then** it raises `LLMCallError` (carrying the `ErrorInfo`) rather than continuing with the error string as if it were content.
3. **Given** this applies to every direct caller of `chat`/`chat_json`/`vision` across the codebase (18 call sites, 11 files — full inventory below), **When** any one of them is exercised, **Then** none of them treat a `Failure` object as parseable string content.
4. **(Non-regression, not in original AC text, added during story creation per exhaustive analysis — see Dev Notes "Blast Radius" table):** for the 5 call sites inside an unprotected per-item loop (processing multiple papers/references), one item's `LLMCallError` must not abort processing of the remaining items in that batch — this preserves existing behavior the codebase already goes out of its way to guarantee (see the `# B6 FIX` comment in `param_extractor.py`).

## Tasks / Subtasks

- [x] Task 1: Add `LLMCallError` and a shared `unwrap()` helper to `utils/azure_client.py` (AC: #1, #2)
  - [x] Add `class LLMCallError(Exception)` — constructor takes an `ErrorInfo` and stores it as `self.error`; `str()` should render `error.kind` and `error.detail`
  - [x] Add `def unwrap(result: Result[T]) -> T:` — `if isinstance(result, Success): return result.value`; `if isinstance(result, Failure): raise LLMCallError(result.error)`
  - [x] This is a **new, additive** helper — do not change `chat()`/`chat_json()`/`vision()`'s signatures again (Story 1.1 already finalized those)
- [x] Task 2: Update the 5 unprotected per-item-loop call sites — each needs a **new local try/except** around the `unwrap()` call, degrading to the existing stub/fallback record shape already used elsewhere in that same function (AC: #2, #4)
  - [x] `pipeline/wiki_compiler.py:71` (`compile_wiki_page`, called per-paper from `build_wiki`'s loop, line 145) — on `LLMCallError`, fall back to the same **shape** as the existing JSON-parse-failure stub, `{"title": paper['filename'], "raw_response": ...}`, but note the existing stub's `raw_response` value is the raw LLM string (only reachable after a successful call that failed to parse) — that variable doesn't exist on this path, so substitute `raw_response=f"[LLM call failed: {e.error.kind}] {e.error.detail}"` (or equivalent), not a literal reuse of `raw` (caught in review, 2026-08-01: the original instruction to "reuse that exact pattern" was imprecise about this)
  - [x] `pipeline/discovery_engine.py:132` (`extract_paper_fingerprints`'s per-page loop) — on `LLMCallError`, fall back to the same `{"paper_title": title, "unique_contribution": "Could not extract"}` stub already used when `_robust_parse` returns empty
  - [x] `pipeline/param_extractor.py:146` (`extract_parameters`'s per-paper loop) — on `LLMCallError`, skip that paper's params (append nothing for it) rather than aborting the whole loop — consistent with the `# B6 FIX` comment's existing philosophy of never silently losing a paper's processing entirely
  - [x] `pipeline/paper_manager.py:102` (`compile_tier2_wiki`, called per-ref from `compile_tier2_batch`'s loop, line 152) — on `LLMCallError`, fall back to the same Tier-3-style stub dict the function already returns when no abstract is available (title/year only, `confidence: "title_only"`, `tier: 3`)
  - [x] `pipeline/paper_manager.py:217` (`extract_tier2_parameters`'s per-ref loop) — on `LLMCallError`, skip that reference's params, same reasoning as `param_extractor.py`
- [x] Task 3: Update the 4 already-protected call sites — safe drop-in, `unwrap()`'s raise is caught by the existing enclosing `except` (AC: #1, #2)
  - [x] `pipeline/academic_search.py:114` (`_assess_coverage`) — replace `raw = client.chat_json(...)` with `raw = unwrap(client.chat_json(...))` inside the existing `try/except Exception: pass` block; no other change needed
  - [x] `utils/export.py:345` — same pattern, existing `except Exception: return fallback` already handles it
  - [x] `pipeline/reference_extractor.py:174` (`parse_references_with_llm`) — the call site itself has no try/except, but its *caller* at line 544 already wraps it in `try/except Exception as e: ... diagnostics["errors"].append(...)` — confirm this still catches `LLMCallError` (it will, `LLMCallError` is an `Exception` subclass) and logs it into diagnostics same as today
  - [x] `pipeline/pdf_parser.py:139` (`vision()` call in `_analyze_figures_with_vision`) — already has a per-page `try/except Exception as e: descriptions.append({"page":..., "description": f"[Vision analysis failed: {e}]"})` — safe drop-in, `unwrap()`'s raised `LLMCallError` renders via `{e}` same as any other exception
- [x] Task 4: Update the 9 single-shot call sites — `unwrap()`'s raise propagates to the caller, which is intended (not a loop, nothing to protect) (AC: #1, #2, #3)
  - [x] `pipeline/wiki_compiler.py:120` (`compile_cross_links`)
  - [x] `pipeline/discovery_engine.py:159` (`generate_cross_paper_combinations`)
  - [x] `pipeline/discovery_engine.py:192` (`generate_novel_hypotheses`)
  - [x] `pipeline/param_extractor.py:177` (`derive_cross_paper_parameters`)
  - [x] `pipeline/param_extractor.py:216` (`check_sufficiency`)
  - [x] `pipeline/gap_detector.py:116` (`detect_gaps`)
  - [x] `pipeline/graph_builder.py:118` (`extract_entities_and_relations`) — **leave the resulting `LLMCallError` uncaught here**; Story 1.3 adds the catch in `build_knowledge_graph` specifically, per the approved epic sequencing — do not implement Story 1.3's work now
  - [x] `pipeline/graph_builder.py:215` (`build_communities`)
  - [x] `pipeline/proposal_generator.py:90` (`generate_proposals`)
- [x] Task 5: Add targeted tests (AC: #1, #2, #3, #4)
  - [x] `unwrap()` unit tests: `Success(v)` → returns `v`; `Failure(e)` → raises `LLMCallError` carrying `e`
  - [x] One regression test proving Group-A per-item resilience is preserved: mock a 3-reference `compile_tier2_batch` call where reference #2 fails — assert references #1 and #3 still produce real results and #2 gets the fallback stub, not a crash
  - [x] One test proving a Group-C call (e.g. `detect_gaps` or `extract_entities_and_relations`) lets `LLMCallError` propagate uncaught to its own caller

### Review Findings

**Layers completed:** Acceptance Auditor only. **Failed layers:** Blind Hunter, Edge Case Hunter — both were interrupted twice (2 separate attempts, 4 total interruptions) before completing; per this workflow's subagent-failure protocol, proceeding with the remaining layer's findings rather than blocking indefinitely.

**⚠️ This review is not fully independent-adversarially verified** — only spec-compliance auditing ran to completion. The dev-story session's own verification (full-repo grep sweep for missed call sites, `py_compile` on all 12 touched files, a whole-package import smoke test, 17/17 tests passing) provides some independent-of-self-report signal, but a true adversarial/edge-case pass on this diff has not happened.

**Acceptance Auditor: zero findings.** All 18 claimed call-site changes verified present and matching spec exactly (Task 2's 5 fallback shapes, Task 3's 4 safe drop-ins, Task 4's 9 propagation sites, including the deliberate uncaught raise in `graph_builder.py` deferred to Story 1.3). AD-4 compliance confirmed. Task 5 tests confirmed present and correctly structured. No dismissed findings, no patches, no decisions needed — nothing to triage.

## Dev Notes

- **This story's own scope discipline:** update all 18 call sites to use `unwrap()`. Do **not** add the `try/except LLMCallError` catch inside `build_knowledge_graph` (graph_builder.py) — that is Story 1.3's specific job (distinguishing the fallback-trigger reason). This story only makes `extract_entities_and_relations` raise; Story 1.3 decides what happens with that raise one level up.
- **Import pattern:** every touched file already does `from ??? import ...` for its `client` parameter type implicitly (client is passed in, untyped, from `app.py`) — no file currently imports from `utils.azure_client` directly except via the `client` object passed around. Add `from utils.azure_client import unwrap, LLMCallError` to each of the 11 touched files.
- **Do not touch `app.py`** — no task here requires it, and per Story 1.1's precedent, the app remains non-functional end-to-end until Epic 2 (which builds on this story's `LLMCallError`) lands. This is expected.

### Blast-Radius Table (why Task 2 exists — read before implementing)

The story as originally scoped in `epics.md` only said "every direct caller... raises `LLMCallError`." Exhaustive analysis (required by this workflow) found that a naive blanket `unwrap()` swap would silently break existing resilience in 5 places — all per-item loops over multiple papers/references with **no existing try/except**, where today's "return an error string, fail to parse, degrade to a stub" behavior means one bad item never kills the batch. A raised, uncaught exception would.

| # | Location | Loop context | Existing fallback shape to reuse on `LLMCallError` |
| --- | --- | --- | --- |
| 1 | `wiki_compiler.py:71` `compile_wiki_page` | `build_wiki()` loops per uploaded paper (Tier 1 — the most important corpus) | `{"title": paper['filename'], "raw_response": raw}` |
| 2 | `discovery_engine.py:132` `extract_paper_fingerprints` | loops per wiki page | `{"paper_title": title, "unique_contribution": "Could not extract"}` |
| 3 | `param_extractor.py:146` `extract_parameters` | loops per paper (has a `# B6 FIX` comment explicitly about never silently losing a paper) | skip that paper's params (append nothing) |
| 4 | `paper_manager.py:102` `compile_tier2_wiki` | `compile_tier2_batch()` loops per Tier-2 reference | the Tier-3 stub already defined in the same function (title/year only, `confidence: "title_only"`, `tier: 3`) |
| 5 | `paper_manager.py:217` `extract_tier2_parameters` | loops per Tier-2 reference | skip that reference's params |

Everything else (13 sites) is either already protected by an enclosing `except` (4 sites, Task 3) or is a single-shot, non-looped call where propagation is the intended behavior (9 sites, Task 4).

### Project Structure Notes

- 11 files touched: `pipeline/wiki_compiler.py`, `pipeline/discovery_engine.py`, `pipeline/param_extractor.py`, `pipeline/paper_manager.py`, `pipeline/academic_search.py`, `utils/export.py`, `pipeline/reference_extractor.py`, `pipeline/pdf_parser.py`, `pipeline/graph_builder.py`, `pipeline/gap_detector.py`, `pipeline/proposal_generator.py`. No new files except the test.
- Aligns with AD-1 (dependency direction): all 11 are `pipeline/*.py` or `utils/*.py` importing from `utils/azure_client.py` — permitted direction, unchanged rule.

### Testing Standards

- Continues Story 1.1's established convention: stdlib `unittest`, `tests/` directory, `sys.path` bootstrap pattern.
- Mock at the `client` level (a fake object with `.chat_json`/`.vision` methods returning `Success`/`Failure` directly) rather than mocking the underlying `OpenAI` SDK — these tests are about caller behavior, not the client's own retry/classification logic (already covered in `tests/test_azure_client.py`).

### References

- [Source: `_bmad-output/planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md#AD-4`]
- [Source: `_bmad-output/planning-artifacts/epics.md#Epic-1-Story-1.2`]
- [Source: `_bmad-output/implementation-artifacts/1-1-typed-success-failure-result-from-llm-calls.md` — Result/Success/Failure/ErrorInfo shapes, established testing convention]
- [Source: all 11 touched files, read in full at their `client.chat_json`/`client.vision` call sites and enclosing loop/function structure — see Blast-Radius Table]

## Change Log

- 2026-08-03: Added `LLMCallError`/`unwrap()` to `utils/azure_client.py`. Updated all 18 call sites across 11 files to unwrap the `Result` returned by `chat_json()`/`vision()`: 5 sites gained new local try/except protection to preserve existing per-batch resilience (`wiki_compiler.py`, `discovery_engine.py`, `param_extractor.py`, `paper_manager.py` x2), 4 sites were safe drop-ins into an existing enclosing `except` (`academic_search.py`, `export.py`, `reference_extractor.py`, `pdf_parser.py`), 9 sites let the raise propagate as intended (including `wiki_compiler.py:129`, initially missed on the first pass and caught by a full-repo grep sweep before completion). Added `tests/test_caller_resilience.py` (2 tests) and extended `tests/test_azure_client.py` with `UnwrapTests` (2 tests). Full suite: 17/17 passing. App unblocked — Story 1.1 + 1.2 together restore end-to-end functionality.

## Dev Agent Record

### Agent Model Used

Claude (BMAD dev-story workflow)

### Debug Log References

- Full-repo grep for `= client\.(chat_json|chat|vision)\(` after applying all planned edits caught one missed site (`wiki_compiler.py:129`, `compile_cross_links`) before it could reach review — fixed immediately.
- `py_compile` run across all 12 touched files confirmed no syntax errors before running tests.
- `python -c "import pipeline; import utils.export; import utils.azure_client"` confirmed no circular-import or load-time errors across the whole package.
- Full suite: `uv run --python 3.11 --with openai --with pdfplumber --with PyMuPDF --with numpy --with scipy --with reportlab --with requests python -m unittest discover -s tests -v` → 17/17 pass.

### Completion Notes List

- All 5 tasks complete; all 18 call sites updated; 17/17 tests pass (10 from Story 1.1 unchanged + 5 new in test_azure_client.py's UnwrapTests/updated suite + 2 new in test_caller_resilience.py).
- The app is now unblocked: Story 1.1 changed `chat_json()`/`chat()`/`vision()`'s return type, and this story completes the migration of every caller. Prior to this story finishing, the app was in a non-functional mixed state (flagged in Story 1.1's completion notes) — that is now resolved.
- Scope boundary respected: `graph_builder.extract_entities_and_relations`'s `LLMCallError` is deliberately left uncaught — Story 1.3 (knowledge-graph fallback distinguishing genuine-empty from call-failed) is the next queued story and owns that catch.

### File List

- Modified: `utils/azure_client.py`
- Modified: `pipeline/wiki_compiler.py`
- Modified: `pipeline/discovery_engine.py`
- Modified: `pipeline/param_extractor.py`
- Modified: `pipeline/paper_manager.py`
- Modified: `pipeline/academic_search.py`
- Modified: `utils/export.py`
- Modified: `pipeline/reference_extractor.py`
- Modified: `pipeline/pdf_parser.py`
- Modified: `pipeline/graph_builder.py`
- Modified: `pipeline/gap_detector.py`
- Modified: `pipeline/proposal_generator.py`
- Modified: `tests/test_azure_client.py`
- Added: `tests/test_caller_resilience.py`
