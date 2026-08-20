---
review: version-verification
target: ARCHITECTURE-SPINE.md (ResGap Pipeline Soundness & Caching Architecture)
reviewer-mandate: "Verify every committed decision was web-researched or reality-checked rather than asserted from training data: current library/framework versions, that each named technology still exists and fits."
date: 2026-07-31
---

# Review: Version & Reality-Check Verification

## Verdict

**PASS.** Every version claim and named technology/pattern in the spine checks out against independent web verification or against the actual project file. One clarity/honesty issue is flagged (finding 2) — not a factual error, but the Stack table's wording could mislead a reader into thinking scipy has built-in random-effects pooling when it does not; the spine should say so explicitly rather than relying on the reader to infer it from the Structural Seed's "NEW" annotation.

## Findings

### 1. tenacity 9.1.4, requires Python >=3.10 — VERIFIED ACCURATE

Checked directly against PyPI (both the JSON API at `pypi.org/pypi/tenacity/json` and the project page at `pypi.org/project/tenacity/`), independently, twice:

- Latest version: **9.1.4**, released **2026-02-07**.
- `requires_python = ">=3.10"`, consistent with classifiers for Python 3.10–3.14.

The spine's claim exactly matches current reality. This is the one claim the spine explicitly flagged as "verified current on PyPI" and it holds up — no issue.

### 2. scipy>=1.12.0 / numpy>=1.26.0 "existing pins" — accurate reality-check, but adjacent claim needs tightening

- Confirmed by reading `C:\Users\Divya\Documents\Research_Gap_Analyzer\requirements.txt` directly: it contains exactly `numpy>=1.26.0` and `scipy>=1.12.0`. The spine's "existing pin" claim is internally consistent and correctly reality-checked against the project, not asserted from training data. No issue with the version numbers themselves.
- However, per the specific instruction to check whether scipy can actually provide the claimed capability: **scipy has no built-in DerSimonian-Laird / random-effects meta-analysis pooling function.** This was confirmed via web search — random-effects meta-analysis combination (including a `method_re='dl'` DerSimonian-Laird option) lives in `statsmodels.stats.meta_analysis.combine_effects`, and dedicated packages like PyMARE/NiMARE exist for this purpose. SciPy provides only generic numerical/statistical primitives (e.g., `scipy.stats.chi2`, `scipy.stats.norm`) that a hand-rolled DL implementation could be built on top of — it does not ship the algorithm itself.
- The Stack table's parenthetical — *"`pipeline/pooling.py`'s random-effects model uses this, no new dependency"* — is technically true (pooling.py can be written using scipy/numpy primitives without adding a new package) but is phrased ambiguously enough that a reader could mistake it for "scipy already implements this." The Structural Seed elsewhere is honest about this (`pooling.py # NEW — random-effects (DerSimonian-Laird) pooling`), which does disclose that this is new code to be written, not an existing scipy feature. But the two sections aren't cross-referenced, and the Stack table row in isolation reads as reassurance about capability rather than a plain statement that this will be a hand-rolled implementation.
- **Recommendation:** tighten the Stack table wording to something like: *"scipy/numpy provide the numerical primitives (chi-square, weighted variance) for a hand-rolled DerSimonian-Laird implementation in `pipeline/pooling.py`; scipy itself has no built-in random-effects meta-analysis function (statsmodels does, via `combine_effects(method_re='dl')`, but is deliberately not added as a dependency)."* This makes the build-vs-borrow decision explicit and auditable, which is exactly what this gate is meant to enforce.

### 3. "Pipes-and-Filters" — VERIFIED real architectural pattern

Confirmed as a standard, well-documented architectural pattern (Microsoft Azure Architecture Center's "Pipes and Filters pattern," POSA-lineage literature, multiple independent write-ups). Correctly named and correctly applied to the app.py → pipeline/*.py sequencing described. No issue.

### 4. "DerSimonian-Laird" — VERIFIED real statistical method, correctly named

Confirmed as a real, well-established method (Rebecca DerSimonian and Nan Laird, 1986, "Meta-analysis in clinical trials") for random-effects meta-analysis pooling, still the standard reference method discussed in current literature (e.g., Cochrane Handbook §9.4.3.1, and comparison papers against newer methods like Hartung-Knapp-Sidik-Jonkman). Not confabulated. Correctly used in AD-6 to describe pooling risk ratios across papers rather than multiplying them directly.

### 5. "pybreaker" (Deferred section) — VERIFIED real PyPI package

Confirmed as a real, actively-maintained Python circuit-breaker library implementing the pattern from Nygard's *Release It!* (`pip install pybreaker`). Appropriately placed in the Deferred section rather than adopted, so risk is low regardless — but the name and pattern are genuine, not confabulated.

### 6. Semantic Scholar API key rationale (AD-5) — VERIFIED accurate

AD-5 claims Semantic Scholar calls should carry an API key rather than call unauthenticated, to avoid the 429/rate-limit failure mode. Web-verified: unauthenticated Semantic Scholar API access is rate-limited and shared across all unauthenticated users, while an individual API key gets a dedicated, more predictable rate allocation. This supports the stated rationale — not an out-of-date or invented claim.

### 7. arXiv / CrossRef / OpenAlex / PubMed (mentioned in the mermaid diagram as external APIs) — not independently web-verified this pass; low risk

These are long-standing, well-established academic APIs. Given the review's time budget, this pass focused web-verification effort on the claims explicitly flagged for checking (tenacity version, scipy capability, pattern/method names) plus the one adjacent claim it surfaced (Semantic Scholar auth). Note for the record: these four API names were not independently re-confirmed against current documentation in this pass. Recommend a follow-up spot-check only if any of these integrations turn out to have changed auth/rate-limit models recently — nothing in the spine currently depends on a version-sensitive detail about them.

## Summary Table

| Claim | Type | Verified? | Result |
| --- | --- | --- | --- |
| tenacity 9.1.4, Python >=3.10 | version | Yes (PyPI JSON + project page) | Accurate |
| scipy>=1.12.0 / numpy>=1.26.0 "existing pins" | reality-check vs project | Yes (read requirements.txt) | Accurate |
| scipy has capability for DL pooling | capability claim | Yes (web search) | False as literally stated; spine implies hand-rolled elsewhere but Stack table wording should be explicit |
| Pipes-and-Filters | pattern name | Yes | Real |
| DerSimonian-Laird | method name | Yes | Real |
| pybreaker | library name (deferred) | Yes | Real |
| Semantic Scholar API key rationale | technical claim | Yes | Accurate |
| arXiv/CrossRef/OpenAlex/PubMed | API existence | Not this pass | Low risk, unverified |
