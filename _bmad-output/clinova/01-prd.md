---
name: 'Clinova Research Intelligence Platform — PRD'
type: prd
status: draft-for-review
created: '2026-08-20'
inputDocuments: ['00-analysis-and-architecture-options.md']
companions: ['02-ux-specification.md', '03-system-architecture.md', '09-epics-and-stories.md']
---

# Product Requirements Document — Clinova Research Intelligence Platform

## 1. Product vision & positioning

**Product name:** Clinova Research Intelligence Platform
**Tagline:** Evidence → Gaps → Hypotheses → Studies
**Landing-page headline (marketing voice, distinct from the tagline — see analysis §2, C8):** "Find the research nobody has done yet."

**Positioning statement:** Clinova is an enterprise-grade, evidence-driven medical and healthcare-AI research intelligence platform for discovering, validating, comparing, and tracking research gaps from a corpus of research papers — through structured extraction, cross-paper knowledge graphs, adversarial gap validation, and reproducible, versioned AI analysis.

**Clinova is explicitly NOT:**
- A hospital or clinical information system
- A clinical-trial-management system
- A generic RAG / document-chat application
- A generic medical chatbot

**Branding independence (binding constraint):** The product name, tagline, and visual identity live entirely in a branding/theme layer. No source file, database table, cache key, package name, or environment variable may contain "Clinova," "ResGap," or any other brand string. The engine is referred to internally by a neutral codename. This is enforced structurally, not by convention — see `03-system-architecture.md` §"Branding Layer."

## 2. Personas

| Persona | Description | Primary needs |
|---|---|---|
| **Research Scientist / Clinical Researcher** (primary user) | Uploads a small corpus of papers on a medical-AI topic, wants to know what's genuinely unstudied. Not an AI engineer. | Trustworthy gap status, plain-language explanations, exportable evidence-backed proposals, doesn't want to see infrastructure. |
| **Research Program Lead / Grant Reviewer** | Compares research opportunities across projects, needs defensible novelty claims to justify funding direction. | Confidence indicators, comparison across runs/versions, exportable reports with full provenance. |
| **Platform Operator** (Divya, initially) | Runs the platform locally, evolves the architecture, evaluates pipeline changes. | Reproducibility, run manifests, champion/challenger comparison, low local resource footprint per phase. |
| **Future: Second Researcher / Reviewer** | Not yet a real user — governance features (Phase 6) are built when this persona becomes real, not before (per `00-analysis...`, C4). | Access control, audit trail. |

## 3. Problem statement

