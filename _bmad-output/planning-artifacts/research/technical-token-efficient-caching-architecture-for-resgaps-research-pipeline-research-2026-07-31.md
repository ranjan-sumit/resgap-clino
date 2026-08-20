---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments: ['C:\Users\Divya\Downloads\research_gap_final_report_final.html']
workflowType: 'research'
lastStep: 6
research_type: 'technical'
research_topic: 'Soundness of ResGap''s paper-to-hypothesis pipeline: cross-paper correlation/topic discovery and computational-modelling validation, plus supporting caching architecture'
research_goals: 'Acting as an NLP/LLM + computational-modelling expert, verify whether ResGap''s current architecture (LLM-wiki paper extraction to knowledge graph to cross-paper discovery/correlation to gap detection to parameter extraction to simulation/computational modelling) is a logically sound method for reliably surfacing important, unexplored, correlated research topics from uploaded papers and validating them computationally against the papers'' own data. Identify weaknesses in that reasoning chain. Secondarily, identify content-addressed caching patterns (wiki pages, reference metadata, gap validations) to cut redundant LLM/API calls across runs without undermining the core logic.'
user_name: 'Divya'
date: '2026-07-31'
web_research_enabled: true
source_verification: true
---

# Is ResGap's Pipeline Logic Sound? A Verified Technical Audit of the Paper-to-Hypothesis Chain

**Date:** 2026-07-31
**Author:** Divya
**Research Type:** technical

---

## Research Overview

This research began as a question about token-efficient caching, then sharpened into a deeper one once a real generated report (`research_gap_final_report_final.html`) was supplied as evidence: **does ResGap's pipeline — LLM-wiki extraction → knowledge graph → cross-paper correlation → gap detection → parameter extraction → computational-modelling simulation — actually produce sound, trustworthy findings, or does it only look like it does?**

Rather than research this in the abstract, every claim below was checked against ResGap's actual source code, and two of the most consequential findings (the academic-search rate-limit failure and the arXiv query-construction bug) were **empirically reproduced live** during this research, not inferred. Six confirmed defects were found, spanning from a serious scientific-validity problem in the computational-modelling stage down to a fixable API-integration bug. Full findings, source-cited technology research, and a phased implementation roadmap follow below; the synthesis and final recommendations are in the closing section.

---

## Technical Research Scope Confirmation

**Research Topic:** Soundness of ResGap's paper-to-hypothesis pipeline: cross-paper correlation/topic discovery and computational-modelling validation, plus supporting caching architecture

**Research Goals:** Acting as an NLP/LLM + computational-modelling expert, verify whether ResGap's current architecture (LLM-wiki paper extraction → knowledge graph → cross-paper discovery/correlation → gap detection → parameter extraction → simulation/computational modelling) is a logically sound method for reliably surfacing important, unexplored, correlated research topics from uploaded papers and validating them computationally against the papers' own data. Identify weaknesses in that reasoning chain. Secondarily, identify content-addressed caching patterns to cut redundant LLM/API calls without undermining the core logic.

**Technical Research Scope:**

- Architecture Analysis — design patterns, frameworks, system architecture
- Implementation Approaches — development methodologies, coding patterns
- Technology Stack — languages, frameworks, tools, platforms
- Integration Patterns — APIs, protocols, interoperability
- Performance Considerations — scalability, optimization, patterns

**Research Methodology:**

- Current web data with rigorous source verification
- Multi-source validation for critical technical claims
- Confidence level framework for uncertain information
- Comprehensive technical coverage with architecture-specific insights

**Scope Confirmed:** 2026-07-31

---

## Preliminary Verified Findings (Empirical + Code Verification, pre-web-research)

Before web research began, direct code inspection of the repository plus live testing of the external APIs it depends on produced the following **confirmed** findings, which anchor the rest of this research:

