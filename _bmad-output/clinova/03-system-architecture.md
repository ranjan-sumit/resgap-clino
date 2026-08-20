---
name: 'Clinova Research Intelligence Platform — System Architecture'
type: architecture-spine
purpose: build-substrate
altitude: enterprise
paradigm: 'hexagonal ports-and-adapters, wrapping an existing pipes-and-filters research pipeline'
scope: 'End-to-end technical architecture for Clinova: repository structure, service boundaries, hexagonal interfaces introduced phase-by-phase, branding independence, dependency rules, and the local-first-to-cloud-portable stack.'
status: draft-for-review
created: '2026-08-20'
binds: ['00-analysis-and-architecture-options.md (Option C, ADR-000)']
sources: ['00-analysis-and-architecture-options.md', '01-prd.md', 'existing Research_Gap_Analyzer ARCHITECTURE-SPINE.md (inherited pipes-and-filters paradigm)']
companions: ['04-ai-research-architecture.md', '05-data-architecture.md', '06-versioning-lineage-architecture.md', '08-local-deployment-architecture.md', 'adr/*']
---

# System Architecture — Clinova Research Intelligence Platform

## Design paradigm

**Hexagonal (ports-and-adapters) wrapping the existing pipes-and-filters pipeline.** The inherited pipeline (`app.py` orchestrating dict-in/dict-out `pipeline/*.py` filter stages) is not replaced — per `00-analysis-and-architecture-options.md`'s Option C recommendation, it is preserved as the execution model, and hexagonal ports are introduced **only at the boundaries where a second real implementation exists to design against**, phase by phase (§3 below), never speculatively.

```mermaid
graph LR
  ui[Next.js UI<br/>Phase 5] --> api[FastAPI<br/>Phase 5]
  api --> engine[Research Engine<br/>pipeline/* filters]
  engine --> ports{{Hexagonal Ports}}
  ports --> llm[LLMProvider]
  ports --> emb[EmbeddingProvider / RerankerProvider]
  ports --> search[SearchProvider x N]
  ports --> obj[ObjectStore]
  ports --> vec[VectorStore]
  ports --> graph[GraphStore]
  ports --> registry[ArtifactRegistry]
  llm -.Phase 1.-> nvidia[NVIDIA NIM]
  vec -.Phase 3.-> qdrant[Qdrant]
  graph -.Phase 3.-> neo4j[Neo4j CE]
  registry -.Phase 4.-> pg[(Postgres)]
```

## Invariants & rules

### AD-1 — Dependency direction (inherited, extended)
- **Binds:** all modules.
- **Rule:** `packages/research-engine/*` (the evolved `pipeline/*.py`) may import shared infrastructure (`packages/contracts/*`, i.e. the port interfaces) but never the reverse; port **implementations** (adapters) depend on the port interface, never on engine code; `apps/api` depends on `packages/research-engine`, never the reverse; `apps/web` depends only on `packages/contracts` (typed API contracts), never directly on engine internals. Identical in spirit to the existing project's `utils/*.py`-never-imports-`pipeline/*.py` rule, generalized to the new monorepo shape.

### AD-2 — Phase-gated port introduction (this is the concrete form of Option C)
- **Binds:** every hexagonal interface listed in the brief (§25): `ObjectStore`, `VectorStore`, `GraphStore`, `LLMProvider`, `EmbeddingProvider`, `RerankerProvider`, `SearchProvider`, `SecretProvider`, `IdentityProvider`, `ArtifactRegistry`.
- **Prevents:** speculative abstraction — an interface designed against zero or one real implementation, later found to be wrong-shaped once a second implementation arrives (`00-analysis...` §7).
- **Rule:** a port is only introduced in the phase where a second real adapter is being built for it. Until then, callers use the concrete local implementation directly (SQLite, filesystem, NetworkX, no-op auth).

