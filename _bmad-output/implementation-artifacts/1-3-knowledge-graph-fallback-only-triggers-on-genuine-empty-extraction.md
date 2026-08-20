---
baseline_commit: 71b3f08773f381aece926edb4b5c745e8f7893e9
---

# Story 1.3: Knowledge-graph fallback only triggers on genuine empty extraction

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a ResGap user,
I want the knowledge-graph fallback to only apply when the LLM genuinely found no entities,
so that a report's "fallback used" diagnostic means what it says instead of also covering silent API failures.

## Acceptance Criteria

1. **Given** Story 1.2's `LLMCallError` exists, **When** `build_knowledge_graph` calls `extract_entities_and_relations` and it raises `LLMCallError`, **Then** `build_knowledge_graph` catches it distinctly and records `diagnostics.fallback_reason` as `"LLM call failed: {detail}"` — not the current generic "LLM graph extraction returned no entities".
2. **Given** `extract_entities_and_relations` returns `Success` with a parsed but empty entities list, **When** `build_knowledge_graph` evaluates the result, **Then** it still falls back to `_fallback_graph_from_wiki` as today, with `fallback_reason` unchanged ("LLM graph extraction returned no entities").
3. **And** in both cases the correct, distinct diagnostic reason is what ends up in any generated report — both paths still return the same overall shape (`entities`, `relationships`, `communities`, `orphan_concepts`, `missing_bridges`, `network_data`, `diagnostics`, `stats`).

## Tasks / Subtasks

