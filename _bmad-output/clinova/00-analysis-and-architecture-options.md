---
name: 'Clinova — Brief Analysis & Target Architecture Options'
type: analysis
altitude: strategic
status: accepted
created: '2026-08-20'
sources:
  - 'Enterprise brief (verbatim, provided 2026-08-20)'
  - '_bmad-output/planning-artifacts/architecture/architecture-Research_Gap_Analyzer-2026-07-31/ARCHITECTURE-SPINE.md'
  - '_bmad-output/planning-artifacts/epics.md'
  - '_bmad-output/implementation-artifacts/deferred-work.md'
  - '_bmad-output/project-context.md'
  - 'Direct inspection of app.py, pipeline/*.py, utils/*.py in the baseline import'
companions: ['01-prd.md', '03-system-architecture.md', 'adr/*']
---

# Clinova Research Intelligence Platform — Brief Analysis & Target Architecture Options

**Working product name:** Clinova Research Intelligence Platform
**Tagline:** Evidence → Gaps → Hypotheses → Studies
**Internal engine codename (branding-independent):** `resgap-core` — see §7 for why the product name must never appear in code.

This is the first BMAD deliverable requested by the enterprise brief (§55): analyze the brief and the existing codebase, identify contradictions and unnecessary complexity, propose three target architecture options, recommend one, and challenge that recommendation — before any PRD, architecture spine, or code is written.

---

## 1. What the brief is actually asking for

Stripped of enterprise vocabulary, the brief asks for two things bolted together:

1. **A scientific-integrity rewrite** of the existing gap-detection pipeline — fix data loss, reference contamination, false novelty, ungrounded graphs, and irreproducibility (§3, §21-22). This is the part with genuine, well-argued scientific rationale and it maps directly onto weaknesses BMAD already partially discovered and started fixing in Epics 1-3 of the existing repo (see §4).
2. **An enterprise platform shell** around that pipeline — Next.js/FastAPI, Postgres/MinIO/Qdrant/Neo4j/Temporal/MLflow/Langfuse/Keycloak/OPA/Prometheus/Grafana, a 12-page desktop UI, versioning/lineage/registry/manifest systems, champion/challenger promotion, and a research benchmark (§9, §23-49).

These are not the same problem, and treating them as one program is the single biggest risk in the brief. (1) is testable in isolation with `pytest` and no new infrastructure. (2) is a platform-engineering program that, done first or done simultaneously, will consume most of the effort before a single research-quality improvement ships. The phased plan in §52 already senses this (Phase 1-3 are pipeline work, Phase 4-8 are platform work) — this analysis takes that instinct and hardens it into the architecture recommendation in §6.

## 2. Contradictions and unnecessary complexity identified

The brief explicitly asked for this ("identify contradictions or unnecessary complexity") — these are load-bearing findings, not nitpicks.