1. **Naive cross-paper risk pooling** (`pipeline/simulation_engine.py:93`) — `run_monte_carlo` multiplies odds/relative/hazard ratios extracted from different papers together as independent risk factors, with no meta-analytic pooling (no fixed/random-effects model, no heterogeneity/I² check). Produces a statistically meaningless but confident-looking 95% CI.
2. **Unfiltered LLM-invented parameters** (`pipeline/param_extractor.py:17`) — the extraction prompt explicitly converts vague language ("majority of patients" → 60) into point estimates tagged `confidence: low`, but nothing downstream (`simulation_engine.py:36`, `_sample()`) filters on that tag before simulation; a fabricated ±20%-of-value spread is applied when no real CI exists.
3. **Academic-search validation is currently blind** (`pipeline/academic_search.py:18`) — live-tested during this research: Semantic Scholar's unauthenticated public API returned HTTP 429 on first call and again on a retry 3 seconds later. `_search_semantic_scholar` swallows all exceptions into `[]`, so a rate-limit failure is indistinguishable from "genuinely no related work exists" — directly explaining why the sample report showed "No relevant papers found" for all 5 gaps.
4. **arXiv fallback query is malformed** (`pipeline/academic_search.py:46`) — live-tested: an unquoted multi-word `all:` field query is parsed by arXiv as an OR across individual words, not a topical phrase; reproduced irrelevant results (a Mendelian-Randomization/ADHD query returned a CMB-polarisation paper).
5. **Knowledge-graph fallback conflates failure causes and undersells itself** (`pipeline/graph_builder.py:330`) — the fallback triggers identically whether the LLM found nothing or the underlying `chat()` call itself failed/timed out; the fallback graph it substitutes contains only paper→field "mentions" edges (not the richer extends/contradicts/compared_with relations), yet report text describes this as producing "no usable entities."
6. **No cross-run caching** (`utils/database.py:33`) — no content-addressed table for wiki pages, enriched references, or gap validations; every run re-spends LLM tokens and re-calls external APIs even for previously-seen papers, compounding finding #3's rate-limit exposure.

---

## Technology Stack Analysis

_Categories adapted from the standard template to fit this research: this is not a "pick a tech stack" comparison but a soundness/fix analysis for an existing Python/Streamlit codebase. Generic categories that don't apply (IDEs, CDN/edge computing, serverless platforms) are omitted rather than padded._

### Statistical Pooling Methods (replaces "Programming Languages")

ResGap's `simulation_engine.py` currently pools odds/relative/hazard ratios from different papers via direct multiplication of Monte Carlo samples — no meta-analytic model. Verified alternative: **random-effects meta-analysis** (DerSimonian and Laird method) is the standard approach for combining effect sizes across heterogeneous studies — it explicitly models between-study variance (heterogeneity) rather than assuming one shared "true" effect, and produces wider, more honest confidence intervals than naive pooling. Fixed-effect pooling is only valid when studies are assumed to estimate the same true effect — not the case across independently-designed papers on different populations, which is ResGap's actual situation.

_Ecosystem note: Python meta-analysis tooling is less mature than R's `metafor` package (still considered the reference implementation), but Python implementations of the DerSimonian-Laird random-effects model exist and are usable with `scipy`/`numpy`, which ResGap already depends on — no new heavy dependency required._

