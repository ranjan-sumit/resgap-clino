---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: ['_bmad-output/specs/spec-resgap-pipeline-fixes/SPEC.md', '_bmad-output/planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md', '_bmad-output/project-context.md']
---

# Research_Gap_Analyzer - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for Research_Gap_Analyzer's pipeline-soundness and caching fixes, decomposing `SPEC-resgap-pipeline-fixes` (capabilities/constraints) and `ARCHITECTURE-SPINE.md` (AD-1…AD-7) into implementable stories. No PRD.md or UX design contract exists for this project — `SPEC.md` and `ARCHITECTURE-SPINE.md` are the FR/NFR and technical-requirements sources of record.

## Requirements Inventory

### Functional Requirements

FR1: The pipeline can skip re-calling the LLM or an external API for a paper, reference, parameter-set, or gap already resolved in a prior run. (CAP-1)
FR2: A user can trust a gap's open/partial/solved validation status as a genuine search result, not a silently-swallowed API failure. (CAP-2)
FR3: A pipeline stage can distinguish "the LLM genuinely returned no data" from "the LLM call itself failed," and react differently to each. (CAP-3)
FR4: A simulated risk/outcome estimate reflects real measured data with statistically valid cross-study pooling, not LLM-invented numbers or naive multiplication of unrelated studies' ratios. (CAP-4)

### NonFunctional Requirements

NFR1: Must not restructure the existing pipes-and-filters pipeline (`app.py` orchestrating dict-in/dict-out `pipeline/*.py` filters) — fixes wrap around it, never replace it.
NFR2: Cache keys must include domain scoping for domain-conditioned stages only (wiki pages, gap validations), plus a stage-logic version tag — content-hash-only keys are insufficient.
NFR3: The Result-type fix is scoped to the LLM client boundary only (`utils/azure_client.py`), not propagated through every pipeline stage.
NFR4: No new infrastructure or database technology — SQLite gains tables only, the pooling model is hand-built on existing scipy/numpy pins, and `tenacity` is the only new package.

### Additional Requirements

- AD-1: `utils/*.py` must never import `pipeline/*.py` or `app.py` (dependency direction is a hard rule, not just convention).
- AD-2: Cache-aside check-before-call required on `wiki_compiler.compile_wiki_page`, `param_extractor.extract_parameters` (per-paper call), `reference_extractor.enrich_reference`, `academic_search._assess_coverage`. A filter that catches `LLMCallError` and falls back to a degraded result must never cache that fallback.
- AD-3: Cache key format is the colon-joined string `content_hash:domain_hash:stage_logic_version`, SHA-256 throughout; `domain_hash` is SHA-256 of canonical (`sort_keys=True`) JSON of the relevant `domain_config` subset, or the literal `none` for domain-invariant stages (references, parameters).
- AD-4: `chat()`, `chat_json()`, and `vision()` in `utils/azure_client.py` all return `Result[str, ErrorInfo]`; every direct caller unwraps immediately and raises `LLMCallError` on `Failure`.
- AD-5: `academic_search.py` and `reference_extractor.py` HTTP calls must call `resp.raise_for_status()` (or equivalent) on non-2xx before `tenacity` retry is added — retry logic alone does nothing if nothing raises. Semantic Scholar calls carry a free API key (user-supplied, stored the same way the existing NVIDIA NIM key is handled).
- AD-6: `pipeline/pooling.py` is a new module implementing random-effects (DerSimonian–Laird) pooling on `scipy`/`numpy` primitives; `simulation_engine._sample()` excludes any parameter where `confidence == "low"`.
- AD-7: `academic_search._search_arxiv` must group query terms as a quoted phrase or explicit `AND`, not raw space-separated words under a bare `all:` prefix.
- No starter template applies — this is brownfield work on an already-running Python 3.11 / Streamlit app; no scaffolding step is needed.
- New dependency: `tenacity` 9.1.4 (verified current, requires Python ≥3.10 — compatible).