| # | Tension | Detail | Resolution proposed |
|---|---|---|---|
| C1 | "Everything must run on one developer laptop" (§23) vs. the full stack listed in the same section | Neo4j CE + Qdrant + Postgres + MinIO + Temporal + MLflow + Langfuse (+ its own Postgres/ClickHouse) + Keycloak + OPA + Prometheus + Grafana, run concurrently, is realistically **8-14 GB of container RAM** before the app or an IDE is open. Docker Desktop on Windows adds its own WSL2 VM overhead on top. | §24's Compose *profiles* already point at the fix — but the brief still implies "core" (frontend+api+postgres+minio+qdrant+mlflow) is needed from day one. It isn't. Recommendation: Phase 1-2 need **zero** of these — SQLite + local filesystem is sufficient until Phase 3 (embeddings/retrieval) genuinely needs Qdrant, and Phase 4 genuinely needs Postgres/MinIO for the artifact registry. Stand up infrastructure the phase in front of you needs, not the platform's eventual full shape. |
| C2 | "Minimize LLM use, run primarily locally" (§13-14) vs. "the only current external LLM dependency should be the free NVIDIA API" | Not a real contradiction, but the brief conflates two different locality axes: *inference locality* (NVIDIA is remote/hosted, not local) and *infrastructure locality* (Postgres/Qdrant/Neo4j run on the laptop). Left unresolved, this reads as "run models locally" when the actual constraint is "keep the free hosted API as the only network dependency for LLM calls, and prefer local models only for embeddings/reranking/classification." | Codify explicitly in the AI Architecture (`04-ai-research-architecture.md`) as two distinct properties: **LLM inference = remote (NVIDIA NIM), swappable via `LLMProvider`**; **embeddings/reranking = local (BGE-M3 / BGE-reranker), swappable via `EmbeddingProvider`/`RerankerProvider`.** |
| C3 | MLflow (§23) *and* a bespoke Research Artifact Registry (§18) *and* a Run Manifest (§19) | The brief itself flags "MLflow must NOT replace this registry" but never draws the line of *what MLflow is for* if not experiment/artifact tracking, which is exactly what the bespoke registry also claims to do. Left ambiguous, teams build both and duplicate effort. | Draw the boundary explicitly (also becomes ADR-005): **MLflow tracks model/embedding *training and evaluation* experiments only** (a thin, optional concern — Clinova is not training models). **The Research Artifact Registry (Postgres table + object storage pointer) is the source of truth for all research artifacts** (corpus, graph, gapset, proposalset, report versions) and the **Run Manifest** is one row in that registry per run. MLflow becomes genuinely optional infrastructure, not core — deferred to Phase 4+ only if/when local model fine-tuning is ever in scope. |
| C4 | Full identity/policy stack — Keycloak + OPA + audit (§23, Phase 6) — for a single-researcher local tool | There is no multi-tenant, multi-user, or access-control requirement anywhere else in the brief. Standing up an OIDC identity provider and a policy engine for a system with one user is enterprise-shaped complexity with no corresponding enterprise-shaped need yet. | Correctly sequenced *already* in the brief as Phase 6 (governance), after the research capability is real. This analysis affirms that ordering and recommends it be treated as **conditional**, not committed: build Phase 6 only once there is an actual second user or a compliance requirement driving it, not on a fixed calendar. |
| C5 | Temporal OSS for "durable orchestration" (§23) vs. the existing pipeline being a synchronous, in-process, sequential `dict → dict` filter chain (`app.py` calling `pipeline/*.py` in order) | A durable workflow engine earns its complexity when runs are long-running, need to survive process restarts, need human-in-the-loop pause/resume, or need distributed worker fan-out. The current pipeline is none of those — it runs in one Streamlit session in minutes. Introducing Temporal in Phase 1-3 would mean learning and operating a workflow engine before there is a durability problem to solve. | Defer Temporal to the phase where a real trigger exists: multi-provider search fan-out with retries at scale (Phase 3, Gap Challenger) or scheduled/background runs (Phase 4+). Until then, the existing pipes-and-filters orchestration in `app.py` (already an accepted, working paradigm per the current `ARCHITECTURE-SPINE.md`) continues, wrapped by a **Run Manifest recorder**, not replaced by a workflow engine. Recorded as ADR-003. |
| C6 | Full Next.js/React enterprise UI shell (§23, §28-46: 15+ pages) specified before a single backend capability (evidence objects, graph QA, gap challenger) exists | Building a 15-screen enterprise frontend against a backend that doesn't yet produce evidence objects, quality scores, or challenger results means the UI is built against placeholder/mock data, then substantially reworked once real data shapes exist. This is the classic frontend-first risk. | UX specification (`02-ux-specification.md`) is produced now (information architecture, screen inventory, design system) so backend contracts are designed UI-aware from the start — but **frontend implementation does not start until Phase 5**, after Phases 1-3 have real evidence/gap/challenger data to design real screens against, per the brief's own phasing. Streamlit continues to serve as the working UI through Phases 0-4 (with the already-in-flight light-theme restyle in the baseline import) so there is a usable app at every phase, not a dark period with no UI at all. |
| C7 | Product name "Clinova Research Intelligence Platform" hard-required to not affect code (§1) | Straightforward, but worth stating as a binding rule now: no source file, table name, cache key, environment variable, or package name may contain "Clinova," "ResGap," or any brand string. | Branding lives in exactly one place: a config/theme layer (`packages/branding/` — name, tagline, palette, logo). The engine keeps its neutral internal name. Recorded as a Consistency Convention in every architecture doc. |
| C8 | Two different taglines in play | The user's direct instruction (this conversation) sets the tagline as **"Evidence → Gaps → Hypotheses → Studies."** The pasted brief's own landing-page copy (§27) proposes a *different* marketing headline, **"Find the research nobody has done yet,"** plus separate supporting copy. | Not a conflict — a product can carry both: **"Evidence → Gaps → Hypotheses → Studies"** is the tagline (used in the nav header, footer, exports, reports — the structural promise). **"Find the research nobody has done yet"** is landing-page hero copy (marketing voice, used once). Both are captured verbatim in the UX spec's content model, not silently dropped. |
| C9 | "False novelty is worse than missing a gap" (§21) vs. an 11-status gap lifecycle with both `LIKELY_CLOSED`/`CLOSED` and `CONTESTED`/`PARTIALLY_OPEN` (§11) | Not a contradiction, but under-specified: nothing in the brief states the actual decision rule for collapsing search+evidence signals into one of 11 statuses, which is exactly the kind of thing that produces silent inconsistency between the Gap Challenger's internal logic and what the UI displays. | Made explicit and testable in the AI/Research Architecture (`04-ai-research-architecture.md`) as a deterministic state-transition table, and used as the anchor scenario for the **False Novelty Rate** benchmark metric (§21-22) from day one of Phase 3. |

