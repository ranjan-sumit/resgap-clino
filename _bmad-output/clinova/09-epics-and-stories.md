---
name: 'Clinova Research Intelligence Platform — Epics & Stories'
type: epics
status: draft-for-review
created: '2026-08-20'
inputDocuments: ['01-prd.md', '03-system-architecture.md', '04-ai-research-architecture.md', '05-data-architecture.md', '10-phased-implementation-plan.md']
companions: ['10-phased-implementation-plan.md']
---

# Epics & Stories — Clinova Research Intelligence Platform

## Detailing policy

Per the brief's own implementation rule (§53) — "stories must remain small enough for an AI coding agent to implement reliably" — and matching this project's own established practice (the baseline `_bmad-output/planning-artifacts/epics.md` fully detailed only its in-scope epics), **full Given/When/Then stories are written here for Phase 0 and Phase 1 only** — the "minimum first phase that improves scientific reliability without destabilizing the existing system" the brief explicitly asks this planning pass to identify (§55). Phases 2-8 are specified at epic level (goal, FRs/ADRs covered, story titles) — detailed stories for each phase are written via `bmad-create-story` immediately before that phase begins, incorporating whatever was learned in the phase before it, exactly as the baseline project's own Epic 1→2→3 sequencing already did.

---

## Phase 0 — Baseline

**Goal:** freeze current behavior, seed the evaluation benchmark, and measure the six known problems concretely — before any code changes. **No engine code changes in this phase.**

### Epic 0.1: Baseline Report & Benchmark Seed
**FRs:** none directly (evaluation infrastructure) · **Depends on:** nothing · **Files:** `evals/benchmarks/`, existing `pipeline/doc_generator.py` (read-only use)

#### Story 0.1.1: Generate a real baseline report from the existing pipeline
As a Platform Operator, I want a real report generated end-to-end from the existing (pre-Clinova) pipeline against a small real corpus, so that later phases have a measured "before" state.