### UX Design Requirements

Not applicable — no UX design contract exists for this project, and none of the four capabilities change user-facing UI/interaction design (they change data correctness and internal resilience behind the existing Streamlit UI).

### FR Coverage Map

FR1: Epic 2 - caching skips re-fetching a previously-processed paper/reference
FR2: Epic 2 - gap validation status is a real search result, not a swallowed API failure
FR3: Epic 1 - a pipeline stage can distinguish genuine-empty from call-failed
FR4: Epic 3 - simulated estimates use properly-pooled, confidence-gated real data
NFR1: Epic 1 & Epic 2 & Epic 3 - all three wrap the existing pipes-and-filters pipeline, none restructure it
NFR2: Epic 2 - cache-key domain/version scoping
NFR3: Epic 1 - Result-type fix scoped to the LLM client boundary only
NFR4: Epic 2 & Epic 3 - no new infrastructure beyond `tenacity`; pooling hand-built on existing scipy/numpy

## Epic List

### Epic 1: Honest Failure Signaling
Users can trust that when a pipeline stage's report shows a "no data" result, it's genuine — not a swallowed API/LLM failure wearing the same face.
**FRs covered:** FR3, NFR3
**Additional Requirements covered:** AD-1, AD-4
**Files:** `utils/azure_client.py`, `graph_builder.py`

### Epic 2: Cached & Resilient Academic Data Pipeline
Users get faster, cheaper re-runs on overlapping papers, and a gap's validation status is a real search result, not a silently-failed rate-limited call.
**FRs covered:** FR1, FR2, NFR2, NFR4
**Additional Requirements covered:** AD-2, AD-3, AD-5, AD-7
**Files:** `academic_search.py`, `reference_extractor.py`, `wiki_compiler.py`, `param_extractor.py`, `utils/database.py`
**Depends on:** Epic 1 (uses `LLMCallError` for the never-cache-a-failure rule)

### Epic 3: Statistically Valid Computational Modelling
Users get simulated risk/outcome numbers built on real, properly-pooled data — not LLM-invented estimates or naively multiplied ratios.
**FRs covered:** FR4
**Additional Requirements covered:** AD-6
**Files:** `pipeline/pooling.py` (new), `simulation_engine.py`
**Depends on:** none — independent of Epic 1 and Epic 2

---

## Epic 1: Honest Failure Signaling

Users can trust that when a pipeline stage's report shows a "no data" result, it's genuine — not a swallowed API/LLM failure wearing the same face.

### Story 1.1: Typed success/failure result from LLM calls

As a ResGap user,
I want the LLM client to clearly signal whether a call succeeded or failed,
So that pipeline stages never mistake a failed call for real content.

**Acceptance Criteria:**

**Given** a successful `chat()`/`chat_json()`/`vision()` call
**When** the response streams back normally
**Then** the method returns `Success(value)` wrapping the real content

**Given** a call that exhausts its retries (timeout, rate limit, or API error)
**When** the failure is final
**Then** the method returns `Failure(error)` with `error.kind` set to `timeout`|`rate_limit`|`api_error` and `error.detail` containing the underlying message
**And** it never returns a plain string standing in for the error

### Story 1.2: Callers raise a distinct exception on LLM failure

As a ResGap user,
I want every direct caller of `chat()`/`chat_json()`/`vision()` to react explicitly to a `Failure` result,
So that a call failure can't silently propagate downstream as if it were content.

**Acceptance Criteria:**

**Given** Story 1.1's Result type exists
**When** a direct caller (e.g. `graph_builder.extract_entities_and_relations`) receives `Success`
**Then** it proceeds exactly as before, unwrapping `.value`

**Given** a direct caller receives `Failure`
**When** it processes the result
**Then** it raises `LLMCallError` (carrying the `ErrorInfo`) rather than continuing with the error string as if it were content
**And** this applies to every direct caller of `chat`/`chat_json`/`vision` across the codebase, not only `graph_builder.py`