## 3. Current system — component disposition (retain / refactor / replace / deprecate)

This assessment is based on direct inspection of the baseline import (`app.py`, `pipeline/*.py`, `utils/*.py`) plus the already-completed Epic 1-3 work and its `deferred-work.md` findings log.

| Component | File(s) | Disposition | Rationale |
|---|---|---|---|
| PDF parsing | `pipeline/pdf_parser.py` | **Refactor** | Single-parser (pdfplumber/PyMuPDF) extraction with no reconciliation or completeness scoring — exactly Problem A. Becomes one input to the new multi-parser reconciliation stage (Phase 1), not replaced outright — its output shape is a reasonable starting schema. |
| Hierarchical paper understanding | `pipeline/page_index.py` | **Retain, wrap** | PageIndex concept is sound and reusable as the section/page provenance backbone that Evidence Objects (§8) need. Extend with confidence/source metadata, don't rewrite. |
| Wiki-style synthesis | `pipeline/wiki_compiler.py` | **Retain as UI convenience, demote as source-of-truth** | Already cached (Story 2.1). Keep for human-readable summaries, but Evidence Objects (Phase 2) — not the wiki text — become what the graph and gap engine read. This is the literal fix for Problem A ("do not use summaries as the only scientific source of truth," §8). |
| Reference extraction | `pipeline/reference_extractor.py` | **Refactor** | Already has enrichment caching (Story 2.3) and API resilience (Story 2.5), but its own code review already logged the exact Problem B risk verbatim: *"title-only cache identity risks silent cross-reference collisions... whichever is enriched first silently and permanently donates its DOI/abstract/authors to every other reference with that title."* This becomes the seed of the Canonical Reference Resolution architecture (§6, ADR-007) — the gap was already found, not newly invented by this brief. |
| Knowledge graph | `pipeline/graph_builder.py` | **Refactor now, replace persistence layer in Phase 3** | Already distinguishes LLM-call-failure from genuine-empty (Story 1.3) and never caches the fallback. Missing entirely: graph versioning, quality score, coverage metrics (Problem E) and Neo4j persistence (currently in-memory/NetworkX-shaped, per architecture spine). Logic mostly survives; persistence and quality-scoring are additive. |
| Gap detection | `pipeline/gap_detector.py` | **Replace with hybrid engine** | Currently a single LLM-prompt-driven detector. Brief's Hybrid Gap Engine (§10 — deterministic patterns + graph reasoning + semantic reasoning + contradiction analysis) is a genuine architectural upgrade, not a refactor. The deterministic pattern library (missing external validation, single-center, no fairness testing, etc.) is new, additive, and delivers value even before the graph/semantic layers land. |
| Academic search / gap validation | `pipeline/academic_search.py` | **Refactor into Gap Challenger** | Already has raise-on-failure + tenacity retry (Story 2.5) and fixed arXiv query construction (Story 2.6) — i.e., Problem D's most acute case (arXiv OR-bug) and part of Problem D's "swallowed failure ≠ open" issue are **already fixed** in the baseline. What's missing is query planning/expansion, multi-provider union+dedup+rerank, and the state machine in §11 — additive, not a rewrite of what's there. |
| Parameter extraction | `pipeline/param_extractor.py` | **Retain** | Confidence-gated (Story 3.1), cached (Story 2.2). Feeds the simulation engine; largely sound as-is. |
| Simulation / computational modelling | `pipeline/simulation_engine.py`, `pipeline/pooling.py` | **Retain** | Random-effects (DerSimonian-Laird) pooling with confidence gating (Story 3.2, Story 3.1) is already statistically sound and has its own unit tests (`tests/test_pooling.py`, `tests/test_simulation_confidence_gate.py`). No brief requirement asks for more here. |
| LLM council / multi-run reasoning | `pipeline/llm_council.py`, `pipeline/multi_run.py` | **Refactor into Small Specialized Agents** | The 4-model roster concept maps directly onto §15's "Research Council" (Gap Generator / Novelty Critic / Methodology Critic / Research Chair) — rename and re-scope, add typed I/O + token budgets + prompt versioning (§15-16), don't discard the tuned per-model configs already in place. |
| Discovery engine | `pipeline/discovery_engine.py` | **Retain, re-scope** | Needs inspection against the Search Planner (§12) during Phase 3 detailed design — likely subsumed into query planning/expansion rather than kept as a separate concept. |
| Doc/report generation | `pipeline/doc_generator.py`, `utils/export.py` | **Refactor** | HTML/PDF generation logic is retained; report *content* changes substantially once Evidence Objects, quality gates, and run manifests exist (Phase 2 report-accuracy gap already logged in `deferred-work.md`: report shows pre-filter parameter counts). |
| LLM client boundary | `utils/azure_client.py` | **Retain** | Already the exact pattern §16 asks for: `Result[str, ErrorInfo]` return type (Story 1.1-1.2), streaming, reasoning-token discarding. Becomes the concrete implementation behind the new `LLMProvider` port (ADR-004) — interface extraction, not rewrite. |
| Persistence | `utils/database.py` | **Replace (SQLite → Postgres) starting Phase 4; extend schema through Phase 1-2 first** | SQLite is fine through Phase 1-3 (no concurrent-user requirement exists yet — already an explicit deferred/accepted limitation in the current architecture spine). Migrate to Postgres only when the Artifact Registry (§18) and multi-run comparison (§20, §41) need relational integrity and concurrent access the current single-blob-per-run model doesn't provide. |
| UI | `app.py` (Streamlit) | **Retain through Phase 0-4, replace in Phase 5** | Per C6 above — kept as the working interface while backend capability is built, replaced by the Next.js shell only once there's real data to design screens against. |
| Domain configuration | `domain_config.py` | **Retain, extend** | The domain-extension pattern (`DOMAINS` dict, `inject_domain_into_*`) is exactly the kind of pluggable-without-code-change design the enterprise brief wants elsewhere (providers, branding) — a positive precedent to replicate, not replace. |

