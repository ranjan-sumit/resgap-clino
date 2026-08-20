---
baseline_commit: c9b53fc13d40b36828c48d5f514a856676a2172d
---

# Story 3.1: Exclude low-confidence parameters from simulation

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a ResGap user,
I want low-confidence, LLM-invented parameter estimates excluded from computational modelling,
so that simulated numbers aren't built on invented data.

## Acceptance Criteria

1. **Given** a set of extracted parameters with mixed confidence levels, **When** `simulation_engine._sample()` (and the callers that select parameters for simulation) run, **Then** only parameters with `confidence` in `{"medium", "high"}` are included in the simulation. A parameter with `confidence` missing entirely, or any value other than `"medium"`/`"high"` (including `"low"`), is excluded — this is an allow-list (only `medium`/`high` are usable), not a block-list of `"low"` specifically, so a malformed/incomplete extraction fails closed rather than silently sneaking into the simulation.
2. **Given** parameters with `confidence == "low"` (or missing/invalid `confidence`) exist, **When** simulation results are produced, **Then** those excluded parameters are listed separately (`excluded_low_confidence` in the results dict returned by `run_simulation()`) rather than silently dropped or silently included.

## Tasks / Subtasks

- [x] Task 1: Add a single, reusable confidence-gate filter (`pipeline/simulation_engine.py`) (AC: #1, #2)
  - [x] **Critical design point — read before implementing.** `_sample(p: dict, n: int) -> np.ndarray` takes **one** parameter dict, not a list — it structurally cannot "exclude" anything; it always samples from whatever it's handed. AD-6's rule ("`_sample()` only accepts parameters where confidence in {medium, high}") is satisfied by filtering **once, at the top of the whole call chain**, before any parameter ever reaches `_sample()` or any of the 7 `run_*` algorithm functions — not by adding per-call filtering logic scattered across `_by_cat`, each `run_*` function, or `_sample` itself. Confirmed via full-file read: only `run_monte_carlo` calls `_sample()` at all (4 call sites); every other algorithm (`run_markov`, `run_survival_analysis`, `run_bayesian_network`, `run_bootstrap`, `run_tornado`) reads `p.get("value")`/`p.get("ci_lower")` etc. directly. Filtering once at the single shared entry point (`run_simulation`) automatically confidence-gates all 7 algorithms with no per-function changes needed.
  - [x] Add:
    ```python
    def filter_confident_params(params: list) -> tuple[list, list]:
        """Split params by AD-6's confidence gate: only medium/high-confidence
        estimates are safe to simulate -- a low-confidence (or missing/invalid
        confidence) value is LLM-invented from vague language ("majority" -> 60)
        and must not be sampled with the same weight as a real measured
        statistic. Returns (usable, excluded) -- excluded is surfaced in the
        results dict, never silently dropped or silently included."""
        usable   = [p for p in params if p.get("confidence") in ("medium", "high")]
        excluded = [p for p in params if p.get("confidence") not in ("medium", "high")]
        return usable, excluded
    ```
  - [x] **Also add a defensive, fail-loud guard inside `_sample()` itself** — belt-and-suspenders, and AD-6/AC #1 literally name `_sample()` as a binding target, not just its callers: at the top of `_sample`, `if p.get("confidence") not in ("medium", "high"): raise ValueError(f"_sample() called with disallowed confidence: {p.get('confidence')!r} (AD-6: only medium/high permitted)")`. Under the Task 1 filtering design above, this should never actually trigger in the normal `run_simulation()` → `run_all_applicable()` → `run_monte_carlo()` → `_sample()` call path (every param reaching it will already be confidence-gated) — it exists to make a *future* bypass (a new code path calling `_sample()` directly on an unfiltered param) fail loudly instead of silently simulating invented data. This matches the codebase's established philosophy (Epic 1: explicit `LLMCallError` instead of a silent sentinel string) rather than a new one invented for this story.
- [x] Task 2: Wire the filter into `run_simulation()` (`pipeline/simulation_engine.py`) (AC: #1, #2)
  - [x] `run_simulation()` is the module's single public entry point (confirmed: `app.py` is the only external caller, importing `run_simulation` and `auto_select_models` — see Task 3). Update it:
    ```python
    def run_simulation(params: list, council_decision: dict, sufficiency: dict = None) -> dict:
        """Main dispatcher — runs all applicable algorithms."""
        simulation_params, excluded_low_confidence = filter_confident_params(params)
        result = run_all_applicable(simulation_params, council_decision, sufficiency or {})
        result["excluded_low_confidence"] = excluded_low_confidence
        return result
    ```
  - [x] `run_all_applicable`, `auto_select_models`, `_by_cat`, and every individual `run_*` function are **unchanged** — they now simply always receive an already-confidence-gated `params` list from `run_simulation`, with no awareness of confidence filtering needed inside them. Do not add confidence checks inside any of these; the single upstream filter is sufficient and is the whole point of this design (DRY, one choke point, no per-algorithm drift).
- [x] Task 3: Fix `app.py`'s separate, un-gated `auto_select_models` call so its progress-display message doesn't diverge from what `run_simulation()` actually runs (AC: #1)
  - [x] **Real, discovered gap — read before implementing.** `app.py` line ~1417 calls `auto_select_models(params, sufficiency)` **directly**, separately from `run_simulation(params, model_council, sufficiency)` at line ~1419, purely to build a progress-bar message ("Stage 10 — Running N algorithms: X, Y, Z…") shown to the user *before* the simulation actually runs. Both calls currently receive the same **raw, unfiltered** `params`. Once Task 2 lands, `run_simulation()` internally filters before selecting/running models — meaning the progress message (computed from unfiltered params) could name a model that won't actually run, or imply more input data than the simulation will actually use, if any of that model's driving parameters turn out to be low-confidence. This is a real, if minor, user-facing inconsistency this story's own change introduces if left unfixed — flagged during story creation, not discovered mid-implementation.
  - [x] Fix: import `filter_confident_params` in `app.py` alongside the existing `run_simulation`, `auto_select_models` import, and compute the auto-select preview against the same filtered set:
    ```python
    from pipeline.simulation_engine import run_simulation, auto_select_models, filter_confident_params
    ...
    simulation_params, _ = filter_confident_params(params)
    models_auto = auto_select_models(simulation_params, sufficiency)
    cupd(f"Stage 10 — Running {len(models_auto)} algorithms: {', '.join(models_auto)}…", 57)
    sim_results = run_simulation(params, model_council, sufficiency)  # unchanged -- filters internally
    ```
  - [x] **Not in scope**: `council_select_model(params, sufficiency, context, client)` (Stage 9, `pipeline/llm_council.py`) is called with the raw, unfiltered `params` and stays that way — AD-6's binding list is `param_extractor.py` output consumed by `simulation_engine.py` specifically, not `llm_council.py`. Whether the LLM council's model-selection reasoning should also be confidence-gated is a separate, unscoped question — do not touch `llm_council.py` in this story.
- [x] Task 4: Add targeted tests (AC: #1, #2)
  - [x] New `tests/test_simulation_confidence_gate.py` (first test file for this module):
    - `filter_confident_params` splits a mixed list correctly: `confidence="high"` and `confidence="medium"` params land in `usable`; `confidence="low"` lands in `excluded`.
    - A param with `confidence` key **missing entirely** lands in `excluded`, not silently included (proves the allow-list, not block-list, design).
    - A param with an invalid/typo'd confidence value (e.g. `"Medium"` mis-cased, or `"unknown"`) lands in `excluded` — proves the check is a strict membership test against exactly `{"medium", "high"}`, not a fuzzy/case-insensitive one (document this as the deliberate literal-match design; `param_extractor.py`'s prompt always requests exactly `"high"|"medium"|"low"` lowercase, so this isn't overly strict for real LLM output).
    - `_sample()` raises `ValueError` when called directly on a `confidence="low"` param, and on a param with no `confidence` key at all — proves the defensive guard.
    - `_sample()` does **not** raise for `confidence="medium"` or `confidence="high"` — proves the guard doesn't over-trigger on legitimate input.
    - `run_simulation()`'s returned dict contains `excluded_low_confidence` with exactly the low/missing-confidence params from the input, and none of the medium/high-confidence ones.
    - `run_simulation()` with an all-low-confidence params list still returns a result dict (doesn't crash) with `excluded_low_confidence` containing everything and the algorithm results reflecting an effectively-empty simulation input (mirrors the existing `run_bootstrap`/`run_tornado` "no numeric params" empty-input handling already in the file — confirm it degrades the same graceful way, not a new crash).
    - A high-confidence risk-ratio (`odds_ratio`/`relative_risk`/`hazard_ratio`) parameter mixed with a low-confidence one, run through **`run_simulation()`** (not `run_monte_carlo()` directly — `run_monte_carlo` is unchanged and confidence-blind by design, so calling it directly would disprove nothing). Build enough params (≥3, so `auto_select_models` includes `"monte_carlo"`) and a `council_decision` dict with `final_decision.selected_model` set to trigger the Monte Carlo path; assert via `result["algorithm_results"]["monte_carlo"]` that only the high-confidence ratio's value shaped `combined_risk` — confirms the filter actually reaches `run_monte_carlo`'s risk-pooling path end-to-end (Story 3.2 will later replace *how* pooling works, not *whether* the filter reaches it — this test only proves the latter).

### Review Findings

Blind Hunter did the heaviest lifting this pass, including a sharp, correct critique of this story's own Task 3 fix (it didn't fully close the gap it claimed to); Edge Case Hunter and Acceptance Auditor found smaller, real items. No convergent findings this round, but several individually strong ones.

- [x] [Review][Patch] **Task 3's fix didn't actually close the gap it claimed to.** `app.py`'s Stage 10 preview re-filtered `params` but still called bare `auto_select_models`, which never replicates `run_all_applicable`'s council-override insert (`if mapped and mapped not in models_to_run: models_to_run.insert(0, mapped)`) — so the preview could still name a different algorithm set than what actually runs, via the exact class of bug this task claimed to close, just from an untouched cause.
- [x] [Review][Patch] **`pipeline/__init__.py` didn't re-export `filter_confident_params`**, even though `app.py`'s import was updated in the same diff — `from pipeline import filter_confident_params` would `ImportError`, an inconsistent public surface for a function billed as "the single, reusable confidence-gate filter."
- [x] [Review][Patch] **`derive_cross_paper_parameters()`'s LLM-derived params can lack a `confidence` field** (its prompt only says "same format as input," never explicitly requesting one) — under the new allow-list gate, a derived value silently loses to the confidence gate for an unrelated prompt-schema reason, even when computed from two high-confidence source values.
- [x] [Review][Patch] **`_sample()`'s guard docstring overclaimed "fail loudly."** Every `_sample()` call happens inside `run_monte_carlo`, itself invoked through `run_all_applicable`'s generic `try/except Exception`, so a triggered guard is caught and reduced to a per-model `{"error": ...}` entry — visible in `algorithm_results`, but not a hard failure the way "fail loudly" implies.
- [x] [Review][Patch] `filter_confident_params` could silently double-iterate (and get the `excluded` half wrong) if ever called with a one-shot iterator instead of a list — cheap, harmless robustness fix, no real call site currently triggers it.
- [x] [Review][Patch] **No test proved the Stage 10 preview and the actual `sim_results['models_run']` stay in sync** — the specific behavior Task 3 claims to fix had zero automated coverage.
- [x] [Review][Patch] **`test_all_low_confidence_does_not_crash` (and similarly-named tests) only passed because every test used `council_decision={}`**, which always defaults `selected_model` to `"monte_carlo"` and force-inserts it — none of the original tests actually exercised `auto_select_models`' own heuristics on sparse/empty input without that override masking the result.
- [x] [Review][Defer] `excluded_low_confidence` is computed and returned in the results dict (satisfying AC #2's literal text) but is never read or rendered anywhere a user would see it — `app.py`'s results view and `doc_generator.py`'s report builder don't reference it. Deferred — wiring it into the UI/report is a legitimate follow-up, but a separate, larger scope than "surface it in the results dict."
- [x] [Review][Defer] `doc_generator.py`'s `"**Parameters:** {len(params)}"` report line uses the pre-filter count, which now overstates how much data actually informed the simulation numbers reported alongside it. Deferred — a real report-accuracy gap this story's semantic change exposes, but fixing it requires threading the filtered/excluded counts into `doc_generator.py`'s report-building interface, a separate change.
- [x] [Review][Defer] Stage 9's `council_select_model` still reasons over unfiltered `params`, so the council can recommend a model for reasons (e.g. multiple risk ratios) that don't survive the confidence gate by the time it actually runs. Deferred — already explicitly scoped out in this story's own Dev Notes (AD-6 binds `param_extractor.py`→`simulation_engine.py`, not `llm_council.py`); re-raised by Blind Hunter but not a new finding.
- [x] [Review][Defer] `sufficiency`/`coverage_score` (used by `auto_select_models`' bootstrap-fallback threshold) is computed pre-filter and goes stale once params are confidence-gated — only the `score` half of the `score < 5 or len(any_params) < 5` condition is stale; `any_params` already correctly reflects the filtered count in both the real run and the preview. Deferred — fixing the `score` half would require an expensive LLM re-computation of sufficiency post-filter, not justified for a secondary fallback-trigger condition.
- [x] [Review][Defer] No distinction/logging between "the LLM said low confidence" and "the confidence field was simply missing from the response" when a param is excluded. Deferred — matches Epic 2's already-established "no logging convention exists yet" pattern; not specific to this story.
- [x] [Review][Dismiss] "`filter_confident_params` does two independent passes instead of a single-pass partition." No correctness risk — the two conditions (`in (...)` / `not in (...)`) are exact logical complements, guaranteeing an exhaustive, disjoint partition regardless of pass count. Pure style preference with no established single-pass convention elsewhere in this codebase.
- [x] [Review][Dismiss] "An all-low-confidence run's progress message could read confusingly (e.g. implying 0 algorithms)." Verified against the actual code: `auto_select_models` always includes `"tornado"` unconditionally, so the real message would read "Running 1 algorithms: tornado" (or "2... tornado, bootstrap" per the sparse-data fallback) — never "0". The underlying "could be clearer" observation has some truth but is cosmetic and unsubstantiated as stated.

**Post-review suite:** 132/132 tests passing (was 128; +4 new: preview/actual-run consistency including the council-override path, `auto_select_models`' own heuristics without an override masking them; existing production code hardened with a shared `resolve_models_to_run()` helper, a `pipeline/__init__.py` export, a `derive_cross_paper_parameters()` confidence default, an iterator-safety guard, and a corrected `_sample()` guard docstring).

## Dev Notes

- **This is the first of two Epic 3 stories, both under AD-6** (3.1 confidence gating — this story; 3.2 random-effects pooling — replaces the `combined_risk *= _sample(rp)` direct-multiplication loop in `run_monte_carlo`). **Do not touch the pooling/multiplication logic in this story** — Task 1/2's filter changes what data *reaches* that loop (only confidence-gated risk ratios now), not *how* the loop combines them. Story 3.2 owns the "how".
- **Why filtering once at `run_simulation()` is correct, not a shortcut**: `_by_cat()` and the ad-hoc `[p for p in params if p.get("value") is not None]` patterns are already scattered across all 7 `run_*` functions for *other* purposes (category selection, value-presence checks) — adding a *second*, separate confidence check inside each of them would be redundant, error-prone (easy to miss one function, as this exact bug class already exists in this codebase's history per the `# B<N> fix` comments), and harder to verify complete. One upstream filter, verified once, is both correct and simpler to audit.
- **The `app.py` fix (Task 3) was found by re-reading the actual call site, not assumed** — `epics.md`'s Story 3.1 text doesn't mention `app.py` at all, and AD-6's binding list only names `param_extractor.py`/`simulation_engine.py`. This is exactly the kind of "epics.md's stated scope was incomplete" gap this project's stories have repeatedly found by reading the real code (Stories 1.2, 2.1, 2.2 all hit the same pattern) — flagging it explicitly here rather than silently expanding scope without explanation.
- **`filter_confident_params()` runs twice per simulation** — once in `app.py`'s Stage 10 preview (Task 3), once again inside `run_simulation()` itself (Task 2). This is intentional, not an oversight: the alternative (computing it once in `app.py` and threading the result into both `auto_select_models` and `run_simulation`) would change `run_simulation`'s signature and couple it to caller-side filtering, weakening its "safe to call directly" guarantee. The filter is cheap (a single list comprehension over params), so the duplication costs nothing meaningful.
- **`_sample()`'s new `raise ValueError`, under this story's design, should never fire in the normal running app** — every param reaching `run_monte_carlo` (the only caller of `_sample`) is already confidence-gated by `run_simulation`. If a test or a future code change *does* trigger it, that's the guard doing its job (a bypass was introduced), not a bug in this story.

### Current State of `simulation_engine.py` (file being modified — read in full)

```python
def _sample(p: dict, n: int = N_SIM) -> np.ndarray:      # ← Task 1: add the raise-if-disallowed guard here
    val = float(p.get("value", 0) or 0)
    lo  = p.get("ci_lower")
    hi  = p.get("ci_upper")
    if lo is not None and hi is not None:
        std = max((float(hi) - float(lo)) / 3.92, 1e-6)
        s   = np.random.normal(val, std, n)
    else:
        std = abs(val) * 0.20 if val else 0.01
        s   = np.random.normal(val, std, n)
    return np.clip(s, 0, 100 if p.get("unit") == "percent" else None)

# ... run_monte_carlo, run_markov, run_survival_analysis, run_bayesian_network,
#     run_bootstrap, run_tornado, run_hybrid -- ALL UNCHANGED, all receive
#     `params` as an argument from run_all_applicable, never filter by
#     confidence themselves today, and won't need to after this story either.

def auto_select_models(params: list, sufficiency: dict) -> list:    # ← unchanged; called with
    ...                                                              #    already-filtered params
                                                                       #    from both call sites (Task 2, 3)

def run_all_applicable(params: list, council_decision: dict, sufficiency: dict) -> dict:  # ← unchanged
    ...

def run_simulation(params: list, council_decision: dict, sufficiency: dict = None) -> dict:  # ← Task 2
    """Main dispatcher — runs all applicable algorithms."""
    return run_all_applicable(params, council_decision, sufficiency or {})
```

### Current State of `app.py`'s Stage 10 call site (file being modified — read in full)

```python
from pipeline.simulation_engine import run_simulation, auto_select_models   # ← Task 3: add filter_confident_params

# ... (Stage 9: council_select_model(params, sufficiency, context, client) — NOT touched, see Task 3 note) ...

# Stage 10: Multi-algorithm simulation
models_auto = auto_select_models(params, sufficiency)                        # ← Task 3: filter params first
cupd(f"Stage 10 — Running {len(models_auto)} algorithms: {', '.join(models_auto)}…", 57)
sim_results = run_simulation(params, model_council, sufficiency)             # ← unchanged call; filters internally (Task 2)
```

### Project Structure Notes

- Two files touched: `pipeline/simulation_engine.py` (new helper + guard + `run_simulation` update), `app.py` (one import line + two lines at the Stage 10 call site).
- Aligns with AD-1 — no new imports beyond what's already present (`numpy`/`scipy` already imported in `simulation_engine.py`; `app.py` already imports from `pipeline.simulation_engine`, just adding one more name to that existing import).
- `run_simulation`'s public signature is unchanged (`run_simulation(params: list, council_decision: dict, sufficiency: dict = None) -> dict`); its return dict gains one new key (`excluded_low_confidence`), which is additive and doesn't break any existing consumer that only reads known keys.

### Testing Standards

- Continues the established convention: stdlib `unittest`, `tests/` directory. This story creates the first test file for `simulation_engine.py` — scoped to the confidence-gate behavior added here, not a general-purpose test suite for all 7 simulation algorithms' internal math (out of scope).
- No mocking needed beyond plain parameter-dict fixtures — `simulation_engine.py` has no external API/LLM calls, only `numpy`/`scipy` computation, so tests can call the real functions directly with small hand-built `params` lists.

### References

- [Source: `_bmad-output/planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md#AD-6` — binding, rationale, and the exact confidence-gate rule]
- [Source: `_bmad-output/planning-artifacts/epics.md#Epic-3-Story-3.1`]
- [Source: `pipeline/simulation_engine.py` — full file read, current implementation of all 7 algorithms, `_sample`, `_by_cat`, `auto_select_models`, `run_all_applicable`, `run_simulation`]
- [Source: `app.py` lines 523, 1411-1423 — the Stage 9/10 call sites, confirming `auto_select_models` is called twice (once directly for a progress message, once implicitly inside `run_simulation`) with what was, before this story, the same unfiltered `params` both times]
- [Source: `pipeline/param_extractor.py`'s `PARAM_EXTRACTION_PROMPT` — confirms the LLM is asked for exactly `"confidence": "high|medium|low"`, lowercase, informing the strict-literal-match design decision in Task 4's tests]

## Change Log

- 2026-08-05: `pipeline/simulation_engine.py` — added `filter_confident_params()` (single, shared confidence-gate choke point per AD-6) and wired it into `run_simulation()`, the module's sole entry point, so all 7 algorithms are automatically confidence-gated with no per-function changes; the excluded params are surfaced via a new `excluded_low_confidence` key in the results dict. Added a defensive `raise ValueError` guard inside `_sample()` itself (AD-6 names it directly), which should never fire in normal operation since every param reaching it is already pre-filtered. `app.py` — imports `filter_confident_params` and applies it before the Stage 10 progress-preview `auto_select_models` call, so the displayed "Running N algorithms" message can't diverge from what `run_simulation()` actually runs. Added `tests/test_simulation_confidence_gate.py` (11 tests, first test coverage for this module).
- 2026-08-05 (code review pass): extracted `resolve_models_to_run()` (the auto-select-plus-council-override logic, previously inline in `run_all_applicable`) and used it in both `run_all_applicable` and `app.py`'s Stage 10 preview, closing a gap where the preview could still diverge from the actual run via the council-override path Task 3's original fix missed. Exported `filter_confident_params`/`resolve_models_to_run` from `pipeline/__init__.py` for a consistent public surface. `pipeline/param_extractor.py`'s `derive_cross_paper_parameters()` now defaults a missing `confidence` field to `"medium"` (a computed combination of real extracted values, not an invented guess), preventing the new confidence gate from silently starving the simulation of legitimate cross-paper-derived data due to an unrelated prompt-schema gap. Hardened `filter_confident_params` against a one-shot iterator input. Corrected `_sample()`'s guard docstring to accurately describe it surfacing as a per-model error rather than "failing loudly." Added 4 more tests. Final: 132/132 passing.

## Dev Agent Record

### Agent Model Used

Claude (BMAD dev-story workflow)

### Debug Log References

- RED confirmed: `tests/test_simulation_confidence_gate.py` failed with `ImportError: cannot import name 'filter_confident_params'` before Task 1.
- One test-design correction made during RED, before finalizing: the original plan for the risk-pooling test compared the *mean* of `risk_adjusted_outcome` between a low- and high-confidence odds-ratio scenario. Tracing `run_monte_carlo`'s actual math showed `adjusted = base * combined_risk / mean(combined_risk)` — normalizing by the risk factor's own mean means the *mean* of the adjusted output is ~invariant to which odds-ratio value was used, regardless of filtering; comparing means would have been a non-discriminating (always-passing) test. Rewrote it as a structural assertion instead: with the only `odds_ratio` param excluded (low-confidence), `risk_p` is empty, so `"risk_adjusted_outcome"` (only ever added when `risk_p` is non-empty) must be absent from `scenario_results`; with a high-confidence one present, the key must appear. Deterministic, not statistical — no flakiness risk.
- Full suite: `uv run --python 3.11 --with openai --with pdfplumber --with PyMuPDF --with numpy --with scipy --with reportlab --with requests --with tenacity python -m unittest discover -s tests -v` → 128/128 pass (was 117 before this story).
- `py_compile` clean on `pipeline/simulation_engine.py` and `app.py`; `import pipeline; import utils.database` smoke test clean.
- Code review (3-layer, all completed): Acceptance Auditor found zero spec violations. Blind Hunter found the most substantial issues of any story this epic, including a sharp, correct critique that Task 3's own fix hadn't fully closed the gap it claimed to (the council-override path was never previewed). 6 patches applied (one — the iterator-safety guard — was pre-applied inline before formal triage), 5 deferred, 2 dismissed (one after empirically verifying the underlying claim was inaccurate). Post-review suite: 132/132 pass.
- Two of my own test assumptions were wrong and caught by actually running the tests, not just reasoning about them: `auto_select_models([], {})` returns `["tornado", "bootstrap"]`, not `["tornado"]` alone — the sparse-data bootstrap-fallback threshold (`len(any_params) < 5`) fires for any input under 5 params, including zero. Fixed both new tests to match actual behavior rather than my initial assumption.

### Completion Notes List

- All 4 tasks complete; 11 new tests in `tests/test_simulation_confidence_gate.py`; 128/128 suite passing.
- Confirmed via full-file read that only `run_monte_carlo` calls `_sample()` (4 call sites) — every other of the 7 algorithms reads `p.get("value")` directly, so filtering once at `run_simulation()` genuinely gates all 7 with zero per-algorithm changes, exactly as the story's design point claimed.
- The `app.py` fix (Task 3) was a real gap found by reading the actual call site during story creation, not invented scope — `app.py` called `auto_select_models` twice (once directly for a progress message, once inside `run_simulation`) against what was, before this story, identically unfiltered `params` both times.
- `council_decision={}` (used throughout the test suite) already defaults to selecting `"monte_carlo"` via `final.get("selected_model", "monte_carlo")`, so no explicit council-override setup was needed to reach the Monte Carlo path in tests — simpler than the story's suggested "≥3 params + explicit council override" setup, and equally valid.
- This story sets up Story 3.2 (random-effects pooling) to have an easier job: since `run_monte_carlo` now only ever receives confidence-gated risk ratios (via the same upstream filter), Story 3.2's pooling replacement doesn't need to reason about confidence at all — that's already handled.
- Code review found a real gap in this story's own Task 3: the "fix" only re-filtered `params` before the preview call, but never accounted for `run_all_applicable`'s separate council-override insertion logic — so the preview could still diverge from the real run through a path Task 3 didn't touch. Fixed by extracting the shared `resolve_models_to_run()` helper so preview and reality are now structurally guaranteed to agree (same function, same inputs), not just coincidentally aligned.
- `derive_cross_paper_parameters()`'s missing-confidence-defaults-to-"medium" fix is outside `simulation_engine.py` (it's in `param_extractor.py`) but directly required to make this story's own confidence gate behave correctly for a real, existing feature (cross-paper derivation) — a good example of a fix genuinely required by this story's change, even though it lands in a file AD-6's binding list doesn't explicitly name.

### File List

- Modified: `pipeline/simulation_engine.py`
- Modified: `pipeline/param_extractor.py`
- Modified: `pipeline/__init__.py`
- Modified: `app.py`
- Modified: `tests/test_simulation_confidence_gate.py`