- [x] Task 1: Wrap the `extract_entities_and_relations` call in `try/except LLMCallError` inside `build_knowledge_graph` (AC: #1, #2, #3)
  - [x] Import `LLMCallError` alongside the existing `unwrap` import in `pipeline/graph_builder.py` (currently only `unwrap` is imported there — added by Story 1.2)
  - [x] On `LLMCallError`, set `graph_data = _fallback_graph_from_wiki(wiki)` and build `diagnostics` directly as `{"used_fallback": True, "raw_response_preview": "", "llm_entities": 0, "llm_relationships": 0, "fallback_reason": f"LLM call failed: {e.error.detail}"}`
  - [x] On success, keep the existing logic unchanged: build `diagnostics` from `graph_data`, then `if not graph_data.get("entities"):` fall back with `fallback_reason = "LLM graph extraction returned no entities."` exactly as today
  - [x] Do **not** duplicate the tail of the function (`build_communities`/`find_orphan_concepts`/`find_missing_bridges`/`prepare_network_diagram_data`/the final `return` dict) — both branches must converge into that single shared tail, run once, not copy-pasted into each branch
- [x] Task 2: Add targeted tests (AC: #1, #2, #3)
  - [x] Test: a client whose `chat_json` returns `Failure(...)` → `build_knowledge_graph` does not raise, returns a fallback graph, and `diagnostics["fallback_reason"] == "LLM call failed: {detail}"` with the actual `detail` text interpolated
  - [x] Test: a client whose `chat_json` returns `Success('{"entities": [], "relationships": []}')` (genuinely empty) → `build_knowledge_graph` returns a fallback graph, and `diagnostics["fallback_reason"] == "LLM graph extraction returned no entities."` (unchanged wording — regression guard on the existing behavior)
  - [x] Test: a client whose `chat_json` returns `Success` with real entities → `diagnostics["used_fallback"] is False`, no `fallback_reason` key at all (unchanged from today — regression guard)
  - [x] Test (added during implementation, not in original task list — see Dev Notes "Discovered During Implementation"): `LLMCallError` path does not fire a second LLM call via `build_communities`

### Review Findings

Both Blind Hunter and Edge Case Hunter independently converged on the same critical gap using different methods (adversarial reasoning vs. mechanical path tracing) — strong signal, treated as the headline finding rather than two separate ones.

- [x] [Review][Patch] **`build_communities`'s own `unwrap()` call was completely unprotected** — the original fix only pre-emptively skipped it right after a *known* extraction failure, but did nothing for the more realistic case of extraction succeeding while the *separate* community-detection call fails on its own (e.g. a rate limit starting mid-run). This meant the story's core promise — no uncaught crash from an LLM failure in this function — was only half-delivered. **Fixed:** replaced the `skip_communities` flag with a direct `try/except LLMCallError` around the `build_communities` call itself, protecting every path uniformly. This also resolves the flag's fragility and the asymmetric-protection findings below as a side effect of the same fix.
- [x] [Review][Patch] `error.kind` was discarded entirely from `diagnostics` — only the free-text `detail` was threaded through, forcing any downstream consumer to string-match the message to distinguish retryable (`rate_limit`/`timeout`) from hard (`api_error`) failures. **Fixed:** added `diagnostics["fallback_kind"] = e.error.kind`.
- [x] [Review][Patch] No test proved the genuine-empty-extraction path still calls `build_communities` (only the failure path's *skip* was tested) — the code comment claimed this was preserved but nothing verified it. **Fixed:** added `test_genuine_empty_extraction_still_attempts_community_detection` with distinct per-call mock responses (`side_effect`, not a single shared `return_value`).
- [x] [Review][Patch] No test covered `"timeout"`/`"api_error"` kind values for the fallback-reason formatting (only `"rate_limit"` was tested). **Fixed:** added `test_llm_call_failure_reason_formats_for_every_error_kind`.
- [x] [Review][Patch] No test covered the empty-wiki boundary for the LLM-failure fallback path. **Fixed:** added `test_llm_call_failure_with_empty_wiki_still_returns_sane_result` — also corrected a wrong assumption in my own first draft of this test (`_fallback_graph_from_wiki` always adds a "domain" entity for the paper itself, even with no other extractable fields; the test initially expected zero entities).
- [x] [Review][Patch] The module docstring's "Fixed bugs" list wasn't extended to mention this change, inconsistent with the file's own established convention. **Fixed:** added entry 13.
- [x] [Review][Patch] `diagnostics["fallback_reason"]`/`["fallback_kind"]` are conditionally-present keys with no guard or comment warning callers. **Fixed:** added a one-line comment above the `diagnostics` return key.
- [x] [Review][Defer] Raw, untruncated exception text flows into `fallback_reason` via `e.error.detail`. **Deferred** — consistent with the same, already-accepted risk on `ErrorInfo.detail` generally, deferred during Story 1.1's review (`deferred-work.md`); this is another consumer of that same field, not a new exposure.
- [x] [Review][Dismiss] Edge Case Hunter: `e.error` could theoretically be `None`/lack `.detail`. **Dismissed** — not reachable; `Failure.error: ErrorInfo` is a required, non-optional dataclass field by construction (Story 1.1/1.2), so `LLMCallError.error` is always a real `ErrorInfo`.
- [x] [Review][Dismiss] Edge Case Hunter: `_fallback_graph_from_wiki` could theoretically raise inside the except block. **Dismissed** — independently verified during story creation: the function does pure dict/list manipulation only, no I/O or LLM calls, cannot raise `LLMCallError` or need its own guard.
- [x] [Review][Defer] Edge Case Hunter: `extract_entities_and_relations` could theoretically raise something other than `LLMCallError`. **Deferred** — speculative given current code paths (safe dict/string ops only), not caused by this change; broadening the `except` to bare `Exception` would be a separate design decision with its own trade-offs (risks masking unrelated bugs), not an unambiguous patch.

**Post-review suite:** 25/25 tests passing (was 21; +4 new: kind-formatting, empty-wiki boundary, genuine-empty-still-calls-communities, community-failure-after-successful-extraction).

## Dev Notes

### Discovered During Implementation

The RED-phase test for AC #1 initially failed **after** the fix was applied — not because the fix was wrong, but because it exposed a real, non-obvious bug: the fallback graph built by `_fallback_graph_from_wiki` typically has non-empty entities (populated from wiki fields), so the function's tail still called `build_communities(graph_data, client)` — a *second* LLM call — immediately after the *first* one had just failed. If the LLM is genuinely down/rate-limited (the realistic case this story exists for), that second call very likely fails too, propagating `LLMCallError` uncaught and crashing `build_knowledge_graph` anyway — defeating the story's entire purpose. Fixed by skipping `build_communities` (returning `communities: []`) specifically in the `LLMCallError` branch, via a `skip_communities` flag that still converges into the single shared tail (no duplicated return blocks). The genuine-empty-extraction path is unaffected — nothing there indicates the LLM itself is failing, so it still calls `build_communities` as before. Per this workflow's own instruction, a story must leave the system working end-to-end, not just satisfy its literal stated ACs — this was exactly that case.

- **Small, single-file story.** Only `pipeline/graph_builder.py` changes — one function, `build_knowledge_graph` (currently lines 334-366). No other file is touched.
- **This is the one deferred piece from Story 1.2.** `extract_entities_and_relations` (same file, lines 93-138) already raises `LLMCallError` on a failed LLM call — Story 1.2 deliberately left it uncaught with a comment pointing here. This story is only about catching it correctly at this one call site.
- **Current behavior being changed:** right now, an `LLMCallError` from `extract_entities_and_relations` propagates fully uncaught out of `build_knowledge_graph`, out of `app.py`'s `build_knowledge_graph(...)` call (line 822), and is caught only by `app.py`'s broad top-level `try/except Exception` (line 766-887) — which aborts the entire multi-stage pipeline run with a generic error, instead of degrading gracefully to a fallback graph and continuing to gap detection, proposals, etc. like every other transient failure in this pipeline is designed to do.
- **Do not change `_fallback_graph_from_wiki`, `extract_entities_and_relations`, or anything else in the file** — this story is scoped to `build_knowledge_graph`'s error handling only.

### Current State of `build_knowledge_graph` (to be modified — read in full)

```python
def build_knowledge_graph(wiki: dict, client, domain_config: dict = None) -> dict:
    graph_data  = extract_entities_and_relations(wiki, client, domain_config=domain_config)
    diagnostics = {
        "used_fallback": bool(graph_data.get("_used_fallback")),
        "raw_response_preview": graph_data.get("_raw_response_preview", ""),
        "llm_entities": len(graph_data.get("entities", [])),
        "llm_relationships": len(graph_data.get("relationships", [])),
    }
    if not graph_data.get("entities"):
        graph_data = _fallback_graph_from_wiki(wiki)
        diagnostics["used_fallback"] = True
        diagnostics["fallback_reason"] = "LLM graph extraction returned no entities."
    communities = build_communities(graph_data, client)
    orphans     = find_orphan_concepts(graph_data, wiki)
    bridges     = find_missing_bridges(graph_data, wiki)
    network     = prepare_network_diagram_data(graph_data)

    return {
        "entities":       graph_data.get("entities", []),
        "relationships":  graph_data.get("relationships", []),
        "communities":    communities,
        "orphan_concepts": orphans,
        "missing_bridges": bridges,
        "network_data":   network,
        "diagnostics":    diagnostics,
        "stats": {
            "entity_count":       len(graph_data.get("entities", [])),
            "relationship_count": len(graph_data.get("relationships", [])),
            "community_count":    len(communities),
            "orphan_count":       len(orphans),
            "bridge_count":       len(bridges),
        },
    }
```

The whole first block (`graph_data = extract_entities_and_relations(...)` through the `if not graph_data.get("entities"):` fallback) needs wrapping in `try/except LLMCallError`, with the `except` branch producing an equivalent `graph_data`/`diagnostics` pair so the unchanged tail (`communities = build_communities(...)` onward) still works identically for both paths.

### Project Structure Notes

- Single file touched: `pipeline/graph_builder.py`. No new files except the test additions.
- Aligns with AD-1 — no new imports beyond `LLMCallError` from the already-permitted `utils.azure_client`.

### Testing Standards

- Continues the established convention: stdlib `unittest`, `tests/` directory. Mock at the `client` level (fake object with `.chat_json` returning `Success`/`Failure` directly), same style as `tests/test_caller_resilience.py`.
- Recommend a new file `tests/test_graph_builder_fallback.py` rather than adding to an existing test file, since this is a distinct concern (diagnostic accuracy, not caller-migration mechanics).

### References

- [Source: `_bmad-output/planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md#AD-4`]
- [Source: `_bmad-output/planning-artifacts/epics.md#Epic-1-Story-1.3`]
- [Source: `_bmad-output/implementation-artifacts/1-2-callers-raise-a-distinct-exception-on-llm-failure.md` — established the `LLMCallError`/`unwrap()` contract this story consumes, and explicitly deferred this exact catch]
- [Source: `pipeline/graph_builder.py` lines 93-138 (`extract_entities_and_relations`), 146-198 (`_fallback_graph_from_wiki`), 334-366 (`build_knowledge_graph`, the function being modified) — read in full]
- [Source: `app.py` lines 766-887 (top-level pipeline try/except), line 822 (`build_knowledge_graph` call site) — confirms current uncaught-propagation behavior]

## Change Log

- 2026-08-04: `pipeline/graph_builder.py` — `build_knowledge_graph` now wraps entity extraction in `try/except LLMCallError`, producing a distinct `diagnostics.fallback_reason` for a failed call vs. a genuine empty extraction (`# B13 fix`). Added `tests/test_graph_builder_fallback.py`.
- 2026-08-04 (code review pass): replaced the initial `skip_communities` flag with a direct `try/except LLMCallError` around `build_communities` itself, protecting every path uniformly rather than only the extraction-just-failed case (two independent reviewers converged on this gap). Added `diagnostics["fallback_kind"]`. Extended the module docstring's bug list. Added 4 more tests (kind-formatting, empty-wiki boundary, genuine-empty-still-calls-communities, community-failure-after-successful-extraction). Final: 25/25 tests passing.

## Dev Agent Record

### Agent Model Used

Claude (BMAD dev-story workflow)

### Debug Log References

- RED confirmed: `test_llm_call_failure_produces_distinct_fallback_reason` failed with uncaught `LLMCallError` against the unmodified file.
- First GREEN attempt still failed the same test — traced to `build_communities` firing a second `chat_json` call that hit the same mocked `Failure`, uncaught (Group C site, correctly unprotected per Story 1.2's design, but not accounted for by this story's original plan). Fixed via a `skip_communities` flag initially; re-ran, all green (21/21).
- Code review (3-layer, all completed this time): Blind Hunter and Edge Case Hunter independently found the `skip_communities` flag only protected the extraction-just-failed case, not the more realistic "extraction succeeded, community detection fails independently" case. Replaced with a direct `try/except` around `build_communities` itself. Re-ran full suite with 4 new tests: 25/25 pass.
- `py_compile` clean; `import pipeline` smoke test clean, both before and after the review-driven redesign.

### Completion Notes List

- All 2 tasks complete; 8 tests total (3 planned + 5 added across implementation and review); 25/25 suite passing.
- The review process caught a real, significant gap that TDD alone didn't surface (my own test happened to always fail *both* mocked calls the same way, masking the asymmetry) — independent adversarial review remains valuable even after a TDD cycle already found one bug.
- Epic 1 (Honest Failure Signaling) is now fully complete: Stories 1.1, 1.2, 1.3 all done. The `LLMCallError`/`unwrap()`/fallback-diagnostics chain is now consistent end-to-end from the LLM client boundary through to the knowledge-graph stage, and every LLM call within `build_knowledge_graph` is protected against an uncaught crash.

### File List

- Modified: `pipeline/graph_builder.py`
- Added: `tests/test_graph_builder_fallback.py`