**Bottom line:** roughly **60% of the existing pipeline logic is retained or lightly refactored**, not rewritten. The genuinely new architecture is: multi-parser reconciliation, canonical reference/paper identity, evidence objects with provenance, graph quality scoring + Neo4j persistence, the hybrid gap engine, the Gap Challenger state machine, provider abstractions, versioning/lineage/registry/manifest, and the enterprise UI. This scoping directly informs the phase-1 recommendation in §8.

## 4. Known weaknesses — brief's Problems A-F cross-referenced against what Epics 1-3 already found

No generated Clinova report exists yet to analyze directly (Phase 0 action item — see §8). But the *existing* ResGap codebase already went through one BMAD hardening pass (Epics 1-3, complete 2026-08-05), and its own code-review trail is a real, evidence-based weaknesses inventory that substantially overlaps with the brief's Problems A-F. This is a significant finding: **the brief is not describing hypothetical problems — it is describing problems this project already started fixing**, with a documented paper trail.

| Brief problem | Status in baseline | Evidence |
|---|---|---|
| **A — Data loss** (PDF → parser → summary → wiki → graph → gap analysis) | **Not addressed.** No completeness scoring, no multi-parser reconciliation exists anywhere in the baseline. | Confirmed absent by direct inspection — genuinely new work, becomes Phase 1's core scope. |
| **B — Reference contamination** | **Partially addressed, and the exact failure mode is already documented.** Title-collision risk in the reference cache is a *known, named, accepted* limitation. | `deferred-work.md`, Story 2.3 review: *"two genuinely different papers sharing an exact title... collide on the same `cache_key`; whichever is enriched first silently and permanently donates its DOI/abstract/authors."* This is Problem B stated in the project's own words before this brief existed. |
| **C — Over-reliance on fallback** | **Partially addressed for one path.** The knowledge-graph fallback is already distinguished from genuine-empty (Story 1.3) and never cached as if real (AD-2). No `VERIFIED/ACCEPTED/QUARANTINED/UNRESOLVED/REJECTED` status model exists anywhere yet — that's net-new. | `_bmad-output/planning-artifacts/architecture/.../ARCHITECTURE-SPINE.md` AD-2; Story 1.3. |
| **D — Missing academic search results treated as "gap is open"** | **The most acute instance is already fixed; the general problem is not.** The arXiv OR-vs-AND bug that was "confirmed, live-reproduced" (returning a CMB polarisation paper for a Mendelian Randomization/ADHD query) is fixed (Story 2.6). Silent-failure-as-empty-result is fixed for HTTP-level failures (Story 2.5). But there is still no search *coverage/quality* measurement, and no state machine that distinguishes `SEARCH_PENDING`/`INSUFFICIENT_EVIDENCE` from `OPEN`. | Stories 2.5-2.6; `deferred-work.md` 2.4 entry explicitly recommends "Story 2.5 should consider bumping `GAP_VALIDATION_STAGE_VERSION`... to invalidate any bad 'open' entries cached before search resilience existed" — i.e., the project already knows old cached "open" gaps may be wrong for this exact reason. |
| **E — Knowledge-graph quality** | **Not addressed.** No graph version, quality score, coverage/duplicate/unresolved-entity metrics exist. | Confirmed absent by inspection — net-new, Phase 3 scope. |
| **F — LLM nondeterminism** | **Not addressed as a measured property**, though some prerequisite plumbing exists (typed Result boundary, streaming with reasoning discarded, per-model tuned configs in `llm_council.py`). No prompt/model versioning, no repeatability score, no run manifest. | Confirmed absent by inspection — net-new, Phase 4 scope, but built on top of an LLM client boundary (`azure_client.py`) that already returns typed results rather than sentinel strings, which is the right foundation for it. |

