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

---

## Phase 1 — Data Foundation

**Goal:** eliminate silent data loss (Problem A) and reference contamination (Problem B), and make fallback trust explicit (Problem C) — the highest-confidence, evidence-backed starting point per `00-analysis-and-architecture-options.md` §4. **No UI changes beyond the existing Streamlit interim theme; no new user-facing screens.**

### Epic 1.1: Multi-Parser Extraction & Reconciliation
**FRs:** FR-1 · **ADRs:** none directly · **Depends on:** Phase 0 · **Files:** new `packages/research-engine/parsing/` (or interim `pipeline/parsing/`), `pipeline/pdf_parser.py` (retained as one input)

#### Story 1.1.1: Stand up GROBID and Docling as local services
**AC:**
- **Given** the `data` Compose profile (`08-local-deployment-architecture.md`)
- **When** `docker compose --profile data up` runs
- **Then** both services report healthy and expose their extraction APIs
- **And** a measured resource-cost result (RAM/startup time against this project's actual corpus) is recorded, confirming or revising the desk estimate in `05-data-architecture.md` §2

#### Story 1.1.2: Extract a paper independently with all three parsers
**AC:**
- **Given** a sample paper
- **When** extraction runs
- **Then** three independent `ExtractedField` sets exist (`05-data-architecture.md` §3), each correctly tagged by `source`

#### Story 1.1.3: Reconcile multi-parser output into one canonical paper representation
**AC:**
- **Given** three `ExtractedField` sets for one paper
- **When** reconciliation runs
- **Then** one canonical value is chosen per field with a documented resolution rule, and all candidate values remain queryable (not discarded)
- **And** a field where every parser fails is marked missing/low-confidence, never silently omitted

#### Story 1.1.4: LLM recovery only for genuinely unresolved fields
**AC:**
- **Given** a field where all three parsers disagree or fail
- **When** reconciliation reaches that field
- **Then** and only then is an `LLMProvider` call made for recovery (tagged `source=LLM_RECOVERY`)
- **Given** a field where parsers agree
- **When** reconciliation runs
- **Then** no LLM call is made for that field (enforces `04-ai-research-architecture.md` §2's discipline)

### Epic 1.2: Corpus Quality Engine & Quality Gates
**FRs:** FR-2, FR-3 · **Depends on:** Epic 1.1

#### Story 1.2.1: Compute per-paper extraction completeness score
**AC:** **Given** a reconciled canonical paper; **When** completeness is computed; **Then** the score reflects the % of `05-data-architecture.md` §4's field list present at confidence ≥ medium.

#### Story 1.2.2: Compute corpus-level quality metrics and reference-resolution funnel
**AC:** **Given** a corpus of reconciled papers and references; **When** the Corpus Quality Engine runs; **Then** it outputs the full funnel and metric set (`05-data-architecture.md` §7) as one structured result attached to the run.

#### Story 1.2.3: Enforce the PASS/DEGRADED/FAIL quality gate
**AC:**
- **Given** corpus quality metrics
- **When** the gate evaluates
- **Then** a `FAIL` result blocks gap-analysis stages by default
- **Given** a user explicitly overrides a `FAIL` gate
- **When** the override is applied
- **Then** it is logged (who/when/why) and the run's degraded provenance still propagates into any generated report

### Epic 1.3: Canonical Reference & Paper Identity Resolution
**FRs:** FR-4, FR-5 · **ADRs:** ADR-007 · **Depends on:** Epic 1.1

#### Story 1.3.1: Implement the DOI→PMID→OpenAlex→S2→normalized(title+author+year) priority chain
**AC:** **Given** a reference with a resolvable DOI; **When** resolution runs; **Then** it resolves at the DOI level with `VERIFIED` status. **Given** a reference resolvable only by normalized title+author+year; **When** resolution runs; **Then** all three fields must match for `ACCEPTED` status — a partial match yields `QUARANTINED`, never `ACCEPTED`.

#### Story 1.3.2: Merge multi-provider records into one canonical paper
**AC:** **Given** the benchmark's duplicate-provider-record case; **When** resolution runs against it; **Then** exactly one canonical paper results, and each contributing provider's raw record is preserved and separately queryable.

#### Story 1.3.3: Reference status model with default-safe corpus filtering
**AC:** **Given** references with `QUARANTINED`/`UNRESOLVED` status; **When** a run completes; **Then** only `VERIFIED`/`ACCEPTED` references feed gap analysis by default, and quarantined/unresolved references are visible in the corpus data contract with an explicit, logged manual-promotion path — never silent auto-promotion.

#### Story 1.3.4: Regression test against the known title-collision benchmark case
**AC:** **Given** Benchmark v1's title-collision case (Story 0.1.2); **When** the new resolver runs against it; **Then** the two distinct papers resolve to two distinct canonical identities — the acceptance test proving ADR-007 is actually in effect, not merely documented.

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