### Story 1.3: Knowledge-graph fallback only triggers on genuine empty extraction

As a ResGap user,
I want the knowledge-graph fallback to only apply when the LLM genuinely found no entities,
So that a report's "fallback used" diagnostic means what it says instead of also covering silent API failures.

**Acceptance Criteria:**

**Given** Story 1.2's `LLMCallError` exists
**When** `build_knowledge_graph` calls `extract_entities_and_relations` and it raises `LLMCallError`
**Then** `build_knowledge_graph` catches it distinctly and records `diagnostics.fallback_reason` as `"LLM call failed: {detail}"` — not the current generic "LLM graph extraction returned no entities"

**Given** `extract_entities_and_relations` returns `Success` with a parsed but empty entities list
**When** `build_knowledge_graph` evaluates the result
**Then** it still falls back to `_fallback_graph_from_wiki` as today, with `fallback_reason` unchanged ("LLM graph extraction returned no entities")
**And** in both cases the correct, distinct diagnostic reason is what ends up in any generated report

---

## Epic 2: Cached & Resilient Academic Data Pipeline

Users get faster, cheaper re-runs on overlapping papers, and a gap's validation status is a real search result, not a silently-failed rate-limited call.

### Story 2.1: Cache compiled wiki pages

As a ResGap user,
I want a paper's compiled wiki page to be cached,
So that re-analyzing a previously-uploaded paper doesn't re-spend an LLM call.

**Acceptance Criteria:**

**Given** `utils/database.py`
**When** this story ships
**Then** a new `wiki_pages` table exists with columns `cache_key` (PK), `content_hash`, `domain_hash`, `stage_logic_version`, `wiki_json`

**Given** `compile_wiki_page` is called for a paper
**When** a matching `cache_key` (`content_hash:domain_hash:stage_logic_version`, SHA-256, `domain_hash` from canonical JSON of the relevant `domain_config` subset) already has a row
**Then** the cached `wiki_json` is returned and no `chat_json` call is made

**Given** no matching `cache_key` exists
**When** `compile_wiki_page` completes with a `Success` result (per Epic 1)
**Then** the result is written to the cache before being returned
**And** a `Failure`/`LLMCallError` path is never cached

### Story 2.2: Cache extracted parameters

As a ResGap user,
I want a paper's extracted quantitative parameters to be cached,
So that re-analyzing a previously-uploaded paper doesn't re-spend the parameter-extraction LLM call.

**Acceptance Criteria:**

**Given** `utils/database.py`
**When** this story ships
**Then** a new `parameters` table exists with columns `cache_key` (PK), `content_hash`, `stage_logic_version`, `params_json` — no `domain_hash`, since parameter extraction is domain-invariant per AD-3

**Given** `extract_parameters` processes a paper
**When** a matching `cache_key` already has a row
**Then** the cached `params_json` is returned for that paper and no `chat_json` call is made

**Given** no matching `cache_key` exists
**When** extraction completes with a `Success` result
**Then** the result is cached
**And** a `Failure` path is never cached

### Story 2.3: Cache enriched reference metadata

As a ResGap user,
I want enriched reference metadata (from Semantic Scholar/CrossRef/etc.) to be cached,
So that a reference cited across multiple uploaded corpora isn't re-fetched from external APIs every run.

**Acceptance Criteria:**

**Given** `utils/database.py`
**When** this story ships
**Then** a new `references` table exists with columns `cache_key` (PK), `doi_or_title_hash`, `stage_logic_version`, `enriched_json`

**Given** `enrich_reference` is called for a reference
**When** a matching `cache_key` already has a row
**Then** the cached `enriched_json` is returned and no external API call is made

**Given** no cached entry exists
**When** enrichment completes
**Then** the result is cached keyed by DOI hash if a DOI was resolved, else by normalized-title hash

### Story 2.4: Cache gap validation results

As a ResGap user,
I want a gap's academic-search validation result to be cached,
So that re-validating the same gap under the same domain doesn't re-spend the search/LLM assessment calls.