_Source: [Meta-analysis using Python: a hands-on tutorial (BMC Medical Research Methodology)](https://bmcmedresmethodol.biomedcentral.com/articles/10.1186/s12874-022-01673-y)_
_Source: [A comparison of seven random-effects models for meta-analyses that estimate the summary odds ratio (PMC)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5841569/)_

### Cross-Paper Discovery Method (replaces "Development Frameworks")

ResGap's `discovery_engine.py` combination logic ("Paper A shows X in population P, Paper B shows biomarker B, combination: test X stratified by B") is a real, named, 39-year-old research method: **Literature-Based Discovery (LBD)**, specifically **Swanson's ABC model** (Swanson, 1986) — A relates to B, B relates to C, therefore A may relate to C, searching for bridging ("b-term") concepts. Swanson's original method found the Raynaud's disease/fish-oil connection this way, later confirmed by clinical trial. This is genuinely reassuring: ResGap's core "find what no single paper said" idea is not an LLM improvisation, it's implementing a validated methodology — but classic LBD is rigorous specifically about the b-term bridging step (formal co-occurrence/statistical validation of the bridge), whereas `discovery_engine.py`'s `COMBINATION_PROMPT` asks an LLM to freely judge "why nobody has done this" and assign `evidence_strength`/`feasibility` without the structured bridging-term validation classical LBD relies on. The core idea is sound; the current implementation skips LBD's most rigorous part.

_Source: [Literature Based Discovery (LBD): Towards Hypothesis Generation (arXiv)](https://arxiv.org/pdf/2310.03766)_
_Source: [Using Concepts in Literature-Based Discovery: Simulating Swanson's Raynaud–Fish Oil Discovery](https://www.researchgate.net/publication/227507140_Using_Concepts_in_Literature-Based_Discovery_Simulating_Swanson's_Raynaud-Fish_Oil_and_Migraine-Magnesium_Discoveries)_

### External API Resilience (replaces "Database and Storage Technologies" for this subtopic)

Confirms and explains finding #3 from the preliminary verification: **unauthenticated Semantic Scholar API calls share one public rate-limit pool across all unauthenticated users worldwide** (reported as 1000 req/s shared pool / 5,000 requests per 5 minutes shared quota). An individual free API key changes this to a **dedicated, guaranteed 1 request/second** for that key alone — not shared with unrelated traffic. This is the direct, verified fix: ResGap's `academic_search.py` and `reference_extractor.py` currently call the API key-less, so they're at the mercy of however much of the shared pool other unrelated users have already consumed — explaining why the very first live call in this research returned 429. Registering a free Semantic Scholar API key and passing it via the `x-api-key` header is a low-effort, verified fix for finding #3, separate from any query-construction fix needed for the arXiv fallback.

_Source: [s2-folks API Release Notes (Semantic Scholar / AllenAI GitHub)](https://github.com/allenai/s2-folks/blob/main/API_RELEASE_NOTES.md)_
_Source: [Semantic Scholar API Tutorial](https://www.semanticscholar.org/product/api/tutorial)_

### Caching Architecture (replaces "Cloud Infrastructure")

Confirms finding #6 is a known, named gap, not a novel problem: the standard pattern for this exact situation (skip re-calling an LLM/API for something already processed) is **content-hash-keyed exact-match caching** — hash the identifying content (paper text / DOI / normalized reference title / gap fingerprint), check a key-value store before calling the LLM/API, write the result back keyed by that hash. This is described in current practice as checking the cache "at the very start... before any agent is created, so a cache hit costs nothing beyond a single SQLite query" — which maps directly onto ResGap's existing SQLite dependency: no new database technology is needed, only new **tables** (content-hash-keyed `wiki_pages`, `references`, `gap_validations`) alongside the existing `runs`/`papers` tables in `utils/database.py`.

_Source: [Caching for LLMs: Prompt, Semantic, and Invalidation](https://mbrenndoerfer.com/writing/caching-prompt-semantic-invalidation-hit-rates-llm)_
_Source: [SQLite as an MCP context saver: stop cramming raw API data into your LLM (DEV Community)](https://dev.to/richardbaxter/sqlite-as-an-mcp-context-saver-stop-cramming-raw-api-data-into-your-llm-2oj4)_

### Technology Adoption Notes

No migration/adoption trend analysis applies here — this is an internal architecture correction on an existing small codebase, not a stack-selection decision between competing ecosystems.

## Integration Patterns Analysis

_Categories adapted again: ResGap is a single-process Streamlit monolith calling external HTTP APIs directly — microservices patterns (service mesh, saga, message brokers, API gateways, CQRS) don't apply and are omitted. What applies is: how to wrap existing call sites with caching and resilience without restructuring the app._

### Cache-Aside Pattern (replaces "API Design Patterns")

The standard pattern for exactly ResGap's caching gap (finding #6) is **cache-aside** ("lazy loading"): application code checks the cache first; on a hit, return immediately with zero LLM/API cost; on a miss, do the real work, then write the result back keyed by content hash. This wraps cleanly around ResGap's existing call sites without restructuring the pipeline: `compile_wiki_page()` checks a `wiki_pages` table keyed by paper content-hash before calling `chat_json()`; `enrich_reference()` checks a `references` table keyed by DOI/arXiv-id/normalized-title before hitting Semantic Scholar/CrossRef/etc.; `_assess_coverage()` checks a `gap_validations` table keyed by a gap-title+description hash. One documented caveat directly relevant here: on cache invalidation, **delete** the stale key rather than overwriting it, to avoid a race where a concurrent reader gets a half-written value — low risk for ResGap's single-user Streamlit session model, but worth keeping as an invariant if concurrent runs are ever supported.

_Source: [Cache-Aside Pattern (GeeksforGeeks)](https://www.geeksforgeeks.org/system-design/cache-aside-pattern/)_
_Source: [Building Resilient REST API Integrations: Cache-Aside, Stale Fallback, and Background Refresh](https://medium.com/@oshiryaeva/building-resilient-rest-api-integrations-cache-aside-stale-fallback-and-background-refresh-9028e5497dfb)_

### Retry / Backoff Resilience (replaces "Communication Protocols")

This directly targets findings #3 and #4. ResGap's `utils/azure_client.py` already has manual retry-with-backoff for LLM calls, but `pipeline/academic_search.py`'s `_search_semantic_scholar`/`_search_arxiv` and `pipeline/reference_extractor.py`'s API lookup functions have **no retry at all** — a single 429 or transient network error is caught and silently converted to an empty list on the first attempt. The verified standard fix is the **`tenacity`** library: a decorator-based retry with exponential backoff + jitter (waiting `2^x * multiplier` seconds between attempts, randomized to avoid synchronized retry storms), which would let a single transient 429 self-recover on retry instead of immediately reporting "no relevant papers found." For a fully rate-limit-exhausted state (not transient), pairing this with a **circuit breaker** (e.g. `pybreaker`) would stop hammering an already-429ing endpoint after a threshold, rather than retrying every gap validation call into the same wall.

_Source: [GitHub - jd/tenacity: Retrying library for Python](https://github.com/jd/tenacity)_
_Source: [Resilient APIs: Retry Logic, Circuit Breakers, and Fallback Mechanisms](https://medium.com/@fahimad/resilient-apis-retry-logic-circuit-breakers-and-fallback-mechanisms-cfd37f523f43)_

### API Key Management (replaces "Integration Security Patterns")

Directly closes finding #3's root cause: register a free Semantic Scholar API key and pass it via the `x-api-key` header on every request in `academic_search.py` and `reference_extractor.py`. This moves those calls off the shared unauthenticated pool onto a dedicated per-key quota (verified in Step 2 research). Store the key the same way the existing NVIDIA NIM key is handled in `utils/azure_client.py` (user-supplied, not hardcoded) — no new secret-management pattern needed beyond what already exists in the app.

### Not Applicable

REST vs. GraphQL vs. gRPC, message queues, service discovery, and API gateways do not apply — ResGap has one process making outbound HTTP calls to third-party read-only APIs; there is no inbound API surface or service-to-service boundary to design.

## Architectural Patterns and Design

_Categories adapted a third time: cloud-native/edge/deployment-ops/SOLID-for-microservices content is dropped as not applicable to a single-process research tool. What's relevant is the shape of the pipeline itself and how it should carry data and errors between stages._

### System Architecture Pattern: Medallion (Bronze/Silver/Gold) for the LLM Wiki

ResGap's own docstring calls `wiki_compiler.py` the "Karpathy Pattern," but structurally what it needs is the well-established **medallion (multi-hop) architecture** from data engineering: **Bronze** = raw parsed PDF text (already persisted implicitly, never re-parsed), **Silver** = the compiled wiki page — cleaned, schema-conformed, deduplicated, and (per this research) content-hash **cached so it is computed once per paper, ever** — and **Gold** = knowledge graph + gaps + proposals, business-ready outputs that can be recomputed cheaply from Silver without re-touching Bronze or re-calling the LLM on raw text. The core benefit directly answers the "how do we cache references and collect only what's needed" question from earlier: teams (or in this case, pipeline stages) can iterate on Silver/Gold transformations without re-ingesting Bronze, because each layer's completeness is guaranteed independent of the layers above it. This reframes the fix from "add some caching" to "give the wiki a real persistent Silver layer" — which is what the content-hash `wiki_pages`/`references` tables from Steps 2–3 actually are.

_Source: [What is the medallion lakehouse architecture? (Databricks)](https://www.databricks.com/blog/what-is-medallion-architecture)_
_Source: [Medallion Architecture: Bronze, Silver & Gold Layers Explained](https://dataforest.ai/blog/medallion-architecture)_

### Design Principle: Explicit Result Types Instead of Sentinel Strings

This directly targets finding #5 (and the underlying pattern behind finding #3 and the swallowed-error design flagged in `project-context.md`). ResGap's `chat()` returns a plain string for both success and failure (`"[API error after N attempt(s): ...]"` on failure) — a documented **sentinel value anti-pattern**: using an ordinary value to signal an exceptional case is fragile because the sentinel can collide with or be indistinguishable from real data, which is exactly why `graph_builder.py` cannot currently tell "the LLM said there are no entities" apart from "the API call itself failed." The verified alternative is an explicit **Result type** (`Success[T]` / `Failure[E]`, sometimes called Railway-Oriented Programming) — a small, non-invasive wrapper that forces every call site to explicitly branch on success vs. failure rather than silently treating a failure string as valid content. This is a scoped fix to `utils/azure_client.py`'s `chat()`/`chat_json()` return type, not a rewrite of the pipeline.

_Source: [Python exceptions considered an anti-pattern](https://sobolevn.me/2019/02/python-exceptions-considered-an-antipattern)_
_Source: [Sentinel value (Wikipedia) — the semipredicate problem](https://en.wikipedia.org/wiki/Sentinel_value)_

### Data Architecture: Confidence/Provenance Propagation

This directly targets findings #1 and #2 — the most serious ones. The verified pattern for pipelines that mix measured and estimated/derived values is to treat uncertainty as **first-class metadata that propagates through every stage**, not something computed once at extraction and then discarded. Concretely for ResGap: `param_extractor.py` already tags each value `confidence: high|medium|low` and `is_derived: true/false` — the architecture gap is that `simulation_engine.py` never reads those fields; a provenance-aware design would have `_sample()` branch on confidence (e.g., exclude or down-weight `low`-confidence linguistic-conversion values, or visibly separate them in output) and would refuse to naively multiply `is_derived` cross-paper values as if they were independently measured — pairing directly with the random-effects pooling model from Step 2.

_Source: [Uncertainty Quantification and Data Provenance for Data Pipeline Security Analysis](https://vtechworks.lib.vt.edu/items/db2245aa-e52c-4bb3-a7da-f94dffc5638b)_
_Source: [Risks of ignoring uncertainty propagation in AI-augmented pipelines](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12747714/)_

### Not Applicable

Cloud-native/edge deployment, container orchestration, and distributed-consensus scalability patterns don't apply — this is a single-user Streamlit tool with a local SQLite file, not a distributed system under load.

## Implementation Approaches and Technology Adoption

_Categories adapted a final time: this is a solo-maintained hobby/research project (no team, no CI, no existing test suite — confirmed in `project-context.md`), so team-organization and DevOps/CI content is dropped in favor of a rollout order and risk framing that fits a single developer touching a working app._

### Adoption Strategy: Strangler Fig, Not Big-Bang

Verified pattern for exactly this situation — modernizing a live, working system piece by piece rather than a risky full rewrite: the **strangler fig pattern**. Applied here, the six confirmed findings can each be "strangled" independently without touching the others: (1) add the cache-aside tables and check-before-call guards first — purely additive, zero behavior change on cache miss, lowest risk; (2) add the Semantic Scholar API key and `tenacity` retry — isolated to `academic_search.py`/`reference_extractor.py`; (3) add the explicit Result type to `chat()`/`chat_json()` — touches the most call sites, so do it third once the lower-risk wins are banked, updating callers incrementally; (4) add confidence-gating and real pooling to `simulation_engine.py`/`param_extractor.py` last, since it changes output *values*, not just performance, and deserves the most scrutiny.

_Source: [Strangler Fig Pattern (Azure Architecture Center)](https://learn.microsoft.com/en-us/azure/architecture/patterns/strangler-fig)_
_Source: [How the Strangler Fig Pattern Enables Safe and Gradual Refactoring](https://www.gocodeo.com/post/how-the-strangler-fig-pattern-enables-safe-and-gradual-refactoring)_

### Testing Strategy

`project-context.md` already confirmed no test suite exists anywhere in the repo. Recommendation is not "add full test coverage" (out of scope, no team to maintain it) but **targeted regression tests for exactly the four fixes above** — e.g., a test asserting `_sample()` excludes/flags `confidence: low` params, a test asserting the Result type distinguishes a real empty-entities response from a simulated API failure, and a recorded-fixture test for `_search_arxiv`'s query construction (so the OR-vs-phrase bug found in this research can't silently return).

### Cost/Token Optimization

This is the direct payoff of the caching architecture (Steps 2–4): once `wiki_pages`/`references`/`gap_validations` are content-hash cached, re-uploading an overlapping corpus (common in practice — foundational papers get cited across many different research areas) turns what is currently a full LLM-wiki-compile + full reference-enrichment + full gap-validation run into a cache-hit lookup for every previously-seen paper/reference/gap, with new LLM/API spend limited to genuinely new content only.

### Risk Assessment

The most important non-technical risk: fixing findings #1/#2 (real pooling, confidence-gating) will very likely make future reports look *less* impressive on the surface — fewer "high confidence" gaps, wider/more honest confidence intervals, some previously-invented numbers no longer appearing. That is the correct outcome of the fix, not a regression, and should be communicated to any report audience as "this version is more rigorous," not silently.

## Technical Research Recommendations

### Implementation Roadmap

1. Cache-aside tables (`wiki_pages`, `references`, `gap_validations`) — additive, no behavior change.
2. Semantic Scholar API key + `tenacity` retry/backoff on all academic-API calls.
3. Explicit Result type for `chat()`/`chat_json()`, migrated call site by call site.
4. Confidence-gating in `_sample()` + random-effects pooling for cross-paper risk ratios in `simulation_engine.py`.

### Technology Stack Recommendations

No new infrastructure: existing SQLite gains tables (not a new database); existing `scipy`/`numpy` gain a random-effects pooling function (not a new heavy dependency); add two small, well-established libraries — `tenacity` (retry) and optionally `pybreaker` (circuit breaker) — plus a free Semantic Scholar API key (no cost).

### Skill Development Requirements

None beyond what's already reflected in this codebase (Python, Streamlit, basic stats) — the random-effects pooling and Result-type patterns are well-documented, narrow additions, not new-paradigm learning.

### Success Metrics and KPIs

- Cache hit rate on wiki/reference/gap-validation lookups across runs with overlapping papers (should rise from 0%, the current state, toward meaningful reuse).
- Academic-search validation calls returning a real status (found/not-found) vs. the current silent-429-as-"not-found" — trackable by logging raw HTTP status separately from "genuinely searched, found nothing."
- Simulation outputs showing wider, heterogeneity-aware confidence intervals for any cross-paper-pooled parameter, and visibly excluding or flagging low-confidence linguistic-conversion values.

## Technical Research Synthesis and Conclusion

_This closing section is intentionally a synthesis, not a repeat of the sections above at greater length — every claim here is already sourced in the sections preceding it. Generic report sections with no applicable content for this project (Security/Compliance/Regulatory frameworks, Competitive Technical Advantage, 5-year technology outlook, team skill-development plans) are omitted rather than padded, consistent with every prior step in this document._

### Executive Summary

ResGap's pipeline borrows two real, credible ideas — Karpathy's "LLM Wiki" (compile once, don't re-derive via RAG) and a Swanson-style Literature-Based-Discovery cross-paper correlation method — but the current implementation only partially realizes either, and the computational-modelling stage that turns findings into numbers has a genuine scientific-validity problem, not just a performance one. Of the six confirmed findings, two (naive cross-paper risk pooling, unfiltered LLM-invented parameters) threaten the trustworthiness of any output claiming numerical rigor; two (the Semantic Scholar 429, the arXiv query bug) were **live-reproduced during this research** and explain, mechanistically, why the sample report showed "no relevant papers found" for all 5 gaps; the remaining two (knowledge-graph fallback mischaracterization, absent caching) are real but lower-severity. None of the fixes require new infrastructure or a rewrite — every recommended change is additive or narrowly scoped to an existing file.

**Key Findings:**

1. `simulation_engine.py` multiplies risk ratios from different papers with no meta-analytic pooling — false statistical precision (most severe).
2. `param_extractor.py` converts vague language into invented numbers with no downstream confidence gate before simulation.
3. Semantic Scholar's unauthenticated API is rate-limited in practice (live-confirmed, 429 on first call and retry) — the gap-validation step is currently blind, not selective.
4. The arXiv fallback query is parsed as an OR-of-words by arXiv's API (live-confirmed) — noisy, off-topic results.
5. The knowledge-graph fallback conflates "LLM found nothing" with "the API call itself failed," and undersells the real (if shallow) fallback graph it produces.
6. No content-addressed caching exists anywhere — every run re-spends tokens/API calls on previously-seen papers, references, and gap validations.

**Recommendations:** (full roadmap in Step 5 above)

1. Add cache-aside tables (`wiki_pages`, `references`, `gap_validations`) — additive, zero behavior change.
2. Add a free Semantic Scholar API key + `tenacity` retry/backoff to all academic-API calls.
3. Replace the `chat()`/`chat_json()` sentinel-error-string with an explicit Result type.
4. Add confidence-gating to `_sample()` and real random-effects pooling to cross-paper risk-ratio combination.

### Research Methodology and Source Verification

- **Primary evidence**: direct reading of `pipeline/simulation_engine.py`, `param_extractor.py`, `academic_search.py`, `graph_builder.py`, `wiki_compiler.py`, `reference_extractor.py`, `llm_council.py`, `discovery_engine.py`, `utils/database.py`, and the user-supplied real report `research_gap_final_report_final.html`.
- **Empirical verification**: live HTTP calls to `api.semanticscholar.org` (429 confirmed twice) and `export.arxiv.org` (200, but topically diffuse results confirmed) during this research session.
- **Web research**: 10 search queries across meta-analysis methodology, literature-based discovery, API rate-limit documentation, caching patterns, resilience patterns, error-handling design patterns, data-provenance patterns, and incremental-refactoring patterns — all cited inline in Steps 2–5 above.
- **Confidence levels**: all six findings are rated **confirmed** (direct code inspection and/or live reproduction), not inferred from general knowledge.

### Next Steps

Per BMAD flow, this research document is the grounding input for **`bmad-architecture`** — the next step is to turn the four-item roadmap above into the project's architecture spine (the invariants: caching key strategy, Result-type contract, pooling-model choice, confidence-gating rule) before implementation begins.

---

**Technical Research Completion Date:** 2026-07-31
**Confidence Level:** High — six of six findings independently confirmed via direct code inspection and/or live empirical testing, not inference.

<!-- Content will be appended sequentially through research workflow steps -->