**Implication for phasing:** Problem B (reference contamination) and Problem D (search validity) have partial fixes in place and known, documented failure modes — they are the **highest-leverage, lowest-risk starting point** for Phase 1, not a cold start. Problems A, E, and F are genuinely greenfield within this codebase.

## 5. Three target architecture options

### Option A — Minimal Local-First Evolution
Keep Streamlit + SQLite + in-process pipeline indefinitely. Add: multi-parser reconciliation, canonical reference resolution, evidence objects (stored as structured JSON in SQLite, not a graph DB), a rule-based gap-status state machine, deterministic gap patterns, and a lightweight run-manifest table. No Neo4j, no Postgres, no vector DB, no new frontend, no Temporal/MLflow/Langfuse/Keycloak/OPA. Graph reasoning done in-process with NetworkX only (no persistence beyond a versioned JSON/GraphML export per run).

- **Complexity:** Lowest. One language (Python), one process, one datastore family (SQLite + filesystem).
- **Laptop resources:** Trivial (<500MB beyond the Python process itself).
- **Cloud portability:** Poor. SQLite and an in-process Streamlit app don't containerize into a multi-service cloud deployment without substantial rework later — the hexagonal ports (§25) would need to be retrofitted, not designed-in.
- **Scientific rigor:** Can reach parity on Problems A-D and F (data loss, contamination, fallback trust, search validity, nondeterminism bounding) since those are pipeline-logic problems, not infrastructure problems. Problem E (graph quality) is achievable in reduced form — quality *scoring* doesn't require Neo4j, but genuinely large/cross-project graph queries would strain NetworkX-in-memory at scale.
- **Maintainability:** High short-term (small surface area), but every enterprise capability in §17-46 (versioning UI, compare, lineage, champion/challenger, governance) would eventually need to be bolted onto an architecture that was never designed for them — likely a second rewrite later.