**AC:**
- **Given** the existing pipeline and a small sample corpus (3-5 open-access papers in the project's existing healthcare-AI domain)
- **When** the report is generated end-to-end using the current `pipeline/doc_generator.py`
- **Then** a real HTML/PDF report is produced and saved immutably at `evals/benchmarks/baseline/phase0-report-v1.*`
- **And** the run's paper/reference counts and any observably degraded output are captured in a companion findings note

#### Story 0.1.2: Seed Clinova Benchmark v1 with the two already-documented real failure cases
As a QA/Evaluation Architect, I want Benchmark v1 seeded with the reference-title-collision risk and the (now-fixed) arXiv query-construction bug as real cases, so that Phase 1-3 acceptance tests validate against confirmed, not hypothetical, failure modes.

**AC:**
- **Given** the existing project's Story 2.3 code-review finding (title-collision risk in reference caching) and Story 2.6 finding (arXiv OR-vs-AND bug)
- **When** Benchmark v1 is created
- **Then** it contains at least one title-collision case (two distinct real papers with identical/near-identical titles) and one multi-concept-query case (reproducing the arXiv topic-mismatch shape)
- **And** the benchmark is saved as an immutable, versioned `evaluation_benchmark` artifact per `06-versioning-lineage-architecture.md`

#### Story 0.1.3: Record baseline measurements against Problems A-F
As a Business Analyst, I want the baseline's measured state against brief Problems A-F explicitly recorded, so later phases can show concrete before/after improvement.

**AC:**
- **Given** Stories 0.1.1-0.1.2's outputs
- **When** the Phase 0 findings document is completed
- **Then** it states, for each of Problems A-F, whether the baseline exhibits the problem with concrete evidence — refining the cross-reference table already drafted in `00-analysis-and-architecture-options.md` §4 against the real Story 0.1.1 report rather than desk analysis alone

### Epic 0.2: Zero-Gap Fabrication Hotfix (unplanned — found live during Story 0.1.1, fixed 2026-08-21)

**Goal:** the headline Phase 0 finding (`evals/benchmarks/baseline/phase0-findings.md`) was severe enough — confidently fabricated, ungrounded proposals presented as real research directions — that the user asked for a thorough fix before proceeding to Phase 1, rather than deferring it to Phase 3's Gap Challenger as originally scoped. This epic is scoped narrowly to the two files directly implicated in the observed failure chain; it does not attempt the broader `_robust_parse`-duplication cleanup noted as a pre-existing, separately-scoped issue across `discovery_engine.py`/`graph_builder.py`/`llm_council.py`/`param_extractor.py`.

**FRs:** none directly (a data-integrity bugfix, not a planned capability) · **Files:** `pipeline/gap_detector.py`, `pipeline/proposal_generator.py` · **Bug-fix changelog ID:** B19 (continuing the inherited project's `# B<N> fix:` numbering — B18 was the last used).

#### Story 0.2.1: detect_gaps distinguishes a parse failure from a genuine empty result

**AC:**
- **Given** `detect_gaps`'s LLM response parses as a valid JSON list on the first attempt
- **When** the stage completes
- **Then** the parsed gaps are returned and `chat_json` is called exactly once
- **Given** the response is a literal, valid `[]`
- **When** the stage completes
- **Then** `[]` is returned without a retry (a genuine empty result is preserved, not conflated with a parse failure)
- **Given** the response fails to parse on the first attempt (not valid JSON, or valid JSON but not a list)
- **When** the stage retries
- **Then** exactly one retry is attempted with the identical prompt, and its result is used if it parses successfully
- **Given** both attempts fail to parse
- **When** the stage exhausts its retry
- **Then** it raises `GapDetectionError` (carrying `raw_response_preview`) rather than returning `[]` silently

**Status:** done. Tests: `tests/test_gap_detector_parse_retry.py` (7 cases). Verified against the real Phase 0 data that exposed the bug (`evals/benchmarks/baseline/verify_b19_fix.py`): the exact wiki/graph/context that originally produced 0 gaps now produces 5 real, evidence-grounded gaps.

#### Story 0.2.2: generate_proposals never calls the LLM on an empty gap list

**AC:**
- **Given** `gaps == []`
- **When** `generate_proposals` is called
- **Then** it returns `[]` immediately, without calling the LLM
- **Given** `gaps` is non-empty but none are `open`/`partial` (all `solved`)
- **When** `generate_proposals` is called
- **Then** the existing fallback-to-all-gaps behavior is unchanged (this story does not alter that pre-existing branch)

**Status:** done. Tests: `tests/test_proposal_generator_empty_guard.py` (3 cases, including a regression guard for the unaffected all-solved branch). Verified directly against real Phase 0 data.

---

## Phase 1 — Data Foundation

**Goal:** eliminate silent data loss (Problem A) and reference contamination (Problem B), and make fallback trust explicit (Problem C) — the highest-confidence, evidence-backed starting point per `00-analysis-and-architecture-options.md` §4. **No UI changes beyond the existing Streamlit interim theme; no new user-facing screens.**

### Epic 1.1: Multi-Parser Extraction & Reconciliation
**FRs:** FR-1 · **ADRs:** none directly · **Depends on:** Phase 0 · **Files:** new `packages/research-engine/parsing/` (or interim `pipeline/parsing/`), `pipeline/pdf_parser.py` (retained as one input)

#### Story 1.1.1a: Stand up Docling as a local Python dependency (unblocked, no Docker needed)
**AC:**
- **Given** Docling is a pure pip-installable package
- **When** it's added to the Phase 1 environment
- **Then** it runs directly in the Python venv with no container dependency, and a measured resource-cost result is recorded, confirming or revising the desk estimate in `05-data-architecture.md` §2

**Status:** done. Measured 2026-08-21 against real papers: **~1.1 GB process RSS, ~86s/paper steady-state (CPU, torch-based)** — revises the original "Moderate" desk estimate to "Heavy" (`evals/benchmarks/baseline/docling-resource-measurement.md`). Caching by content hash made binding as a result (`utils/database.py`'s `docling_extractions` table, `pipeline/docling_parser.py`).

#### Story 1.1.1b: Stand up GROBID via Gradle (deferred — see `amendments/2026-08-20-environment-constraints.md`)
**AC:**
- **Given** this development machine has no Docker access (no admin rights, no WSL2) but does have Java 11 already installed
- **When** GROBID is picked up
- **Then** it is built and run via its own Gradle wrapper (`./gradlew run`), not the `data` Compose profile, until Docker access is resolved
- **And** a measured resource-cost result (RAM/startup time) is recorded, confirming or revising the desk estimate in `05-data-architecture.md` §2
- **Not required to unblock the rest of Epic 1.1** — Story 1.1.2-1.1.4 proceed with PyMuPDF + Docling as the two-parser interim combination in the meantime

**Status:** still deferred — not picked up this pass, per its own AC (not required to unblock 1.1.2-1.1.4).

#### Story 1.1.2: Extract a paper independently with each available parser
**AC:**
- **Given** a sample paper
- **When** extraction runs
- **Then** an independent `ExtractedField` set exists per available parser (`05-data-architecture.md` §3) — PyMuPDF + Docling now, GROBID added once Story 1.1.1b lands — each correctly tagged by `source`, and reconciliation (Story 1.1.3) works correctly with either two or three parser inputs (never assumes exactly three)

**Status:** done. `pipeline/docling_parser.py` (new) alongside the existing `pipeline/pdf_parser.py`. Verified against real `Data-17072026/AuDHD_1.pdf`: PyMuPDF 5.3s/53,417 chars/5 tables; Docling 96.1s (cold)/65,083 chars/5 tables. Tests: `tests/test_docling_parser_cache.py`.

#### Story 1.1.3: Reconcile multi-parser output into one canonical paper representation
**AC:**
- **Given** three `ExtractedField` sets for one paper
- **When** reconciliation runs
- **Then** one canonical value is chosen per field with a documented resolution rule, and all candidate values remain queryable (not discarded)
- **And** a field where every parser fails is marked missing/low-confidence, never silently omitted

**Status:** done, scoped to the fields both parsers can produce deterministically today (`full_text`, `doi`, `tables` — title/authors/abstract/etc. remain LLM-derived via `wiki_compiler.py` unchanged, not silently claimed as reconciled). `pipeline/extraction_reconciler.py` (new). Real-data validation caught and fixed a genuine bug in the first implementation (a naive "prefer longer string" DOI tiebreak that happened to work by coincidence on the first test but isn't the actual right signal) — see `evals/benchmarks/baseline/doi-disambiguation-note.md` for the full finding: position-in-text, not length, correctly distinguishes a paper's own DOI from an unrelated one (e.g. a linked OSF dataset DOI) mentioned later in the body. Tests: `tests/test_extraction_reconciler.py` (18 cases).

#### Story 1.1.4: LLM recovery only for genuinely unresolved fields
**AC:**
- **Given** a field where all three parsers disagree or fail
- **When** reconciliation reaches that field
- **Then** and only then is an `LLMProvider` call made for recovery (tagged `source=LLM_RECOVERY`)
- **Given** a field where parsers agree
- **When** reconciliation runs
- **Then** no LLM call is made for that field (enforces `04-ai-research-architecture.md` §2's discipline)

**Status:** done, scoped to the `doi` field (the only field in this pass's reconciliation scope that both parsers can fail to resolve at all — `full_text`/`tables` always have a fallback candidate as long as either parser produced anything). `recover_doi_via_llm()` in `pipeline/extraction_reconciler.py`, invoked only when `needs_llm_recovery=True`. Tests confirm the LLM is never called when a DOI is already resolved (`tests/test_extraction_reconciler.py::DoiLlmRecoveryTests`).

### Epic 1.2: Corpus Quality Engine & Quality Gates
**FRs:** FR-2, FR-3 · **Depends on:** Epic 1.1

#### Story 1.2.1: Compute per-paper extraction completeness score
**AC:** **Given** a reconciled canonical paper; **When** completeness is computed; **Then** the score reflects the % of `05-data-architecture.md` §4's field list present at confidence ≥ medium.

**Status:** done. `pipeline/corpus_quality.py`'s `score_paper_completeness()`. Honest by construction: 5 of the 16 fields (authors, abstract, introduction, metrics, conclusion) have no extraction path anywhere in the pipeline today and always score `not_extracted`, distinct from a field that was attempted and came back empty — not silently collapsed into the same signal. Real corpus (`Data-17072026/`) scored 44-56% per paper.

#### Story 1.2.2: Compute corpus-level quality metrics and reference-resolution funnel
**AC:** **Given** a corpus of reconciled papers and references; **When** the Corpus Quality Engine runs; **Then** it outputs the full funnel and metric set (`05-data-architecture.md` §7) as one structured result attached to the run.

**Status:** done. `compute_corpus_quality()`, built directly on the existing `reference_extractor.py` diagnostics shape. Real-data validation caught a genuine bug before shipping: an initial version divided `ref_diagnostics["doi_entries"]` by `structured_entries`, which are not numerator/denominator of the same fraction (`doi_entries` counts raw DOI-regex matches added on top of `structured_entries` during combined-list construction, not a subset of it) — produced a rate of 4.25 on real data. Fixed to compute DOI resolution rate from the actual resolved reference records. Real corpus result: 52.1% extraction completeness, 93.9% DOI resolution rate, `DEGRADED` gate.

#### Story 1.2.3: Enforce the PASS/DEGRADED/FAIL quality gate
**AC:**
- **Given** corpus quality metrics
- **When** the gate evaluates
- **Then** a `FAIL` result blocks gap-analysis stages by default
- **Given** a user explicitly overrides a `FAIL` gate
- **When** the override is applied
- **Then** it is logged (who/when/why) and the run's degraded provenance still propagates into any generated report

**Status:** done. `enforce_quality_gate()` / `QualityGateBlockedError`. **Not yet wired into `app.py`'s live run flow** — the gate is implemented and tested in isolation but the Streamlit pipeline doesn't call it yet; that integration (plus a UI affordance for the override) is tracked as follow-up, not silently claimed done here.

### Epic 1.3: Canonical Reference & Paper Identity Resolution
**FRs:** FR-4, FR-5 · **ADRs:** ADR-007 · **Depends on:** Epic 1.1

#### Story 1.3.1: Implement the DOI→PMID→OpenAlex→S2→normalized(title+author+year) priority chain
**AC:** **Given** a reference with a resolvable DOI; **When** resolution runs; **Then** it resolves at the DOI level with `VERIFIED` status. **Given** a reference resolvable only by normalized title+author+year; **When** resolution runs; **Then** all three fields must match for `ACCEPTED` status — a partial match yields `QUARANTINED`, never `ACCEPTED`.

**Status:** done, with one honest gap. `pipeline/canonical_resolver.py`'s `resolve_canonical_identity()`. DOI, Semantic Scholar ID, arXiv ID, and normalized title+author+year all work against real data. PMID is recovered from the existing PubMed enrichment's `url` field (cheap regex, no upstream change needed). **OpenAlex ID is structurally present in the chain but will never match** — `pipeline/reference_extractor.py`'s OpenAlex query doesn't request an `id` field at all, so nothing is captured to resolve against. Not fixed in this pass (would require modifying the existing OpenAlex enrichment call, out of Epic 1.3's scope) — recorded as a real, open gap, not silently claimed complete.

#### Story 1.3.2: Merge multi-provider records into one canonical paper
**AC:** **Given** the benchmark's duplicate-provider-record case; **When** resolution runs against it; **Then** exactly one canonical paper results, and each contributing provider's raw record is preserved and separately queryable.

**Status:** done. `merge_canonical_references()`. Verified against Benchmark v1's real duplicate-DOI fixture (3 pairs from the actual `Data-17072026/` corpus) — each pair correctly merges to 1 canonical reference with both provider records preserved.

#### Story 1.3.3: Reference status model with default-safe corpus filtering
**AC:** **Given** references with `QUARANTINED`/`UNRESOLVED` status; **When** a run completes; **Then** only `VERIFIED`/`ACCEPTED` references feed gap analysis by default, and quarantined/unresolved references are visible in the corpus data contract with an explicit, logged manual-promotion path — never silent auto-promotion.

**Status:** the status model itself (`resolve_status()`, 5-value VERIFIED/ACCEPTED/QUARANTINED/UNRESOLVED/REJECTED) is done and tested. **The default-safe filtering behavior — actually excluding QUARANTINED/UNRESOLVED references from gap analysis — is NOT yet wired into `app.py`'s live pipeline flow.** `canonical_resolver.py` is a standalone, tested module; integrating it into the real run (replacing the current unmerged `ref_papers` list app.py passes downstream) is real remaining work, not done in this pass. Flagged explicitly rather than implied.

#### Story 1.3.4: Regression test against the known title-collision benchmark case
**AC:** **Given** Benchmark v1's title-collision case (Story 0.1.2); **When** the new resolver runs against it; **Then** the two distinct papers resolve to two distinct canonical identities — the acceptance test proving ADR-007 is actually in effect, not merely documented.

**Status:** done, against real fixtures (not the originally-planned synthetic case — Benchmark v1 was reseeded in Phase 0 with real findings). `tests/test_canonical_resolver.py::BenchmarkV1RegressionTests`: the duplicate-DOI case correctly merges (3/3 real pairs); the Español contamination case correctly merges to 1 reference with `VERIFIED` status (a real DOI legitimately resolves VERIFIED — relevance filtering is a distinct, not-yet-built stage, and the benchmark fixture's `expected_behavior` was corrected to reflect this real scope boundary rather than overclaim); the truncated-DOI case resolves without crashing or spuriously merging unrelated entries.

### Epic 1.4: Branding Layer & LLMProvider Port Extraction
**FRs:** NFR-1, FR-17 · **ADRs:** ADR-004 · **Depends on:** nothing (parallelizable with 1.1-1.3)

#### Story 1.4.1: Extract the LLMProvider interface behind the existing azure_client.py logic
**AC:** **Given** the existing `Result[str, ErrorInfo]` pattern in `utils/azure_client.py`; **When** the `LLMProvider` port is introduced; **Then** all existing callers continue to work unchanged (behavior-preserving refactor) — verified by the existing test suite (`tests/test_azure_client.py`, `tests/test_caller_resilience.py`) passing unmodified.

#### Story 1.4.2: Create the branding/theme config layer with Clinova identity
**AC:** **Given** the product name and tagline (`02-ux-specification.md` §2); **When** the branding layer is created; **Then** no other module references these strings literally, and the interim Streamlit UI reads them from this config — proving `03-system-architecture.md` AD-3 holds in practice.

---

## Phase 2 — Evidence Foundation (epic-level; stories detailed at Phase 2 kickoff)

**Goal:** structured Evidence Objects with provenance become the source of truth the graph and gap engine read, demoting wiki-synthesis to a UI convenience (Problem A, cont'd). **Trigger to begin:** Phase 1 quality gate (Epic 1.2) and reference resolution (Epic 1.3) are passing their benchmark regression tests.

- **Epic 2.1: Evidence Object Schema & Extraction** — FR-6 · Evidence Extractor agent (`04-ai-research-architecture.md` §3) · schema in `packages/research-schemas`. Story titles: define Evidence Object JSON Schema; implement Evidence Extractor agent with typed I/O + token budget; extract evidence from reconciled papers with page/section/span provenance; validate extraction against Evidence Object schema before acceptance.
- **Epic 2.2: Evidence Provenance Store & Wiki Demotion** — FR-6 (cont'd) · demotes `pipeline/wiki_compiler.py` output to display-only. Story titles: persist Evidence Objects with provenance; wire wiki_compiler as a rendering layer over Evidence Objects rather than an independent LLM call where feasible; update `doc_generator.py` reports to cite Evidence Objects, not wiki text, for scientific claims.

## Phase 3 — Reliable Research Intelligence (epic-level; stories detailed at Phase 3 kickoff)

**Goal:** graph quality scoring, the hybrid gap engine, the Gap Challenger state machine, and the determinism envelope — the core of the product's scientific-integrity claim. **Trigger to begin:** Phase 2's Evidence Objects are populated and validated for the sample project.

- **Epic 3.1: Graph Persistence & Quality Scoring** — FR-7, FR-8, FR-9 · ADR-002. Neo4j CE + NetworkX hybrid; version/quality-score/coverage/duplicate-rate/unresolved-entity-rate/fallback-indicator per build; every edge requires an Evidence Object reference.
- **Epic 3.2: Hybrid Gap Engine** — FR-10 · deterministic pattern library (medical/healthcare-AI patterns, Research Methodology Specialist pass) + graph-structural reasoning + scoped semantic reasoning; every candidate gap tagged with its contributing source(s).
- **Epic 3.3: Search Planner & Multi-Provider Search** — FR-14, FR-15 · `SearchProvider` port formalized; query-family generation (synonyms/terminology/broader-narrower); union → canonical dedup → metadata filter → embedding retrieval → rerank → LLM relevance review funnel.
- **Epic 3.4: Gap Challenger State Machine** — FR-11, FR-12, FR-13 · ADR-008 · the 11-status lifecycle and Search Coverage Score decision table (`04-ai-research-architecture.md` §5); every stage inspectable; regression-tested against the benchmark's known-open/known-closed/ambiguous cases.
- **Epic 3.5: EmbeddingProvider / RerankerProvider + Qdrant** — FR-17, FR-18 · ADR-001, ADR-004 (completion) · BGE-M3/BGE-reranker local adapters.
- **Epic 3.6: Determinism Envelope & Repeatability Score** — FR-19, FR-20 · ADR-006 · agent typed configs with budgets/timeouts; Repeatability Score computed against Benchmark v1+.

## Phase 4 — Versioned Platform (epic-level)

**Goal:** every artifact versioned/immutable, run manifests, the Research Artifact Registry, and champion/challenger promotion. **Trigger to begin:** Phase 3's Gap Challenger is producing regression-tested statuses on the benchmark; SQLite's single-blob-per-run model becomes the concrete limiting factor for cross-run comparison (already a documented gap in `project-context.md`).

- **Epic 4.1: Postgres Migration & Research Artifact Registry** — FR-21, FR-22 · ADR-005 · forward-only migration scripts, no destructive down-migration against research data.
- **Epic 4.2: Run Manifest Recorder** — FR-23 · full schema per `06-versioning-lineage-architecture.md` §3.
- **Epic 4.3: Champion/Challenger Evaluation Harness & Benchmark Expansion** — FR-26 · `07-evaluation-architecture.md`'s full metric set; False Novelty Rate as the hard promotion gate (ADR-008-adjacent).
- **Epic 4.4: Lineage Views & Compare Engine** — FR-24, FR-28 · technical + scientific lineage; metric diffing and change explanation feeding the future Compare UI screen's data contract.

## Phase 5 — Enterprise UI (epic-level)

**Goal:** the Next.js/FastAPI shell and full screen inventory, built against Phase 1-4's real data contracts. **Trigger to begin:** Phase 4's Run Manifest and Artifact Registry are populated with real run history (not mocks).

- **Epic 5.1: Design System & Application Shell** — FR-29 · `02-ux-specification.md` §3-4; branding layer (Epic 1.4) consumed here.
- **Epic 5.2: Core Screens** — Landing, Project Dashboard, Corpus, Paper Detail, Data Quality.
- **Epic 5.3: Intelligence Screens** — Knowledge Graph, Research Gaps, Gap Detail, Gap Challenger, Research Council, Proposal.
- **Epic 5.4: Engineering Screens** — Runs, Run Detail/Manifest, Compare, Research Time Machine, Lineage, Version Registry.
- **Epic 5.5: Reporting** — FR-27, FR-28 · HTML/PDF/JSON export; report-to-report comparison and downloadable diff.

## Phase 6 — Governance (epic-level, conditional — see `10-phased-implementation-plan.md` trigger)

- **Epic 6.1: Identity (Keycloak)** — FR-33.
- **Epic 6.2: Policy & Audit (OPA)** — FR-33 (cont'd).

## Phase 7 — Observability (epic-level)

- **Epic 7.1: OpenTelemetry instrumentation**
- **Epic 7.2: Langfuse LLM observability**
- **Epic 7.3: Prometheus/Grafana dashboards**

## Phase 8 — Portability (epic-level)

- **Epic 8.1: Docker hardening for production images**
- **Epic 8.2: OpenTofu cloud modules**
- **Epic 8.3: Kubernetes/Helm deployment (AKS/EKS/GKE/OpenShift/on-prem targets)**

---

## Code-review checklist addendum (applies to every story, every phase)

Per `04-ai-research-architecture.md` §2's binding LLM-use discipline, every story's code review must explicitly check: *does this change add an LLM call where deterministic code or a local model would do?* — this is not left to reviewer discretion alone; it is a named checklist item precisely because the discipline is easy to erode incrementally without a standing check.