Six structural problems in the current pipeline (brief §3, cross-referenced against real findings from the existing project's own code-review trail in `00-analysis-and-architecture-options.md` §4):

- **P-A Data loss** — information can silently disappear between PDF → parser → summary → wiki → graph → gap analysis, with no measurement of what was lost.
- **P-B Reference contamination** — fallback reference resolution can misattribute or merge unrelated papers into the corpus. *(Already partially observed in production: title-collision cache risk, documented in the existing project's Story 2.3 review.)*
- **P-C Over-reliance on fallback** — fallback extraction output is currently trusted the same as verified output, with no status distinguishing degrees of trust.
- **P-D Missing search results misread as "gap is open"** — an empty academic-search result can mean the gap is genuinely open, or it can mean a bad query, vocabulary mismatch, provider outage, or insufficient coverage — and today these are indistinguishable in the worst case. *(The most severe instance — the arXiv OR-vs-AND query bug — is already fixed upstream; the general problem of coverage measurement is not.)*
- **P-E Knowledge-graph quality is invisible** — a degraded/fallback graph can silently feed a high-confidence gap conclusion with no quality signal downstream.
- **P-F LLM nondeterminism is unmeasured** — the same project can produce materially different conclusions across runs, with no way to tell whether a conclusion is stable or model-sensitive.

## 4. Goals & success metrics

| Goal | Metric | Target (aspirational — refined per-phase in `10-phased-implementation-plan.md`) |
|---|---|---|
| Eliminate silent data loss | Extraction completeness score, measured per paper per field (§9 field list in `05-data-architecture.md`) | ≥95% of scientifically-load-bearing fields (methods, dataset/population, results, limitations) extracted with a traceable source span, or explicitly flagged as missing — never silently absent |
| Eliminate reference contamination | Canonical reference collision rate on the Clinova benchmark (`07-evaluation-architecture.md`) | 0 known-distinct papers merged under one canonical identity on the benchmark's adversarial title-collision cases |
| Make fallback trust explicit | % of corpus items with a resolution status (`VERIFIED/ACCEPTED/QUARANTINED/UNRESOLVED/REJECTED`) surfaced to the user before gap analysis proceeds | 100% — no ungated status is possible by construction |
| Make search coverage measurable | Search Coverage Score computed for every gap validation; gaps with `SEARCH_PENDING`/`INSUFFICIENT_EVIDENCE` never silently rendered as `OPEN` | 100% of gap statuses trace to a documented decision rule (state machine in `04-ai-research-architecture.md`) |
| Make graph quality visible | Every graph build carries version, quality score, coverage, duplicate rate, unresolved-entity rate, fallback indicator | 100% of graph builds scored; downstream gap confidence provably reduced when graph quality is degraded |
| **False Novelty Rate — the single most important product metric (brief §21)** | % of gaps the system reports as novel that the benchmark's known-closed-gap set proves are not | Minimize aggressively; explicitly prioritized over gap recall (missing a real gap is preferable to inventing one) |
| Bound nondeterminism | Repeatability Score (gap overlap, ranking correlation, confidence drift, claim/proposal stability across repeated runs on a frozen benchmark) | Reported per pipeline version; used as a champion/challenger promotion gate, not a fixed pass/fail target initially |
| Local-first economics | Token usage per run/stage/agent/model, tracked in the run manifest | No regression in cost-per-run as capability is added, enforced by per-agent token budgets (`04-ai-research-architecture.md`) |

## 5. Functional requirements

Organized by capability area. Each FR states intent and a success signal; detailed Given/When/Then acceptance criteria live in `09-epics-and-stories.md` per story.

### 5.1 Data Foundation (Phase 1)

- **FR-1** A paper can be extracted by more than one parser (GROBID, PyMuPDF, and existing `pdf_parser.py`/PageIndex logic) and the results reconciled into one canonical paper representation, with each field's value, source, extraction method, page/section, and confidence recorded. *Success: a reconciliation report exists per paper showing where parsers agreed/disagreed and which value won and why.*
- **FR-2** Every extracted field is scored for completeness against a defined scientific field list (title, authors, DOI, abstract, methodology, dataset/population, results, limitations, future work, references, tables). *Success: a Corpus Quality Engine score is computed before any downstream stage runs.*
- **FR-3** A run's corpus receives an overall quality gate (`PASS`/`DEGRADED`/`FAIL`) before gap analysis proceeds; a `FAIL` gate blocks downstream stages by default (with an explicit, logged override, not a silent continue). *Success: it is structurally impossible for gap analysis to run against a `FAIL`-gated corpus without an explicit user override.*
- **FR-4** A paper or reference must resolve to exactly one canonical identity regardless of which provider (DOI/PMID/OpenAlex/Semantic Scholar/normalized title+author+year) discovered it; provider-specific metadata is preserved separately, not discarded. *Success: the benchmark's duplicate-provider-record test case produces one canonical paper, not N.*
- **FR-5** Fallback-derived data carries an explicit resolution status (`VERIFIED`/`ACCEPTED`/`QUARANTINED`/`UNRESOLVED`/`REJECTED`) and never silently upgrades to "trusted" without a defined transition rule. *Success: every reference in a run's corpus has a status visible in the Corpus/Data Quality UI.*

### 5.2 Evidence Foundation (Phase 2)

- **FR-6** Every scientific claim, method, dataset, result, limitation, etc. extracted from a paper is represented as a structured Evidence Object (per the type list in brief §8) carrying provenance (paper_id, page, section, text span, extraction version, confidence) — not only as unstructured wiki prose. *Success: the graph and gap engine read Evidence Objects, and every gap explanation traces back to at least one Evidence Object with a real page/section reference.*

### 5.3 Knowledge Graph (Phase 3)

- **FR-7** Every knowledge-graph build is versioned and scored: build status, quality score, extraction coverage, evidence coverage, duplicate rate, unresolved-entity rate, fallback indicator. *Success: a degraded graph provably reduces the confidence of any gap conclusion derived from it — not silently treated as equal-quality to a clean build.*
- **FR-8** No graph relationship is created solely because an LLM inferred it without a supporting Evidence Object. *Success: every graph edge is traceable to at least one Evidence Object.*
- **FR-9** Graph persistence supports interactive exploration: search nodes, filter by type/paper/confidence, trace paths, and compare two graph versions. *(UI requirement — detailed in `02-ux-specification.md` §"Knowledge Graph Page.")*

### 5.4 Hybrid Gap Engine & Gap Challenger (Phase 3)

- **FR-10** Candidate research gaps are generated from three combined sources, not one LLM prompt alone: a deterministic pattern library (missing external validation, single-center studies, small samples, no fairness testing, etc.), graph-structural reasoning (sparse/missing/conflicting relationships, untested combinations), and LLM semantic reasoning — used only where conceptual reasoning is genuinely required.
- **FR-11** Every candidate gap is adversarially challenged before being presented as a research opportunity: query planning → query expansion → multi-provider search → deduplication → reranking → relevance judgment → contradiction analysis → status assignment. The Gap Challenger's stated objective is to *prove the gap already has research*, not to confirm the user's hypothesis.
- **FR-12** A gap's status is one of the defined 11-value lifecycle (`GENERATED, EVIDENCE_SUPPORTED, SEARCH_PENDING, SEARCHED, CHALLENGED, OPEN, PARTIALLY_OPEN, CONTESTED, LIKELY_CLOSED, CLOSED, INSUFFICIENT_EVIDENCE`), assigned by a documented, deterministic decision rule (not implicit LLM judgment) — see `04-ai-research-architecture.md` for the state-transition table. **An empty search result must resolve to `INSUFFICIENT_EVIDENCE` or `SEARCH_PENDING`, never silently to `OPEN`.**
- **FR-13** Every gap challenge stage (query terms used, providers queried, candidate count, dedup/rerank funnel, relevant-result count, contradiction count) is inspectable by the user, not hidden. *(UI requirement — `02-ux-specification.md` §"Gap Challenger Page.")*

### 5.5 Academic Search (Phase 3)

- **FR-14** Search providers are pluggable behind a `SearchProvider` interface; the initial set covers PubMed, Europe PMC, OpenAlex, Semantic Scholar, Crossref, arXiv, and (where relevant) ClinicalTrials.gov.
- **FR-15** A single candidate gap generates multiple query families (synonyms, medical terminology, abbreviations, broader/narrower concepts) rather than one LLM-generated sentence; results are retrieved broadly first and ranked afterward (union → canonical dedup → metadata filter → embedding retrieval → rerank → LLM relevance review).
- **FR-16** Search coverage is measured and surfaced per gap validation, distinguishing "genuinely no related work found" from "search itself was insufficient" (poor query, provider outage, vocabulary mismatch).

### 5.6 AI / Model Architecture (Phase 1-4, incremental)

- **FR-17** LLM inference, embeddings, and reranking are each behind their own provider interface (`LLMProvider`, `EmbeddingProvider`, `RerankerProvider`); the current NVIDIA NIM integration becomes the first `LLMProvider` implementation without business logic elsewhere depending on it directly.
- **FR-18** LLM calls are reserved for tasks that genuinely need them (difficult extraction, semantic gap reasoning, query expansion, final relevance judgment, contradiction reasoning, research council, proposal reasoning); deterministic code is used for parsing, ID matching, exact dedup, metadata transforms, state transitions, versioning, and quality arithmetic. Local models (e.g. BGE-M3, a BGE reranker) are used for embeddings/reranking/simple classification rather than LLM calls.
- **FR-19** Agent roles (Evidence Extractor, Gap Generator, Gap Challenger, Methodology Critic, Research Chair) are each narrowly scoped, with typed input/output, a token budget, a maximum tool-call count, a timeout, an allowed-tools list, a model configuration, and a prompt version. Agents do not recursively spawn further agents without an explicit, bounded uncertainty-threshold trigger.
- **FR-20** Reproducibility controls (low temperature where appropriate, fixed seed where the provider supports it, versioned system prompts, structured JSON-schema outputs, deterministic pre/post-processing and sort ordering, immutable corpus/search snapshots, model/prompt/tool version tracking, semantic-input-hash caching, run manifests) are applied consistently, and a **Repeatability Score** is computed by running the frozen benchmark multiple times and measuring gap overlap, ranking correlation, confidence drift, and claim/proposal stability.

### 5.7 Versioning, Lineage & Registry (Phase 4)

- **FR-21** Every research artifact type (project, corpus, paper extraction, references, evidence schema, embedding model, vector index, graph, graph builder, search strategy/snapshot, prompt bundle, model bundle, agent definitions, pipeline, gap set, proposal set, report, evaluation benchmark) is versioned and immutable once created — nothing scientifically load-bearing is overwritten in place.
- **FR-22** A Research Artifact Registry (application-owned, not replaced by MLflow — see `00-analysis...` C3) records artifact_id, type, version, schema_version, parent_artifact, project_id, run_id, created_at, content_hash, storage_uri, status, and metadata for every artifact.
- **FR-23** Every research run produces an immutable Run Manifest capturing input corpus version, pipeline version, git commit, parser/resolver/embedding/reranker/graph-builder versions, prompt/model bundle, search strategy version and date, output artifacts, evaluation metrics, warnings, quality-gate results, duration, and token usage.
- **FR-24** Two technical-lineage and scientific-lineage views are available: PDF→parser→evidence→embedding→graph→gap→proposal (technical), and paper→passage→claim→relationship→candidate gap→challenge→validated gap→proposal (scientific) — every object traceable in both.

### 5.8 Evaluation (Phase 3-4, ongoing)

- **FR-25** A versioned, immutable internal benchmark (the "Clinova Benchmark") exists containing known genuine gaps, known closed gaps, intentionally false gaps, ambiguous/contradictory cases, duplicate references, malformed citations, unrelated references, missing abstracts, and parser-failure cases.
- **FR-26** Champion/challenger pipeline comparison runs two pipeline versions against the same frozen benchmark and reports extraction completeness, reference resolution precision/recall, corpus contamination, retrieval recall, gap precision, **false novelty rate**, contradiction recall, evidence coverage, consistency, latency, and token usage; promotion requires passing defined acceptance thresholds, never a manual "looks fine" judgment alone.

### 5.9 Reporting (Phase 1 → progressively enriched)

- **FR-27** Professional downloadable reports (HTML, PDF, JSON evidence package) are generated with a fixed section structure (Executive Summary → Methodology → Corpus/Data Quality → Evidence → Graph → Gaps/Validation/Contradictions → Proposals → Risks → Run Metadata → Limitations → Appendix), and every report embeds its run ID, corpus version, pipeline version, generation timestamp, search cutoff date, and overall research confidence.
- **FR-28** Two reports (by version) can be compared, surfacing new/removed papers, new evidence, changed graph relationships, new/closed gaps, confidence changes, and proposal/methodology changes, with the comparison itself downloadable.

### 5.10 Enterprise UI (Phase 5)

- **FR-29** The full screen inventory in `02-ux-specification.md` (landing/login, application shell with the specified navigation groups, project dashboard, corpus, paper detail, data quality, knowledge graph, research gaps, gap detail, gap challenger, research council, proposal, runs, run manifest, compare, research time machine, lineage, version registry) is implemented as a Next.js/TypeScript application against real backend contracts established in Phases 1-4.
- **FR-30** The interface follows progressive disclosure, plain-language uncertainty indicators, and good empty/loading/failure states, such that a non-AI-engineer researcher can use it without needing to understand the underlying pipeline.

### 5.11 Local Deployment & Portability (Phase 0-8, incremental)

- **FR-31** The full system runs on a single developer laptop via `docker compose --profile <name> up`, with profiles matching phases (see `08-local-deployment-architecture.md`) rather than requiring all services simultaneously.
- **FR-32** All infrastructure-facing code sits behind hexagonal ports (`ObjectStore`, `VectorStore`, `GraphStore`, `LLMProvider`, `EmbeddingProvider`, `RerankerProvider`, `SearchProvider`, `SecretProvider`, `IdentityProvider`, `ArtifactRegistry`); no business logic contains a direct cloud-provider SDK call.

### 5.12 Governance (Phase 6 — conditional, not committed by default)

- **FR-33** *(Triggered only when a second real user or a compliance requirement exists — see `00-analysis...` C4.)* Identity (Keycloak/OIDC) and policy (OPA) enforce access control; all governance-relevant actions are audit-logged.

## 6. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | The product name/tagline/brand must be changeable without touching engine code (§1, C7). |
| NFR-2 | No pipeline restructuring occurs without an ADR; hexagonal ports are introduced only in the phase that has a second real implementation to design against (`00-analysis...` §7). |
| NFR-3 | Every phase leaves the repository in a working, demoable state; no phase requires a big-bang cutover (brief §52). |
| NFR-4 | Infrastructure is introduced strictly per-phase (see `08-local-deployment-architecture.md`); no phase requires services a later phase alone needs. |
| NFR-5 | LLM usage is bounded by explicit per-agent token/request/search-call/timeout budgets; the system must not repeatedly send full papers to the LLM (hierarchical evidence retrieval instead). |
| NFR-6 | Every scientifically load-bearing artifact is versioned and immutable; nothing is silently overwritten. |
| NFR-7 | False novelty is treated as a more severe failure mode than missed novelty throughout scoring, thresholds, and UI language. |
| NFR-8 | The system must remain usable and understandable by a non-AI-engineer researcher (plain language, progressive disclosure, explicit uncertainty — never presented as false certainty). |

## 7. Explicit non-goals

- Hospital / clinical information system functionality
- Clinical-trial-management functionality
- Generic RAG document chat, unscoped to the gap-discovery workflow
- Generic medical chatbot functionality
- Kubernetes as a requirement for local development (brief §23)
- Multi-tenant identity/policy infrastructure before a real second user exists
- Circuit breaker (`pybreaker`) — retry-with-backoff judged sufficient at current scale (inherited from the existing `ARCHITECTURE-SPINE.md` Deferred section)
- Concurrent/multi-user cache access before Phase 4's Postgres migration
- Any cloud deployment prior to Phase 8

## 8. Phasing summary

See `10-phased-implementation-plan.md` for the authoritative, gated phase plan. Summary: Phase 0 (baseline/benchmark) → Phase 1 (data foundation) → Phase 2 (evidence foundation) → Phase 3 (graph QA, hybrid gap engine, Gap Challenger — first new infra: Qdrant, Neo4j) → Phase 4 (versioning/registry/manifest/champion-challenger — Postgres, MinIO) → Phase 5 (enterprise UI) → Phase 6 (governance, conditional) → Phase 7 (observability) → Phase 8 (portability/cloud).

## 9. Assumptions & open questions

- **Assumption:** The free NVIDIA NIM API remains available and free through at least Phase 1-3; no budget exists for a paid LLM provider. Revisit if this changes.
- **Assumption:** Single researcher/operator through Phase 5; Phase 6 governance work is not on a committed calendar date.
- **Open question:** Exact set of medical-domain deterministic gap patterns (§10 of the brief lists examples) needs a Research Methodology Specialist pass during Phase 3 detailed design — the list in FR-10 is a starting set, not final.
- **Open question:** Whether ClinicalTrials.gov is in scope for Phase 3 or deferred — brief says "where relevant"; needs a concrete first-domain decision (the existing `domain_config.py` currently ships healthcare-AI-flavored domains — worth checking against before deciding).
- **Open question:** GROBID's local resource cost (JVM-based, non-trivial RAM/startup) needs a concrete benchmark against PyMuPDF+existing parser before Phase 1 detailed design commits to it — flagged in `03-system-architecture.md` as a Phase-1 spike, not assumed.