### Option B — Full Enterprise Stack (brief as literally specified)
Build all of §23 concurrently or near-concurrently: Next.js/FastAPI, Postgres, MinIO, Qdrant, Neo4j CE + NetworkX, Temporal, MLflow, Langfuse, Keycloak, OPA, OpenTelemetry, Prometheus/Grafana, Docker Compose profiles, all 15 UI screens, full versioning/lineage/registry/manifest/champion-challenger system, from the start.

- **Complexity:** Highest. 10+ services, 2 languages (Python + TypeScript), 4 datastore technologies (relational, object, vector, graph), a workflow engine, an identity provider, a policy engine — before a single new research-quality capability ships.
- **Laptop resources:** Heavy, per C1 above — realistically requires a dedicated dev machine or careful profile discipline that the option's own "build it all" framing works against.
- **Cloud portability:** Excellent — this *is* the target cloud-portable shape, designed hexagonally from day one.
- **Scientific rigor:** No inherent advantage over Option A or C on the actual scientific-integrity problems (A-F) — those are solved by pipeline logic, not by which datastore or orchestrator sits underneath it. Risk: platform-building consumes the time budget that should go to the scientific fixes, and the scientific fixes ship *later*, not better.
- **Maintainability:** Poor in the near term (large surface area, mostly idle/unexercised infrastructure for months), good in the long term once genuinely at multi-user/enterprise scale — but that scale doesn't exist yet (single researcher, local laptop, per the brief's own §23 premise).

### Option C — Staged Hybrid: Phase-Gated Platform Growth (recommended)
Same **end-state architecture as Option B** — hexagonal ports/adapters, all the same interfaces (`ObjectStore`, `VectorStore`, `GraphStore`, `LLMProvider`, `EmbeddingProvider`, `RerankerProvider`, `SearchProvider`, `SecretProvider`, `IdentityProvider`, `ArtifactRegistry`) defined from Phase 1 onward — but **each piece of infrastructure is introduced only in the phase whose capability genuinely requires it**, with a local/degraded adapter (SQLite, filesystem, NetworkX, no-op auth) satisfying the same port until then. Concretely:

