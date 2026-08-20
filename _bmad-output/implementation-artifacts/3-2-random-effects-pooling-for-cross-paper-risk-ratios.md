---
baseline_commit: 2c1746580cfd244d9d943e92552593a3d466e610
---

# Story 3.2: Random-effects pooling for cross-paper risk ratios

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a ResGap user,
I want risk ratios from different papers combined using proper statistical pooling,
so that a combined estimate reflects real between-study uncertainty instead of false precision.

## Acceptance Criteria

1. **Given** odds/relative/hazard ratios extracted from two or more different papers, **When** `run_monte_carlo` currently combines them (`combined_risk *= _sample(rp)` loop), **Then** this direct multiplication is replaced with a call to a new `pipeline/pooling.py` function implementing random-effects (DerSimonian–Laird) pooling.
2. **Given** the same set of heterogeneous risk ratios, **When** pooled via the new function versus the old direct-multiplication method, **Then** the pooled result's 95% CI is wider (reflecting between-study heterogeneity), demonstrating the fix is actually in effect.
3. **Given** `pipeline/pooling.py`, **When** this story ships, **Then** it has its own targeted unit test(s) covering the pooling calculation in isolation, independent of the full simulation pipeline.

## Tasks / Subtasks

- [x] Task 1: Implement DerSimonian-Laird pooling in a new `pipeline/pooling.py` (AC: #1, #3)
  - [x] **The formula, verified against the Cochrane Handbook (9.4.3.1) and the original DerSimonian-Laird (1986) method-of-moments estimator — do not improvise this, a subtly wrong statistical formula is worse than no formula at all:**
    - Work in **log space** (ratios are approximately log-normally distributed — this is why `run_monte_carlo`'s existing risk multiplication already treats ratios multiplicatively, just incorrectly).
    - For each param `p` with `value > 0`: `y_i = ln(value)`. Variance `v_i`: if `ci_lower`/`ci_upper` are both present and both `> 0`, `se_i = (ln(ci_upper) - ln(ci_lower)) / 3.92` (the existing `/3.92` convention already used in `simulation_engine._sample`, i.e. `(hi-lo)/(2*1.96)`), `v_i = se_i²`. Otherwise, fall back to `se_i = 0.2` (matches `_sample`'s own no-CI fallback — `std = abs(val) * 0.20` on the natural scale — via the delta-method approximation `SE(ln X) ≈ SE(X)/X ≈ 0.20` for a 20% relative SE; explicitly document this as the reasoning, don't just drop a bare `0.2` in the code with no explanation).
    - Fixed-effect weights: `w_i = 1/v_i`. Fixed-effect pooled estimate: `M = Σ(w_i·y_i) / Σw_i`.
    - Cochran's Q: `Q = Σ w_i·(y_i - M)²`. Degrees of freedom: `df = k - 1` (k = number of params).
    - `C = Σw_i - (Σw_i²)/Σw_i`. **Guard `k < 2` or `C == 0` explicitly** (a single study has no estimable between-study heterogeneity — plain Python `0.0/0.0` raises `ZeroDivisionError`, so this guard is required, not just a `NaN`-avoidance nicety): `tau_squared = 0.0` in that case, else `tau_squared = max(0.0, (Q - df) / C)`.
  - [x] **Add a shared internal helper the public function AND the tests both use** — this is what makes Task 3's fixed-effect-vs-random-effects comparison a genuine proof rather than two independently-hand-rolled formulas that might silently drift apart:
    ```python
    def _pool(y_values: list, variances: list, tau_squared: float) -> tuple[float, float]:
        """Given log-scale point estimates, their variances, and a
        between-study variance (0.0 for a fixed-effect pool), returns
        (pooled_log_estimate, pooled_log_variance). Shared by
        pool_risk_ratios (tau_squared from the DL formula above) and its
        own tests (tau_squared=0.0, to compute the fixed-effect comparison
        point with the exact same weighting logic, not a re-derived one)."""
        weights = [1.0 / (v + tau_squared) for v in variances]
        pooled_estimate = sum(w * y for w, y in zip(weights, y_values)) / sum(weights)
        pooled_variance = 1.0 / sum(weights)
        return pooled_estimate, pooled_variance
    ```
    `pool_risk_ratios` calls `_pool(y_values, variances, tau_squared)` for its real (random-effects) result; Task 3's AC #2 test calls `_pool(y_values, variances, 0.0)` directly for the fixed-effect comparison point — both go through the identical weighting code, so the comparison can't pass due to a testing-side formula bug.
    - Random-effects weights: `w_i* = 1/(v_i + tau_squared)`. Pooled estimate: `y_RE = Σ(w_i*·y_i) / Σw_i*`. Variance of pooled estimate: `var_RE = 1/Σw_i*`.
    - 95% CI (log scale): `y_RE ± 1.96·sqrt(var_RE)`. Back-transform everything to the ratio scale via `exp()`.
  - [x] Public function:
    ```python
    def pool_risk_ratios(params: list) -> dict:
        """Random-effects (DerSimonian-Laird) pooling of odds/relative/hazard
        ratios, potentially from different papers (AD-6). Returns:
        {"pooled_ratio": float, "ci_lower": float, "ci_upper": float,
         "tau_squared": float, "n_studies": int, "method": "DerSimonian-Laird"}.
        A single valid ratio (n=1) has no estimable heterogeneity and
        degenerates to that study's own value/CI (tau_squared=0.0) -- the
        same interpretation as a fixed-effect model with one study.
        Raises ValueError if no param has a usable value > 0."""
    ```
    Skip (don't crash on) any param whose `value` is missing, non-numeric, or `<= 0` — log-space pooling is undefined for a non-positive ratio; a defensive skip matches this codebase's general "one bad input doesn't abort the batch" convention. If **every** param is skipped this way, raise `ValueError` (pooling zero valid ratios is a genuine caller error — the caller, `run_monte_carlo`, already only calls this when `risk_p` is non-empty per Task 2's guard, so this should never fire in the real app; same "should never happen, fail loud if it does" posture as Story 3.1's `_sample()` guard).
  - [x] `pipeline/pooling.py` is a brand-new file — start it with `import numpy as np` (needed for `sample_pooled_risk`'s `np.log`/`np.random.normal`/`np.clip`/`np.exp`; `pool_risk_ratios`/`_pool` themselves only need plain Python `math.log`/`sum`, but using `np.log` etc. consistently throughout is fine too since `numpy` is already a project dependency).
  - [x] Also add a small sampling helper in the same file, so all pooling *and* pooled-sampling math lives together (AD-6 names `pipeline/pooling.py` specifically):
    ```python
    def sample_pooled_risk(pooled: dict, n: int) -> np.ndarray:
        """Draw n samples from the pooled ratio's log-normal distribution --
        for Monte Carlo use. Clipped to [0.1, 20], matching the existing
        safety bound simulation_engine already applied to per-study risk
        samples before this story."""
        log_mean = np.log(pooled["pooled_ratio"])
        log_se = (np.log(pooled["ci_upper"]) - np.log(pooled["ci_lower"])) / 3.92
        samples = np.random.normal(log_mean, max(log_se, 1e-6), n)
        return np.clip(np.exp(samples), 0.1, 20)
    ```
- [x] Task 2: Replace `run_monte_carlo`'s multiplication loop with pooling (`pipeline/simulation_engine.py`) (AC: #1, #2)
  - [x] **This is a full replacement, not an addition** — the entire `combined_risk = np.ones(N_SIM); for rp in risk_p[:4]: combined_risk *= np.clip(_sample(rp, N_SIM), 0.1, 20)` loop is deleted, not kept alongside the new pooling call:
    ```python
    if risk_p and distributions:
        pooled = pool_risk_ratios(risk_p[:4])
        combined_risk = sample_pooled_risk(pooled, N_SIM)
        _, base = distributions[0]
        adjusted = base * combined_risk / np.maximum(np.mean(combined_risk), 1e-9)
        sr["risk_adjusted_outcome"] = _stats(adjusted)
        sr["risk_pooling"] = pooled   # surfaces pooled_ratio/CI/tau_squared/n_studies for the UI and for tests to verify AC #2 directly
    ```
  - [x] Add `from pipeline.pooling import pool_risk_ratios, sample_pooled_risk` to `simulation_engine.py`'s imports. This is `pipeline/*.py` importing another `pipeline/*.py` module — permitted under AD-1 (`pipeline/*.py` may import other `pipeline/*.py` modules; only `utils/*.py` importing `pipeline/*.py` is forbidden).
  - [x] **`_sample()` is no longer called on `risk_p` params anywhere** after this change (confirmed via full-file read: `_sample`'s only other call site, the sensitivity-correlation loop near the end of `run_monte_carlo`, iterates `outcome_p`, never `risk_p` — unaffected by this story). Do not leave the old per-study `_sample(rp, ...)` calls anywhere as dead code.
  - [x] Story 3.1's confidence gate (`filter_confident_params`, wired into `run_simulation`) already ensures every param reaching `run_monte_carlo` — including everything in `risk_p` — is medium/high confidence before this story's code ever runs. `pool_risk_ratios` does **not** need its own confidence check; that's already handled upstream. Do not duplicate it here.
- [x] Task 3: Add targeted tests (AC: #2, #3)
  - [x] New `tests/test_pooling.py` (first test file for `pipeline/pooling.py`, standalone per AC #3 — no `simulation_engine` import needed):
    - `pool_risk_ratios` on a **single** param returns that param's own value as `pooled_ratio`, its own CI as `ci_lower`/`ci_upper` (or a CI derived from the 0.2 fallback SE if it had none), and `tau_squared == 0.0`.
    - `pool_risk_ratios` on **two homogeneous** ratios (same value, same tight CI) produces `tau_squared` at or very near `0.0` (no real heterogeneity to detect) and a `pooled_ratio` close to that shared value.
    - `pool_risk_ratios` on **two heterogeneous** ratios (e.g. `value=1.5` and `value=4.0`, each with a fairly tight CI so `Q` clearly exceeds `df`) produces `tau_squared > 0`.
    - **The core AC #2 proof, done rigorously**: for the same heterogeneous input, compare the DerSimonian-Laird (random-effects) CI width against a **fixed-effect** pooling of the identical data, computed by calling Task 1's shared `_pool(y_values, variances, tau_squared=0.0)` helper directly — the *same* weighting code `pool_risk_ratios` itself uses, just with `tau_squared` forced to `0`, not a hand-rolled re-derivation that could silently drift from production code. Assert the random-effects CI is strictly wider. This is the textbook-correct way to demonstrate "reflects between-study heterogeneity" — mathematically guaranteed whenever `tau_squared > 0` (every random-effects weight `w_i* = 1/(v_i+τ²)` is strictly less than the fixed-effect weight `w_i = 1/v_i`, so the summed weight is smaller and the variance, `1/Σw_i*`, is larger) — unlike a direct comparison against the old raw-multiplication behavior, which computes a fundamentally different quantity (a compounded product of independent factors, not a pooled estimate of one effect) with no guaranteed CI-width relationship in either direction.
    - **One additional, illustrative (not strict-inequality) comparison against the literal old behavior**, to satisfy epics.md AC2's literal "versus the old direct-multiplication method" wording alongside the rigorous FE-vs-RE proof above: for the same heterogeneous `risk_p` list, run the OLD logic inline in the test (`combined_risk = np.ones(N); for rp in risk_p: combined_risk *= np.clip(_sample-equivalent-inline-normal-sample, 0.1, 20)` — reproduce the pre-Story-3.2 formula directly in the test, not by importing deleted code) and the NEW `sample_pooled_risk` output side by side; assert they differ (e.g. differing means or stds) and note in a comment that this comparison is illustrative/documentary, not a proof (the two approaches compute different quantities, as explained above) — the rigorous proof is the FE-vs-RE test.
    - `pool_risk_ratios([])` (empty list) raises `ValueError`.
    - `pool_risk_ratios` skips a param with `value <= 0` or missing `value`, without crashing, and still pools the remaining valid ones.
    - `pool_risk_ratios` where **every** param has an invalid value raises `ValueError` (not silently returns something meaningless).
    - `sample_pooled_risk` returns `n` samples, all within `[0.1, 20]`, with an empirical mean reasonably close to `pooled["pooled_ratio"]` (a loose statistical assertion — e.g. within 2x — not an exact-match assertion, since it's random sampling).
  - [x] Update `tests/test_simulation_confidence_gate.py`'s existing Monte Carlo integration test(s) (from Story 3.1) if any assumed the old multiply-per-study `risk_adjusted_outcome` behavior — re-verify `test_monte_carlo_risk_pooling_excludes_low_confidence_ratio` still passes unmodified (it only asserts presence/absence of the `risk_adjusted_outcome` key based on whether `risk_p` ends up empty or not, which is unaffected by *how* a non-empty `risk_p` gets combined — confirm this rather than assuming it).
  - [x] Add one **integration-level** test proving `run_monte_carlo`'s `risk_adjusted_outcome` output now includes the new `risk_pooling` key (with `pooled_ratio`/`ci_lower`/`ci_upper`/`tau_squared`/`n_studies`) when 2+ heterogeneous risk-ratio params are present, and that its `tau_squared` is `> 0` for genuinely heterogeneous input — a direct, end-to-end check that Task 2's wiring is actually live, not just that `pipeline/pooling.py` works in isolation.

### Review Findings

The strongest cross-layer convergence in this entire program: all three layers independently flagged the inverted/zero-width CI bug, and two of three independently flagged both the NaN/Inf gap and the uncaught-exception regression.

- [x] [Review][Patch] **`NaN`/`Infinity` values silently pass the `value <= 0` filter** — Python's `nan <= 0` and `inf <= 0` both evaluate `False`. A NaN/Inf `value` (plausible from an LLM extraction glitch) gets `np.log()`'d and poisons the whole pooled result with no error, contradicting the docstring's "usable value > 0" promise. Independently flagged by Blind Hunter and Edge Case Hunter. [pipeline/pooling.py]
- [x] [Review][Patch] **Inverted (`ci_lower > ci_upper`) or zero-width (`ci_lower == ci_upper`) CIs produce a negative or zero `se`, incorrectly floored to `1e-6` by `max(se, 1e-6) ** 2`** — giving that study near-infinite weight (near-zero variance) instead of falling back to the default or erroring. This is exactly the failure mode ("understating uncertainty") this whole story exists to prevent, now reachable via malformed input. **Independently flagged by all three review layers** — the strongest convergence signal in this program.
- [x] [Review][Patch] **`pool_risk_ratios`'s `ValueError` (when every `risk_p` entry is invalid) is uncaught in `run_monte_carlo`, discarding the *entire* Monte Carlo result** — not just the risk-adjustment piece. The old code never raised on a bad risk value (defaulted to `0` and kept sampling); a single garbage risk-ratio param used to degrade gracefully, now it can wipe out prevalence/incidence outcome results that had nothing to do with the bad risk ratios. Independently flagged by Blind Hunter and Edge Case Hunter.
- [x] [Review][Patch] `_pool()` is a public-enough (imported-by-tests) helper with no guard against an empty `variances` list — `sum(weights)` is `0.0`, causing an unhandled `ZeroDivisionError` if ever called directly with empty input.
- [x] [Review][Patch] `_pool()` has no guard against `y_values`/`variances` of mismatched length — `zip()` silently truncates to the shorter list, dropping data without warning.
- [x] [Review][Patch] **`pool_risk_ratios` hand-rolls its own fixed-effect mean (`fe_mean`) instead of calling the "shared" `_pool(y_values, variances, 0.0)`** — the module's own docstring claims `_pool` gives "the exact same weighting logic" for the AC #2 proof, but that guarantee only actually held between the *test's* FE calculation and `_pool`, not between production's *own* internal FE calculation and `_pool`. Two independent implementations of the identical formula existed in the same file.
- [x] [Review][Patch] **`sample_pooled_risk` reconstructs `log_se` by re-`log()`-ing the already-`exp()`-computed `ci_upper`/`ci_lower`**, instead of using the `se_pooled` value already computed (and discarded) inside `pool_risk_ratios`. A fragile round-trip that's only numerically exact today because the two formulas happen to be algebraic inverses — nothing enforces that invariant if either formula ever changes independently.
- [x] [Review][Patch] **Story 3.1's confidence-gate protection is silently dead for the `risk_p` code path.** Before this story, every risk-ratio param passed through `_sample()`, which has a defensive `raise` if `confidence not in ("medium","high")` (Story 3.1's belt-and-suspenders guard). This story removed all `_sample()` calls on `risk_p`, routing them through `pool_risk_ratios`/`sample_pooled_risk` instead — neither of which has any confidence check. The defensive protection Story 3.1 specifically added is now unreachable for this exact code path, with nothing replacing it.
- [x] [Review][Patch] **The deliberate scope decision to pool OR/RR/HR together as if they were repeated estimates of one effect lives only in the story's markdown file, not in `pooling.py` itself.** A future maintainer reading the module in isolation has no signal that different effect-measure types are being combined despite being only approximately interchangeable under a rare-outcome assumption.
- [x] [Review][Patch] **No plausibility bound on the pooled output** (`pooled_ratio`/`ci_lower`/`ci_upper`) before returning — an extreme individual `value` (e.g. a corrupted `1e12`) or extreme heterogeneity-driven CI blowup can silently produce `inf`/`nan`, a downstream JSON-serialization landmine (standard JSON has no `Infinity`/`NaN` literal).
- [x] [Review][Patch] **No test coverage for any of the above paths** — NaN/Inf value, reversed CI, zero-width CI, all-invalid-`risk_p` degrading gracefully through `run_monte_carlo`, or the confidence-gate skip. The 144/144-green status materially overstated how well-defended this module was against malformed real-world input.
- [x] [Review][Defer] `sample_pooled_risk`'s hard clip to `[0.1, 20]` can truncate a non-trivial fraction of the sampled distribution precisely when `tau_squared` is large — i.e. exactly the high-heterogeneity scenarios this story represents. Deferred — this exact clip bound already existed in the old (pre-Story-3.2) code; carried forward unchanged, not newly introduced. A deeper redesign (wider bounds, truncation-aware statistics) is a separate scope decision.
- [x] [Review][Defer] `risk_p[:4]`'s truncation criterion (arbitrary list order — not sorted by confidence, recency, or CI tightness) is more consequential under DL pooling than it was under independent multiplication, since which studies are included now directly changes `tau_squared` and CI width. Deferred — the `[:4]` slice itself is pre-existing, unchanged by this story; re-examining the selection criterion is a separate concern.
- [x] [Review][Dismiss] "Deletion finding: per-study `np.clip(..., 0.1, 20)` no longer applied before combining." This is an intentional, statistically-correct design change, not a regression — proper meta-analysis pools raw CI-derived variances in log space; ad-hoc per-study clipping of sampled values before pooling doesn't belong in the math (it would distort the variance estimates feeding `tau_squared`). The final *samples* are still clipped, at the correct layer (`sample_pooled_risk`, unchanged bound), preserving the original safety property where it actually belongs.

**Post-review suite:** 155/155 tests passing (was 144; +11 new covering NaN/Inf rejection, inverted/zero-width CI fallback, `_pool()`'s own empty/mismatched-length guards, the restored confidence-gate skip, and graceful degradation through `run_monte_carlo` on all-invalid risk params; production code hardened against all convergent findings above).

## Dev Notes

- **This is the final story in the whole BMAD pipeline-fixes program** — Epic 1, 2, and 3 (this story) complete the full `SPEC-resgap-pipeline-fixes` scope once this ships.
- **The DerSimonian-Laird formula in Task 1 was verified against the Cochrane Handbook (9.4.3.1, "Random-effects (DerSimonian and Laird) method") before writing this story** — this is a real, load-bearing statistical method, not a made-up placeholder calculation; a plausible-looking but subtly wrong formula (e.g. mixing up `Q`'s degrees of freedom, forgetting the `max(0, ...)` truncation, or using natural-scale instead of log-scale) would be a serious, hard-to-notice correctness bug — exactly the class of problem this whole epic exists to eliminate. Implement Task 1's formula exactly as specified; do not "simplify" or approximate it.
- **Why log-space, not natural-scale pooling**: ratios (OR/RR/HR) are bounded below by 0 and are conventionally treated as approximately log-normally distributed in the meta-analysis literature — this is *why* the pre-existing (buggy) code already worked multiplicatively rather than additively. Pooling in log space and exponentiating back is standard practice, not a stylistic choice.
- **This story replaces WHAT the old bug did (independent multiplication), not the general concept of "multiple risk factors compound multiplicatively."** If `risk_p` contains ratios that are genuinely *different, independent* risk factors (not multiple papers' estimates of the *same* effect), pooling them as if they were repeated measurements of one effect is itself a modeling simplification — but this is the same simplification the current codebase already makes implicitly (there's no `risk_factor_identity`/grouping field anywhere in the param schema to distinguish "same effect, different papers" from "different effects"), and introducing that distinction is a data-model change well beyond AD-6's stated scope ("Cross-paper combination of odds/relative/hazard ratios goes through `pipeline/pooling.py`'s... pooling function"). Do not attempt to add risk-factor grouping/identity in this story.
- **`_sample`'s existing 20%-of-value fallback and DL's 0.2-log-SE fallback are related but not identical** — `_sample`'s convention is on the *natural* scale (`std = abs(val) * 0.20`), Task 1's is on the *log* scale (`se_i = 0.2`). They're connected via the delta method (`SE(ln X) ≈ SE(X)/X`, which reduces to ≈0.20 when the natural-scale relative SE is ≈20%) — close enough to be a principled, not arbitrary, choice, but they are not the same formula reused verbatim. Don't just copy `_sample`'s natural-scale code into log space without the transformation.
- **Minor, optional optimization** (not required, mention only if convenient): `pool_risk_ratios(risk_p[:4])` is deterministic and `risk_p` doesn't vary by scenario, so calling it once before the `for scenario in scenarios:` loop and reusing the result (rather than recomputing identically on every scenario iteration) avoids redundant CPU work. Not a correctness issue either way — do this only if it doesn't complicate the diff.
- **Not in scope**: nothing else in `simulation_engine.py` changes — `run_markov`, `run_survival_analysis`, `run_bayesian_network`, `run_bootstrap`, `run_tornado`, `run_hybrid`, `auto_select_models`, `resolve_models_to_run`, `filter_confident_params` are all untouched. Only `run_monte_carlo`'s risk-combination block changes.

### Current State of `run_monte_carlo`'s risk-combination block (file being modified — read in full)

```python
def run_monte_carlo(params: list, scenarios: list) -> dict:
    _seed_rng()
    outcome_p  = _by_cat(params, "prevalence", "incidence", "proportion", "rate", "survival")
    risk_p     = _by_cat(params, "odds_ratio", "relative_risk", "hazard_ratio")
    efficacy_p = _by_cat(params, "efficacy")
    ...
    for scenario in scenarios:
        ...
        distributions = []
        for p in outcome_p[:8]:
            samples = _sample(p, N_SIM) * mod
            ...
            distributions.append((name, samples))

        if risk_p and distributions:                                     # ← Task 2: replace this whole block
            combined_risk = np.ones(N_SIM)
            for rp in risk_p[:4]:
                combined_risk *= np.clip(_sample(rp, N_SIM), 0.1, 20)     # ← THE BUG: independent multiplication
            _, base = distributions[0]
            adjusted = base * combined_risk / np.maximum(np.mean(combined_risk), 1e-9)
            sr["risk_adjusted_outcome"] = _stats(adjusted)
        ...
```

### Project Structure Notes

- One new file (`pipeline/pooling.py`), one file modified (`pipeline/simulation_engine.py`, `run_monte_carlo`'s risk block + one new import line).
- Matches the architecture spine's own Structural Seed exactly: `pipeline/pooling.py # NEW — random-effects (DerSimonian-Laird) pooling, used by simulation_engine.py`.
- Aligns with AD-1 — `simulation_engine.py` (`pipeline/*.py`) importing `pooling.py` (`pipeline/*.py`) is a permitted same-layer import, unchanged direction rule.
- `run_monte_carlo`'s public signature is unchanged (`run_monte_carlo(params: list, scenarios: list) -> dict`); its per-scenario result dict gains one new key (`risk_pooling`), additive, only present when `risk_p` is non-empty (same condition as `risk_adjusted_outcome` today).

### Testing Standards

- Continues the established convention: stdlib `unittest`, `tests/` directory, no mocking needed (pure `numpy`/`scipy` computation, same as Story 3.1's `simulation_engine` tests).
- `pipeline/pooling.py`'s tests must be genuinely independent of `simulation_engine.py` (AC #3's explicit requirement) — `tests/test_pooling.py` should only import from `pipeline.pooling`, not `pipeline.simulation_engine`.

### References

- [Source: `_bmad-output/planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md#AD-6` — binding, rationale, and the explicit `pipeline/pooling.py` file naming in the Structural Seed]
- [Source: `_bmad-output/planning-artifacts/epics.md#Epic-3-Story-3.2`]
- [Source: `pipeline/simulation_engine.py` — full file read, current `run_monte_carlo` implementation post-Story-3.1 (confidence-gating already in place upstream)]
- [Source: Cochrane Handbook 9.4.3.1, "Random-effects (DerSimonian and Laird) method for meta-analysis" (handbook-5-1.cochrane.org), web-verified 2026-08-05 — confirms the exact `tau²`/`Q`/weight formulas used in Task 1, cross-checked against a second independent source (metricgate.com's DerSimonian-Laird calculator documentation) before finalizing]
- [Source: `_bmad-output/implementation-artifacts/3-1-exclude-low-confidence-parameters-from-simulation.md` — establishes that `risk_p` reaching `run_monte_carlo` is already confidence-gated upstream, so this story's pooling function doesn't need its own confidence check]

## Change Log

- 2026-08-05: Added `pipeline/pooling.py` (new file) implementing DerSimonian-Laird random-effects pooling — `pool_risk_ratios()` (public), `_pool()` (shared internal helper used by both the real random-effects call and its own tests' fixed-effect comparison), and `sample_pooled_risk()` for drawing Monte Carlo samples from the pooled log-normal distribution. `pipeline/simulation_engine.py`'s `run_monte_carlo` — the old `combined_risk = np.ones(N_SIM); for rp in risk_p[:4]: combined_risk *= np.clip(_sample(rp, N_SIM), 0.1, 20)` loop (independent per-study sampling and multiplication) is fully replaced with a single `pool_risk_ratios`/`sample_pooled_risk` call; the per-scenario result dict gains a new `risk_pooling` key surfacing `pooled_ratio`/`ci_lower`/`ci_upper`/`tau_squared`/`n_studies`/`method`. Added `tests/test_pooling.py` (11 tests, standalone per AC #3) and one integration test in `tests/test_simulation_confidence_gate.py` proving the wiring is live end-to-end.
- 2026-08-05 (code review pass — the strongest cross-layer convergence in this program): fixed NaN/Inf values silently passing the value filter (`np.isfinite` check added). Fixed inverted/zero-width CI bounds producing a negative-or-zero `se` that got floored into a bogus near-zero variance (near-infinite weight) — now requires `hi > lo` strictly, falling back to the 0.2 default otherwise; independently flagged by all three review layers. Fixed `pool_risk_ratios`'s `ValueError` (all risk_p entries invalid) propagating uncaught through `run_monte_carlo` and discarding the entire Monte Carlo result — now caught locally, degrading to skipping just the risk-adjustment step. Hardened `_pool()` against empty and mismatched-length input. `pool_risk_ratios` now calls `_pool(..., 0.0)` for its own fixed-effect mean instead of hand-rolling a second implementation of the same formula. `sample_pooled_risk` now uses `pooled_log_estimate`/`pooled_log_se` stored directly in the pooled dict instead of a fragile CI round-trip. Restored the confidence-gate protection that was silently lost when `_sample()` calls (which had their own defensive guard) were removed from the risk_p path in the original implementation — `pool_risk_ratios` now skips non-medium/high-confidence params itself. Added an explicit scope-boundary comment in `pooling.py` about pooling OR/RR/HR together being deliberate. Clipped pooled output to a sane finite range. Added 11 more tests. Final: 155/155 passing.

## Dev Agent Record

### Agent Model Used

Claude (BMAD dev-story workflow)

### Debug Log References

- RED confirmed: `tests/test_pooling.py` failed to import (`pipeline.pooling` didn't exist) before Task 1.
- One test-fixture bug caught and fixed during RED, not a formula bug: `test_single_study_with_ci_returns_its_own_value_and_ci` originally hand-picked `value=2.0` with `ci_lower=1.5`/`ci_upper=2.7` — but `2.0` isn't the geometric mean of `1.5` and `2.7` (`sqrt(1.5×2.7) ≈ 2.0125`), so the CI wasn't internally consistent with its own point estimate in log space, and the reconstructed CI didn't exactly round-trip (off by ~0.01 at 3 decimal places). `pooled_ratio` matched exactly (confirming the formula, not the fixture, was correct). Fixed by deriving `ci_lower`/`ci_upper` as `value × exp(∓0.3)` — genuinely symmetric around `ln(value)` — so the round-trip test is mathematically exact, not approximately so.
- Full suite: `uv run --python 3.11 --with openai --with pdfplumber --with PyMuPDF --with numpy --with scipy --with reportlab --with requests --with tenacity python -m unittest discover -s tests -v` → 144/144 pass (was 132 before this story).
- `py_compile` clean on `pipeline/pooling.py` and `pipeline/simulation_engine.py`; `import pipeline; import utils.database` smoke test clean.
- The DerSimonian-Laird formula was verified against the Cochrane Handbook (9.4.3.1) during story creation, and independently re-derived from scratch by a fresh-context reviewer before implementation began, who confirmed every step correct (including the easy-to-get-wrong details: Q computed with fixed-effect weights, the `max(0, ...)` truncation, `df = k-1`, log-scale vs. natural-scale, and the `k=1` degenerate case). No formula errors were found or needed correction during implementation.
- Code review (3-layer, all completed): the strongest cross-layer convergence of this entire program. All three layers independently flagged the inverted/zero-width CI bug (negative `se` incorrectly floored into a near-zero variance, giving that study near-infinite weight — precisely the failure mode this story exists to prevent). Two of three independently flagged both the NaN/Inf gap and an uncaught-`ValueError` regression that could wipe out an entire Monte Carlo result over one bad risk parameter. 11 patches applied, 2 deferred (both pre-existing behavior carried forward unchanged, not introduced by this story), 1 dismissed (a deletion finding that was actually an intentional, statistically-correct design change, not a regression). Post-review suite: 155/155 pass.
- One design choice worth flagging: adding a confidence-gate check inside `pool_risk_ratios` itself (a review-driven fix) required updating every existing test fixture in `tests/test_pooling.py` to include a `confidence` field — the `_ratio()` helper now defaults `confidence="high"` so pre-existing tests didn't need individual changes, only the shared fixture.

### Completion Notes List

- All 3 tasks complete; 12 new tests total (11 in the new `tests/test_pooling.py`, 1 integration test in `tests/test_simulation_confidence_gate.py`); 144/144 suite passing.
- The AC #2 proof (random-effects CI wider than fixed-effect CI for the same heterogeneous data) is implemented exactly as the story specified: both computed via the same shared `_pool()` helper (`tau_squared` from the real DL formula vs. `tau_squared=0.0` forced), so the test cannot pass due to a hand-rolled, independently-drifting comparison formula — it's mathematically guaranteed whenever real heterogeneity exists (`tau_squared > 0`), not just empirically likely.
- The illustrative (non-strict-proof) comparison against the literal old multiplication behavior was also included, satisfying epics.md's literal AC2 wording alongside the rigorous FE-vs-RE proof, per the story's own Enhancement note.
- `_sample()` is confirmed to no longer be called anywhere on `risk_p` params — its only remaining call site in `run_monte_carlo` is the sensitivity-correlation loop over `outcome_p`, untouched by this story.
- This is the final story in the entire BMAD pipeline-fixes program (`SPEC-resgap-pipeline-fixes`) — Epics 1, 2, and 3 are now all complete.
- The review's 3-way convergence on the inverted-CI bug is a strong validation of this session's whole review discipline: three independently-reasoning layers (spec-compliance, adversarial, mechanical-edge-case), with no shared context, all found the exact same real bug from different angles. That's the signal this process is designed to produce.

### File List

- Added: `pipeline/pooling.py`
- Modified: `pipeline/simulation_engine.py`
- Added: `tests/test_pooling.py`
- Modified: `tests/test_simulation_confidence_gate.py`