| Port | First introduced | Adapters at introduction | Rationale |
|---|---|---|---|
| `LLMProvider` | Phase 1 | NVIDIA NIM (wraps existing `azure_client.py`) | Already has a de facto second-implementation-shaped usage history (per-model tuned configs in `llm_council.py`) — safe to interface-extract now. |
| `EmbeddingProvider` / `RerankerProvider` | Phase 3 | BGE-M3, BGE-reranker (local) | Introduced exactly when Qdrant-backed retrieval needs them — no earlier consumer exists. |
| `SearchProvider` | Phase 1 (existing academic_search.py providers) → formalized Phase 3 | Semantic Scholar, arXiv, CrossRef, OpenAlex, PubMed (existing) + Europe PMC, ClinicalTrials.gov (new) | Multiple real providers already exist today — safe to interface-extract at Phase 1, formalized fully once the Search Planner (Phase 3) needs to add/swap providers dynamically. |
| `VectorStore` | Phase 3 | Qdrant | No consumer before Phase 3's embedding retrieval. |
| `GraphStore` | Phase 3 | NetworkX (in-process, existing) + Neo4j CE (persisted) | Two real implementations from day one of this port's existence — the textbook case for introducing an interface. |
| `ArtifactRegistry` | Phase 4 | Postgres-backed (replaces SQLite `runs`/`papers` tables) | No registry concept exists before Phase 4. |
| `ObjectStore` | Phase 4 | Filesystem (local) + MinIO | Large artifacts (graphs, reports, search snapshots) start needing this once the registry tracks `storage_uri`. |
| `SecretProvider` | Phase 1 (trivial: env vars) → formalized only if Phase 6 governance activates | Env var adapter | No secrets-management need beyond API keys exists before governance. |
| `IdentityProvider` | Phase 6 (conditional) | Keycloak | Not built until a real second user exists — see PRD FR-33. |

### AD-3 — Branding layer (binding, PRD NFR-1)
- **Binds:** `apps/web`, report generation (`packages/research-engine` doc generator), all user-facing strings.
- **Rule:** product name, tagline, palette, and logo live in exactly one config module (`packages/branding/theme.json` + `packages/branding/copy.ts`). No other module references "Clinova," "ResGap," or any brand string literally. The engine's internal name is `resgap-core` (neutral, never user-facing).

### AD-4 — Pipeline execution model unchanged through Phase 4
- **Binds:** `packages/research-engine/*` (evolved `pipeline/*.py`).
- **Rule:** the sequential, in-process filter-chain execution model is retained through Phase 4. A durable workflow engine (Temporal) is deferred until a real durability/fan-out trigger exists (`00-analysis...` C5) — recorded as ADR-003.

### AD-5 — Registry vs. experiment tracking boundary (resolves `00-analysis...` C3)
- **Binds:** `ArtifactRegistry` (Phase 4) vs. any future MLflow integration.
- **Rule:** the Research Artifact Registry (Postgres) is the source of truth for all research artifacts and run manifests — always present from Phase 4 onward. MLflow, if ever introduced, is scoped strictly to model/embedding *training and evaluation* experiments (not corpus/graph/gap/proposal artifacts) and is optional, triggered only by an actual local fine-tuning need. Recorded as ADR-005.

### AD-6 — Governance is conditional, not scheduled
- **Binds:** Phase 6 (Keycloak, OPA, audit).
- **Rule:** Phase 6 has no calendar date. Its trigger condition (recorded in `10-phased-implementation-plan.md`) is "a real second user or an actual compliance requirement exists" — until then, `IdentityProvider`/policy enforcement stay unimplemented, not stubbed.

## Repository structure

Adapted from the brief's proposed monorepo (§50), validated against the phase-gating rule above — folders are created in the phase that needs them, not all upfront:

```text
Research_Gap_Analyzer_V1/
  apps/
    web/                      # Next.js/React/TS — created Phase 5
    api/                      # FastAPI — created Phase 5 (thin layer over research-engine)
  packages/
    research-engine/          # evolved pipeline/*.py — created Phase 1, grows through Phase 4
      parsing/                # multi-parser reconciliation — Phase 1
      identity/                # canonical reference/paper resolution — Phase 1
      evidence/                # evidence objects — Phase 2
      graph/                   # graph builder + quality scoring — Phase 3
      gaps/                    # hybrid gap engine + Gap Challenger — Phase 3
      agents/                  # research council, small specialized agents — Phase 3-4
      simulation/               # pooling.py, simulation_engine.py — retained from baseline
      reporting/                # doc_generator.py evolution — Phase 1, enriched per phase
    contracts/                 # port interfaces (typed) — introduced per AD-2's table
    branding/                  # AD-3 — created Phase 1 (used by Streamlit interim UI too)
    research-schemas/          # evidence/graph/gap JSON schemas — Phase 2
  infra/
    docker/compose/            # profiles mapped to phases — see 08-local-deployment-architecture.md
    helm/                      # Phase 8
    opentofu/                  # Phase 8
  evals/
    benchmarks/                # Clinova Benchmark — Phase 0 seed, Phase 3+ full
    regression/                # champion/challenger harness — Phase 4
  docs/
    architecture/decisions/    # ADRs — this planning pass
  _bmad-output/                # BMAD planning artifacts (this document set) + inherited baseline artifacts
  app.py, pipeline/, utils/, domain_config.py   # RETAINED as-is through Phase 4 (interim UI + engine home
                                                  # until packages/research-engine absorbs pipeline/*.py)
```