- Phase 0-1 (Data Foundation): SQLite + filesystem only. No new services.
- Phase 2 (Evidence Foundation): still SQLite + filesystem — evidence objects are structured JSON rows with provenance columns.
- Phase 3 (Reliable Research Intelligence): **first new infra** — Qdrant (embeddings/reranking need real vector search at this point) and Neo4j CE (graph quality/cross-paper reasoning genuinely needs graph queries here). NetworkX remains for in-process algorithms.
- Phase 4 (Versioned Platform): Postgres (replaces SQLite for the Artifact Registry — this is where relational integrity and concurrent runs start to matter) + MinIO (object storage for large artifacts). MLflow only if/when a real experiment-tracking need appears (see C3) — not committed by default.
- Phase 5 (Enterprise UI): Next.js/FastAPI shell — built against real Phase 1-4 data contracts, not mocks.
- Phase 6 (Governance): Keycloak + OPA — only triggered by an actual second user or compliance need (see C4), otherwise this phase stays unscheduled.
- Phase 7 (Observability): OpenTelemetry + Prometheus + Grafana + Langfuse — once there's enough running system to observe.
- Phase 8 (Portability): OpenTofu + Kubernetes/Helm — cloud deployment only, no change to research logic (as the brief itself specifies).

- **Complexity:** Grows monotonically but always matched to a real, currently-shipping capability — never idle infrastructure.
- **Laptop resources:** Bounded at every phase to what that phase needs; Compose profiles (§24) map 1:1 to phases rather than being an afterthought.
- **Cloud portability:** Equal to Option B — same hexagonal interfaces, same end state, just built when needed instead of upfront.
- **Scientific rigor:** Equal to Option A through Phase 1-2 (same pipeline-logic fixes, same timeline), then *exceeds* Option A from Phase 3 onward because graph quality and vector retrieval get real infrastructure instead of an in-memory approximation, without having paid Option B's upfront tax.
- **Maintainability:** Best of the three — no idle services, no infrastructure whose purpose developers have to re-learn months after standing it up, and no forced second rewrite the way Option A eventually risks.

### Comparison matrix

| Dimension | A — Minimal Local | B — Full Enterprise Upfront | C — Staged Hybrid |
|---|---|---|---|
| Time to first scientific-quality improvement (Phase 1 done) | Fastest | Slowest (platform work blocks it) | Fast (same as A) |
| Laptop RAM at Phase 1 | ~0.5 GB | ~8-14 GB | ~0.5 GB |
| Laptop RAM at full build-out | ~0.5-1 GB (never grows) | ~8-14 GB (from day one) | ~8-14 GB (only once, at the phase that needs it) |
| Cloud portability designed-in | No (retrofit risk) | Yes | Yes |
| Risk of a second rewrite | High (Option A eventually needs B's shape) | Low | Low |
| Risk of wasted/idle infrastructure | None | High (months of unused services) | Low |
| Matches brief's own §52 phased plan | No (ignores it) | No (contradicts it — "build it all" vs. phases) | Yes (this *is* §52, made concrete) |

## 6. Recommendation

**Option C — Staged Hybrid.** It delivers Option A's speed on the scientific-integrity problems (which is where the actual product value and the brief's own stated priority — "false novelty" as the most important metric, §21 — live) while building toward Option B's exact end-state architecture, so nothing done in Phase 1-2 is thrown away later. It is also, concretely, what the brief's own §52 phasing already describes — this recommendation formalizes that plan as the binding architecture decision rather than leaving it as a soft suggestion that competes with §23's "build the full stack" framing.

This becomes **ADR-000** (see `adr/` — recorded once the ADR set is finalized in this same planning pass) and is the load-bearing decision every other architecture document in this planning set assumes.

## 7. Self-challenge: red-teaming the Option C recommendation