**Acceptance Criteria:**

**Given** `utils/database.py`
**When** this story ships
**Then** a new `gap_validations` table exists with columns `cache_key` (PK), `gap_hash`, `domain_hash`, `stage_logic_version`, `validation_json`

**Given** `_assess_coverage` is called for a gap
**When** a matching `cache_key` already has a row
**Then** the cached `validation_json` (status + reasoning) is returned and no search/LLM calls are made

**Given** no cached entry exists
**When** validation completes with a `Success` result
**Then** it is cached
**And** a `Failure` path is never cached

### Story 2.5: Academic-API calls raise on failure and retry

As a ResGap user,
I want Semantic Scholar and arXiv search calls to actually retry on a rate-limit or transient failure,
So that a gap isn't wrongly marked "no relevant papers found" because of a 429.

**Acceptance Criteria:**

**Given** `_search_semantic_scholar` and `_search_arxiv` currently return `[]` silently on any non-200 response
**When** this story ships
**Then** both raise on a non-2xx response (`resp.raise_for_status()`) instead of silently falling through

**Given** a raised exception from a non-2xx response
**When** the call is made
**Then** it is wrapped in a `tenacity` retry with exponential backoff and jitter, retrying before finally falling back to an empty result

**Given** a Semantic Scholar call
**When** it is made
**Then** it includes a user-supplied API key header (stored the same way the existing NVIDIA NIM key is handled), not an unauthenticated request

### Story 2.6: Correct arXiv query construction

As a ResGap user,
I want the arXiv fallback search to match the actual topic of a gap,
So that validation results aren't polluted by off-topic papers matched on a single shared word.

**Acceptance Criteria:**

**Given** `_search_arxiv` currently builds an unquoted, space-separated `all:` query
**When** this story ships
**Then** the query groups the gap's search terms as a quoted phrase or explicit `AND`-joined terms

**Given** a known multi-concept gap query (e.g. "Mendelian Randomization ADHD brain structure")
**When** searched
**Then** returned results are topically related to the combined concept, not matched on any single word in isolation

---

## Epic 3: Statistically Valid Computational Modelling

Users get simulated risk/outcome numbers built on real, properly-pooled data — not LLM-invented estimates or naively multiplied ratios.

### Story 3.1: Exclude low-confidence parameters from simulation

As a ResGap user,
I want low-confidence, LLM-invented parameter estimates excluded from computational modelling,
So that simulated numbers aren't built on invented data.

**Acceptance Criteria:**

**Given** a set of extracted parameters with mixed confidence levels
**When** `simulation_engine._sample()` (and the callers that select parameters for simulation) run
**Then** only parameters with `confidence` in `{medium, high}` are included in the simulation

**Given** parameters with `confidence == "low"` exist
**When** simulation results are produced
**Then** those excluded parameters are listed separately (e.g. `excluded_low_confidence` in the results dict) rather than silently dropped or silently included

### Story 3.2: Random-effects pooling for cross-paper risk ratios

As a ResGap user,
I want risk ratios from different papers combined using proper statistical pooling,
So that a combined estimate reflects real between-study uncertainty instead of false precision.

**Acceptance Criteria:**

**Given** odds/relative/hazard ratios extracted from two or more different papers
**When** `run_monte_carlo` currently combines them (`combined_risk *= _sample(rp)` loop)
**Then** this direct multiplication is replaced with a call to a new `pipeline/pooling.py` function implementing random-effects (DerSimonian–Laird) pooling

**Given** the same set of heterogeneous risk ratios
**When** pooled via the new function versus the old direct-multiplication method
**Then** the pooled result's 95% CI is wider (reflecting between-study heterogeneity), demonstrating the fix is actually in effect

**Given** `pipeline/pooling.py`
**When** this story ships
**Then** it has its own targeted unit test(s) covering the pooling calculation in isolation, independent of the full simulation pipeline