**Migration note:** `pipeline/*.py` and `utils/*.py` are not moved into `packages/research-engine/` on day one — they are refactored in place through Phase 1-2 (per the retain/refactor table in `00-analysis-and-architecture-options.md` §3), then physically relocated as part of Phase 4's monorepo consolidation once the shape has stabilized. Moving code before its shape is stable would mean rework; this sequencing avoids that.

## Consistency conventions

| Concern | Convention |
|---|---|
| Naming | Product-facing name never appears in code (AD-3). Internal engine codename: `resgap-core`. Port interfaces named exactly as listed in AD-2's table — no synonyms. |
| Versioning | Every artifact type versioned per `06-versioning-lineage-architecture.md`; SemVer for packages, integer `stage_logic_version` for pipeline-stage cache invalidation (inherited convention from the existing `wiki_pages`/`parameters`/`references`/`gap_validations` cache tables). |
| Data & formats | JSON Schema for all evidence/graph/gap object shapes (`packages/research-schemas`). SHA-256 content hashing throughout (inherited from the existing `content_hash:domain_hash:stage_logic_version` cache-key convention). |
| Error handling | The existing `Result[str, ErrorInfo]` / `LLMCallError` pattern at the LLM boundary (`utils/azure_client.py`) is retained and becomes the reference implementation behind `LLMProvider`. |
| State & cross-cutting | Cache-aside writes only on genuine success (never cache a failure/fallback) — inherited AD-2 rule from the existing architecture spine, carried forward unchanged. |

## Stack (introduced per-phase — see `08-local-deployment-architecture.md` for the Compose-profile mapping)

| Layer | Phase 0-2 | Phase 3 | Phase 4 | Phase 5 | Phase 6-8 |
|---|---|---|---|---|---|
| UI | Streamlit (existing, restyled) | Streamlit | Streamlit | **Next.js + React + TS** | — |
| API | in-process (Streamlit calls `pipeline/*` directly) | in-process | in-process | **FastAPI** | — |
| System DB | SQLite (existing) | SQLite | **Postgres** | Postgres | Postgres |
| Object storage | filesystem | filesystem | **MinIO** | MinIO | MinIO |
| Vector DB | — | **Qdrant** | Qdrant | Qdrant | Qdrant |
| Graph | NetworkX (in-process) | **Neo4j CE + NetworkX** | Neo4j CE + NetworkX | same | same |
| Orchestration | in-process sequential | in-process sequential | in-process sequential | in-process sequential | **Temporal (only if a real trigger exists — AD-4)** |
| Experiment tracking | — | — | (optional, see AD-5) | — | MLflow OSS (conditional) |
| LLM observability | — | — | — | — | Langfuse OSS |
| Identity/policy | — | — | — | — | **Keycloak + OPA (conditional — AD-6)** |
| Telemetry | — | — | — | — | OpenTelemetry + Prometheus + Grafana |
| Packaging | Docker (dev container, existing) | Docker | Docker Compose (`data` profile) | Docker Compose (`core` profile) | Docker Compose (all profiles) → Kubernetes/Helm (Phase 8 only) |

## Deferred (explicitly, not forgotten)

- Kubernetes/Helm, OpenTofu cloud deployment — Phase 8, no earlier trigger exists yet.
- Temporal — deferred per AD-4 until a real durability/fan-out need is observed.
- MLflow — deferred per AD-5 until a real local-fine-tuning need is observed.
- Keycloak/OPA — deferred per AD-6 until a real second user or compliance need exists.
- Multi-region / high-availability concerns — out of scope entirely; single-instance local-first through the end of this plan's visible horizon.
