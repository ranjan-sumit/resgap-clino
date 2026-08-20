---
id: SPEC-resgap-pipeline-fixes
companions: ['../../planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md', '../../project-context.md']
sources: ['../../planning-artifacts/research/technical-token-efficient-caching-architecture-for-resgaps-research-pipeline-research-2026-07-31.md']
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# ResGap Pipeline Soundness & Caching Fixes

## Why

Pain-to-solve, and a mandate to meet before further work continues: ResGap's paper-to-hypothesis pipeline produces gap-detection and computational-modelling output that *looks* rigorous but currently is not. Direct code inspection and live-reproduced testing confirmed six concrete defects — naive cross-paper statistical pooling, LLM-invented numbers flowing unfiltered into simulation, a rate-limited academic-validation step that silently reports "no relevant papers found" regardless of whether that's true, a malformed arXiv fallback query, a knowledge-graph fallback that can't tell "no data" from "the call broke," and no caching, so every run re-spends tokens on previously-seen papers. This affects the tool's owner/user directly: any report generated today cannot be trusted at face value. The architecture spine (`ARCHITECTURE-SPINE.md`) already fixed the invariants; this SPEC is the build contract derived from it.

## Capabilities

- **CAP-1** — Content-addressed caching layer
  - **intent:** The pipeline can skip re-calling the LLM or an external API for a paper, reference, parameter-set, or gap it has already resolved in a prior run.
  - **success:** Re-uploading a previously-processed paper, or processing a reference already enriched in a prior run, produces a cache hit — no corresponding LLM/API call is made — rather than a full recompute.

- **CAP-2** — Resilient, correctly-scoped academic-API validation
  - **intent:** A user can trust a gap's open/partial/solved validation status as a genuine search result, not a silently-swallowed API failure.
  - **success:** A 429 response from Semantic Scholar triggers a visible retry rather than an immediate silent "no relevant papers found." An arXiv query for a well-covered topic (e.g. "Mendelian Randomization ADHD") returns topically relevant results, not off-topic noise.

- **CAP-3** — Explicit success/failure signaling at the LLM boundary
  - **intent:** A pipeline stage can distinguish "the LLM genuinely returned no data" from "the LLM call itself failed," and react differently to each.
  - **success:** Forcing an LLM call to fail (e.g. invalid API key) produces a distinct, visible failure state at the calling stage, rather than silently degrading through the same fallback path used for genuine empty extraction.

- **CAP-4** — Confidence-gated, properly-pooled computational modelling
  - **intent:** A simulated risk/outcome estimate reflects real measured data with statistically valid cross-study pooling, not LLM-invented numbers or naive multiplication of unrelated studies' ratios.
  - **success:** A parameter tagged `confidence: low` is excluded from simulation and listed separately. Cross-paper odds-ratio combination produces a random-effects pooled estimate with an appropriately wider confidence interval, not the naive-multiplication result.

## Constraints

- Must not restructure the existing pipes-and-filters pipeline (`app.py` orchestrating dict-in/dict-out `pipeline/*.py` filters) — all four capabilities wrap around it (AD-1).
- Cache keys must include domain scoping — for domain-conditioned stages only (wiki pages, gap validations) — plus a stage-logic version tag, so a future prompt or query change invalidates only what it affects (AD-3). Content-hash-only keys are ruled out.
- The Result-type fix (CAP-3) is scoped to the LLM client boundary only, not propagated through every pipeline stage (AD-4). A pipeline-wide Result-typed rewrite is ruled out.
- No new infrastructure or database technology: SQLite gains tables only, the pooling model is hand-built on the existing scipy/numpy pins, and the only new package is `tenacity`. Introducing Redis, a new database, or a new heavy statistics library is ruled out.

## Non-goals

- Circuit breaker (`pybreaker`) integration on external API calls.
- Result-type propagation beyond the LLM client boundary.
- Concurrent/multi-user access to the SQLite cache.
- Any deployment, infrastructure, or hosting change.
- A cache eviction/retention policy.

## Success signal

Re-running ResGap on an overlapping paper corpus costs meaningfully fewer LLM/API calls than the first run, with cache hits directly observable. A generated report's validation section and simulation numbers can be trusted at face value, without requiring the kind of manual live API testing this project needed to uncover their current unreliability.
