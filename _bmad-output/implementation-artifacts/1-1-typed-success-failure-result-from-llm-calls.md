---
baseline_commit: 9b27f5c5fe277643e23013009bedad79231590d2
---

# Story 1.1: Typed success/failure result from LLM calls

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a ResGap user,
I want the LLM client to clearly signal whether a call succeeded or failed,
so that pipeline stages never mistake a failed call for real content.

## Acceptance Criteria

1. **Given** a successful `chat()`/`chat_json()`/`vision()` call, **When** the response streams back normally, **Then** the method returns `Success(value)` wrapping the real content.
2. **Given** a call that exhausts its retries (timeout, rate limit, or API error), **When** the failure is final, **Then** the method returns `Failure(error)` with `error.kind` set to `timeout`|`rate_limit`|`api_error` and `error.detail` containing the underlying message, and never returns a plain string standing in for the error.

## Tasks / Subtasks

- [x] Task 1: Define the Result type in `utils/azure_client.py` (AC: #1, #2)
  - [x] Add `T = TypeVar("T")`
  - [x] Add `@dataclass(frozen=True) class ErrorInfo` with `kind: Literal["timeout", "rate_limit", "api_error"]` and `detail: str`
  - [x] Add `@dataclass(frozen=True) class Success(Generic[T])` with `value: T`
  - [x] Add `@dataclass(frozen=True) class Failure` with `error: ErrorInfo` (not generic — always wraps `ErrorInfo`)
  - [x] Add `Result = Success[T] | Failure` — **`Result` has exactly one free type parameter (the success value type)**. Annotate return types as `Result[str]`, never `Result[str, ErrorInfo]` — `Failure` isn't generic, so a second type argument is a `TypeError` at definition time (no `from __future__ import annotations` is in place to defer evaluation)
- [x] Task 2: Update `chat()` to return `Result[str]` (AC: #1, #2)
  - [x] On a normal streamed response, wrap the collected content in `Success(value)` instead of returning the bare string
  - [x] Replace the current fallback `return f"[API error after {_retry+1} attempt(s): {err[:200]}]"` (line 78 today) with `return Failure(ErrorInfo(kind=..., detail=str(e)))` once retries are exhausted
  - [x] Classify `error.kind` from the caught exception text, checked in this priority order (first match wins): `"rate_limit"` if `"429"` or `"rate"` is in the error text; else `"timeout"` if `"timeout"` is in the error text; else `"api_error"`. Reuse the existing retry-trigger substring check at line 72 as the classification source — don't reinvent a second check.
- [x] Task 3: Update `chat_json()` to propagate the same `Result` (AC: #1, #2)
  - [x] `chat_json()` only modifies the system prompt before delegating to `self.chat()` — once `chat()` returns `Result`, `chat_json()` should return exactly what `self.chat()` returns, unchanged in shape
- [x] Task 4: Update `vision()` to return `Result[str]` (AC: #1, #2)
  - [x] `vision()` currently has its own independent try/except (not shared with `chat()`'s retry logic) and returns `f"[Vision unavailable: {e}]"` on failure (line 116 today) — replace with `Failure(ErrorInfo(kind=_classify_error(str(e)), detail=str(e)))`. **(Revised during code review, decision resolved 2026-08-01):** classify rather than hardcode `"api_error"` — a vision call can genuinely hit a timeout or rate limit even without retry logic, and classifying keeps `vision()` consistent with `chat()`'s reporting.
  - [x] On success, wrap the collected content in `Success(value)`
- [x] Task 5: Add targeted unit tests for the Result type behavior (AC: #1, #2)
  - [x] Test `chat()` returns `Success` on a mocked successful stream
  - [x] Test `chat()` returns `Failure` with the correct `error.kind` after exhausting retries, for each of the three failure classifications
  - [x] Test `chat_json()` and `vision()` return the same `Result` shape on both paths

### Review Findings

- [x] [Review][Decision] `vision()` classifies `error.kind` via `_classify_error()` instead of hardcoding `"api_error"` as Task 4 literally specified — **Resolved 2026-08-01: keep classify.** More correct/consistent with `chat()`; Task 4 text updated to match.
- [x] [Review][Patch] Retry-eligibility check in `chat()` and `_classify_error()` are duplicated, independently-maintained substring checks — violates Task 2's explicit "reuse, don't reinvent" instruction; also both use imprecise bare-substring matching ("rate" matches "generate"/"moderate"; "timeout" misses "timed out") [utils/azure_client.py:41-48,108-112] — **Fixed:** `chat()` now calls `_classify_error()` once and reuses its result for both retry-eligibility and `error.kind`; regex tightened to `rate.?limit` and `timeout`/`timed out`.
- [x] [Review][Patch] `chat()`'s `Failure` truncates `detail` to `err[:200]`, contradicting Task 2's literal replacement code and AC #2's "containing the underlying message" [utils/azure_client.py:~114] — **Fixed:** truncation removed, `detail=err` (full message).
- [x] [Review][Patch] `vision()`'s `Failure` truncates `detail` to `str(e)[:200]`, same issue, and a regression versus the untruncated string `vision()` returned before this story [utils/azure_client.py:~152] — **Fixed:** truncation removed.
- [x] [Review][Patch] `chat()`'s docstring still claims "one automatic retry" while `MAX_RETRIES = 2` (three attempts total) — this diff touches that exact docstring block without correcting the adjacent stale claim [utils/azure_client.py:85] — **Fixed:** now says "up to two automatic retries."
- [x] [Review][Patch] Missing test: a retryable error on the first attempt followed by success on retry — only permanent exhaustion and immediate success are currently tested [tests/test_azure_client.py] — **Fixed:** added `test_chat_recovers_after_transient_failure`.
- [x] [Review][Patch] Missing test: `_classify_error`'s documented priority order (rate_limit before timeout) is unverified for a message containing both signals [tests/test_azure_client.py] — **Fixed:** added `ClassifyErrorTests` (priority order + word-boundary + "timed out" cases).
- [x] [Review][Patch] `vision()`'s failure path calls `str(e)` twice instead of once, unlike `chat()` [utils/azure_client.py:~151-152] — **Fixed:** computed once as `err`.
- [x] [Review][Patch] `vision()`'s docstring doesn't mention it now returns `Result[str]`, unlike `chat()`'s explicit note [utils/azure_client.py:128] — **Fixed:** docstring updated.
- [x] [Review][Patch] No `.gitignore` exists; this story's new test file already produced a committable `__pycache__` artifact — first story to introduce this risk [repo root] — **Fixed:** added `.gitignore` (`__pycache__/`, `*.pyc`).
- [x] [Review][Patch] Test doesn't assert `make_nvidia_client` was called with the correct `api_key` — constructor wiring exercised incidentally, never verified [tests/test_azure_client.py] — **Fixed:** added `test_constructor_passes_api_key_to_make_nvidia_client`.
- [x] [Review][Defer] Exception text flows unredacted into `ErrorInfo.detail` (a now-structured, more-loggable field) — deferred, pre-existing exposure (the old sentinel string embedded the same text); no AC/constraint governs redaction
- [x] [Review][Defer] No Python version pin anywhere despite this file now depending on PEP 604 `X | Y` union syntax (3.10+) — deferred, pre-existing project-wide gap, not owned by this story
- [x] [Review][Defer] `tests/test_azure_client.py` mutates `sys.path` at module scope to enable imports — deferred, tied to the still-open test-framework/test-infra convention question already flagged in this story's Open Questions

## Dev Notes

- This story is the foundation for AD-4 (`ARCHITECTURE-SPINE.md`) and is the first story in Epic 1, which Epic 2 depends on for its "never cache a failure" rule (AD-2) — get the `Success`/`Failure`/`ErrorInfo` shapes right here since every later story in Epics 1 and 2 imports them.
- **Scope discipline:** this story defines the `Result` type and updates the three client methods only. It does **not** touch any caller (`graph_builder.py`, `wiki_compiler.py`, etc.) — that is Story 1.2's job. Do not raise `LLMCallError` in this story; that exception class doesn't exist yet and is Story 1.2's responsibility to define and use.
- Per AD-4's Rule (`ARCHITECTURE-SPINE.md`), all **three** methods — `chat`, `chat_json`, and `vision` — must return the Result type, not just `chat`/`chat_json`. This was a specific finding from the architecture spine's reviewer gate: `vision()` was originally missed and has the identical sentinel-string bug today.
- Per the Consistency Conventions table (`ARCHITECTURE-SPINE.md` §Data & formats): `Result[str]` = `Success(value: str)` | `Failure(error: ErrorInfo)`; `ErrorInfo` carries `kind` (`timeout`|`rate_limit`|`api_error`) and `detail`. This story is where those types are actually defined — no prior story has created them.
- No new project structure is required — `ErrorInfo`, `Success`, and `Failure` are added directly inside `utils/azure_client.py` (the sole file this story touches), not a new module. Future stories (1.2 onward) import them from there alongside the existing `AzureOpenAIClient` import.

### Current State of `utils/azure_client.py` (file being modified — read in full)

The file currently has no `Result`/`Success`/`Failure` types at all. Relevant current behavior, by line:

- **Lines 9–13:** imports `base64` and `OpenAI` from the `openai` package. `Generic`, `TypeVar`, `Union`/`|`, `Literal`, and `dataclass` will need new imports from `typing`/`dataclasses` (stdlib only — no new dependency, consistent with NFR4).
- **Lines 47–78 (`chat`)**: streams a response via `_collect_stream`, returns the plain string on success. On exception, retries up to `MAX_RETRIES = 2` with exponential backoff (`time.sleep(2 ** _retry)`) **only if** `"timeout" in err.lower() or "rate" in err.lower() or "429" in err` (line 72) — this substring check is the existing signal for retryable errors and should be reused (not reinvented) to classify `error.kind` in Task 2. On final failure, returns the sentinel string `f"[API error after {_retry+1} attempt(s): {err[:200]}]"` (line 78) — this exact line is what AC #2 requires replaced.
- **Lines 80–88 (`chat_json`)**: appends a "return ONLY valid JSON" instruction to the system prompt, then calls `self.chat(...)` and returns its result directly — no independent success/failure logic of its own. Once `chat()` returns `Result`, this method requires no logic change beyond its return type following `chat()`'s.
- **Lines 90–116 (`vision`)**: builds a base64-encoded image message, streams a response, and has its **own separate** try/except (does not call `self.chat()` or share its retry logic) returning `f"[Vision unavailable: {e}]"` on any exception (line 116) with **no retry at all** — note this for Task 4; the story only requires wrapping in `Result`, not adding retry logic to `vision()` (that's out of scope here, not requested by AD-4 or AC #2).
- **What must be preserved:** the streaming mechanics (`_collect_stream`, `stream=True` on every call), the existing `MAX_RETRIES`/backoff behavior in `chat()`, and `make_nvidia_client()`'s NVIDIA NIM base URL/model wiring — none of this changes in this story, only the return type.

### Project Structure Notes

- Single file touched: `utils/azure_client.py`. No new files, no new directories.
- Aligns with `ARCHITECTURE-SPINE.md`'s AD-1 (dependency direction) — `utils/azure_client.py` continues to import nothing from `pipeline/*.py`, this story doesn't change that.
- No conflicts detected with existing project structure.

### Testing Standards

- **No test suite or framework exists anywhere in this repository today** (confirmed in `project-context.md`). This is the first story to add tests. Recommend Python's built-in `unittest` (stdlib, zero new dependency, consistent with NFR4's "no new infrastructure") over `pytest`, since no test framework decision has been made anywhere in this BMAD chain and `unittest` avoids adding a dependency purely for testing. **This is flagged as an open question below rather than silently decided** — it's a real, project-wide precedent-setting choice, not just this story's call.
- Mock the `OpenAI` client's `chat.completions.create` to simulate: (a) a normal streamed success, (b) a timeout exception, (c) a 429/rate-limit exception, (d) a generic API error — covering all three `error.kind` classifications plus the success path.

### References

- [Source: `_bmad-output/planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md#AD-4`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md#Consistency-Conventions`]
- [Source: `_bmad-output/planning-artifacts/epics.md#Epic-1-Story-1.1`]
- [Source: `_bmad-output/specs/spec-resgap-pipeline-fixes/SPEC.md#Capabilities` — CAP-3, NFR3]
- [Source: `_bmad-output/project-context.md` — confirms no existing test suite/framework]
- [Source: `utils/azure_client.py` lines 9–116 — current implementation being modified]

## Latest Technical Specifics (web-verified)

The dataclass-based Result pattern used above (`Success`/`Failure` as frozen dataclasses combined via `Union`/`|`, with `isinstance`/`match`-based dispatch by callers) is the current idiomatic approach for this pattern in Python — confirmed via web research during story creation, not assumed from training data. No third-party library is needed; Python 3.11's stdlib `dataclasses`, `typing.Generic`/`TypeVar`, and structural pattern matching (`match`/`case`, available since 3.10) are sufficient, consistent with NFR4's "no new infrastructure."

Sources: [Build a Simple Result type in Python](https://hamy.xyz/blog/2024-06_python-result-type), [Idiomatic algebraic data types in Python with dataclasses and Union](https://blog.ezyang.com/2020/10/idiomatic-algebraic-data-types-in-python-with-dataclasses-and-union/)

## Project Context Reference

- `project-context.md`'s "LLM Client Rules" section (already documents `chat()`'s current retry/sentinel-string behavior) should be updated once this story ships, since it currently describes the pre-fix behavior this story replaces. Not this story's job to edit — noted for whoever reviews/merges.
- `project-context.md`'s "Bug-Fix Changelog Convention" (`# B<N> fix:` inline comments) should be followed if this change is later described as a fix in code comments, per existing project convention.

## Open Questions (for user — not blocking story creation, but should be answered before/during dev)

1. **Test framework choice:** no test framework has been selected anywhere in this project or BMAD chain. This story (and later Story 3.2, which also requires isolated unit tests) needs one. Recommendation above is stdlib `unittest` to avoid a new dependency — confirm, or specify `pytest` if preferred despite the added dependency.

## Change Log

- 2026-07-31: `utils/azure_client.py` — added `ErrorInfo`/`Success`/`Failure`/`Result` types and `_classify_error()`; `chat()`, `chat_json()`, `vision()` now return `Result[str]` instead of a plain string that doubled as an error sentinel (`# B11 fix` comment added, following the project's existing bug-fix changelog convention). Added `tests/test_azure_client.py` (first test file in this repository).
- 2026-08-01: Code review — resolved 1 decision (keep `_classify_error()` classification in `vision()` rather than hardcoding `"api_error"`) and applied 10 patches: consolidated the duplicated retry/classification logic into a single `_classify_error()` call, tightened its substring matching (word-boundary rate-limit match, added "timed out"), removed `[:200]` truncation from both `chat()` and `vision()`'s `Failure.detail`, corrected `chat()`'s stale "one automatic retry" docstring, fixed `vision()`'s double `str(e)` call, added a `Result[str]` note to `vision()`'s docstring, added `.gitignore`, and added 4 tests (transient-recovery, classification priority order, word-boundary matching, constructor wiring). 3 items deferred (pre-existing, out of this story's scope) — see `deferred-work.md`.

## Dev Agent Record

### Agent Model Used

Claude (BMAD dev-story workflow)

### Debug Log References

- RED phase confirmed: `python -m unittest tests.test_azure_client` failed with `ImportError: cannot import name 'Success'` against the unmodified file, before any implementation change.
- GREEN phase confirmed: same command, all 8 tests pass after implementation (`uv run --python 3.11 --with openai python -m unittest tests.test_azure_client -v`).
- Post-review: all 13 tests pass (8 original + 4 added during review + 1 constructor-wiring test) after applying all 10 patches.

### Completion Notes List

- All 5 tasks complete; all 13 unit tests pass (8 original + 5 added during code review); no pre-existing tests to regress (this is the first test file in the repo).
- Independent 3-layer code review (Blind Hunter, Edge Case Hunter, Acceptance Auditor) ran against the diff: 1 decision resolved, 10 patches applied, 3 items deferred as pre-existing/out-of-scope, 2 dismissed as already-disclosed or non-issues. Full findings recorded above under Review Findings.
- **Transitional note for reviewer:** this story intentionally changes `chat()`/`chat_json()`/`vision()`'s return type from `str` to `Result[str]`, and — per its explicit scope boundary — does **not** update any caller (`graph_builder.py`, `wiki_compiler.py`, `param_extractor.py`, `reference_extractor.py`, `academic_search.py`, `llm_council.py`, `pdf_parser.py`). Every current caller still treats the return value as a plain string (e.g. `json.loads(raw)`), so the app will not run end-to-end until Story 1.2 updates those call sites. This is the expected, approved incremental sequence from `epics.md` (Story 1.2 depends on this story's output), not an oversight.
- `project-context.md`'s "LLM Client Rules" section still describes the pre-fix sentinel-string behavior this story replaces — flagged for a follow-up documentation update (not in this story's scope; no task covered it).
- Test framework: proceeded with the story's recommended stdlib `unittest` (flagged as an open question in the story; user confirmed proceeding without objection).

### File List

- Modified: `utils/azure_client.py`
- Added: `tests/test_azure_client.py`
- Added: `.gitignore`