**Steelman Option B (full stack upfront):** "Staging the build risks the ports/adapters being designed wrong in Phase 1 because there's no real Postgres/Qdrant/Neo4j implementation to validate the interface against — you're designing `VectorStore` against an imagined future consumer instead of a real one, and you'll get it wrong and have to change it in Phase 3 anyway." — **Response:** True risk, mitigated, not eliminated: the port interfaces are defined in Phase 1 (per Option C's own description) with a real, working adapter behind them (SQLite/filesystem/NetworkX) — not an untested stub. That adapter has to actually satisfy real callers (the reconciliation engine, the reference resolver) from day one, which is a legitimate validation of the interface shape even without Qdrant/Neo4j specifically behind it yet. Residual risk accepted: some interface rework at the Phase 3 boundary is likely and should be budgeted for, not treated as a sign the staged approach failed.

**Steelman Option A (never build the platform):** "Once Phase 1-2 ship real scientific value on SQLite, there will be organizational pressure to just keep going on SQLite indefinitely — 'staged' quietly becomes 'never,' and the enterprise UI/versioning/governance work described in §17-49 (which the user explicitly asked for) never happens." — **Response:** This is the most credible objection. Mitigation: each phase transition in the Phased Implementation Plan (`10-phased-implementation-plan.md`) is written as a **gate with an explicit trigger condition** ("Phase 4 begins when the Artifact Registry needs concurrent-run relational integrity that SQLite's single-blob-per-run model can't provide" — a condition already true today, actually, per `project-context.md`'s own documented gap), not an open-ended "later." The RESUME.md index and sprint-status tracking make the plan's existence and next-gate impossible to silently forget between sessions.

**What could concretely go wrong with Option C specifically:**
- *Two migrations instead of one* (SQLite→Postgres at Phase 4, in-memory NetworkX→Neo4j at Phase 3) costs real engineering time that Option B pays once, upfront. Accepted trade — the alternative (Option B) pays a *guaranteed* large upfront cost for a *possible* future need; Option C pays a smaller, deferred cost only when the need is confirmed real.
- *Provider abstraction overhead in Phase 1* — defining `GraphStore`/`VectorStore` interfaces before there's a second implementation to prove they're not over-fit to NetworkX/nothing is a known anti-pattern (speculative abstraction) the project's own engineering conventions warn against (`CLAUDE.md`-equivalent guidance: "no abstractions beyond what the task requires"). **Correction applied:** Phase 1-2 do **not** define `VectorStore`/`GraphStore` ports yet — those are introduced at Phase 3 when Qdrant/Neo4j land, built against two real reference points (NetworkX's actual usage pattern + Neo4j's actual usage pattern) rather than one imagined one. Only `LLMProvider`/`EmbeddingProvider` are ported early, because `azure_client.py` already has two years of a de facto second implementation's worth of usage patterns to design against (the existing NVIDIA NIM wrapper plus the brief's own stated future providers). This is reflected in `03-system-architecture.md`'s phase-by-phase interface introduction table, not front-loaded into a single "ports" epic.

## 8. What this analysis unblocks

With this document as the accepted baseline (pending your review), the remaining planning artifacts in this pass are:

- `01-prd.md` — Product Requirements Document
- `02-ux-specification.md` — UX/Product Design specification
- `03-system-architecture.md` — Enterprise System Architecture (hexagonal ports, phase-gated per §6)
- `04-ai-research-architecture.md` — AI/Research Architecture (providers, agents, hybrid gap engine, Gap Challenger, determinism envelope)
- `05-data-architecture.md` — Data Architecture (schemas, canonical identity, evidence objects, corpus quality engine)
- `06-versioning-lineage-architecture.md` — Versioning/Lineage/Registry/Manifest architecture
- `07-evaluation-architecture.md` — Evaluation architecture (Clinova benchmark, false-novelty rate, champion/challenger)
- `08-local-deployment-architecture.md` — Local deployment architecture (Compose profiles mapped to phases)
- `adr/ADR-001` through `ADR-008`
- `09-epics-and-stories.md` and `10-phased-implementation-plan.md`

One explicit Phase 0 action item surfaced by this analysis, not yet done: **no sample Clinova report exists to analyze** (§55 asked for "analyze the existing generated report"). The closest available artifact is the *ResGap* pipeline's own report generator (`pipeline/doc_generator.py`) and its already-logged accuracy gap (pre-filter parameter counts, `deferred-work.md`). Recommend generating one real baseline report from the existing pipeline against a small real corpus as the first concrete Phase 0 task, so Phase 1's completeness/contamination fixes have a measured "before" to compare against — this becomes the seed of the Clinova benchmark (`07-evaluation-architecture.md`).
