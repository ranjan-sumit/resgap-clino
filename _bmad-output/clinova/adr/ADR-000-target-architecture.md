# ADR-000: Target architecture — Staged Hybrid (Option C)

**Status:** Accepted
**Date:** 2026-08-20
**Deciders:** BMAD planning pass (Business Analyst, Enterprise Architect roles)
**Supersedes:** none

## Context

The enterprise brief specifies a full platform stack (Next.js/FastAPI, Postgres, MinIO, Qdrant, Neo4j, Temporal, MLflow, Langfuse, Keycloak, OPA, OpenTelemetry/Prometheus/Grafana) as if it should be built from day one (§23), while separately stating the system "must run on one developer laptop" and proposing an 8-phase rollout (§52) that itself only introduces platform capability gradually. These two framings are in tension. Three target architectures were evaluated in `00-analysis-and-architecture-options.md` §5: (A) minimal local-first evolution with no new infrastructure, (B) the full stack built upfront, (C) a staged hybrid — same end-state hexagonal architecture as B, but each piece of infrastructure introduced only in the phase whose capability genuinely requires it.

## Decision

Adopt **Option C**. Hexagonal ports (`ObjectStore`, `VectorStore`, `GraphStore`, `LLMProvider`, `EmbeddingProvider`, `RerankerProvider`, `SearchProvider`, `SecretProvider`, `IdentityProvider`, `ArtifactRegistry`) are defined as the binding target shape from the start, but each port's real (non-local) adapter is only built when a second genuine implementation exists to design against — see `03-system-architecture.md` AD-2's phase-by-phase introduction table.

## Consequences

- Phase 1-2 ship on SQLite/filesystem/NetworkX with zero new infrastructure — fastest possible path to the scientific-integrity fixes (Problems A-F), which is where the brief's own stated top priority (False Novelty Rate, §21) lives.
- Two migrations are accepted as a cost: SQLite→Postgres at Phase 4, in-memory NetworkX→Neo4j-backed at Phase 3. This is a known, budgeted trade-off, not an oversight — see `00-analysis-and-architecture-options.md` §7 for the full risk analysis.
- Governance (Keycloak/OPA) and durable orchestration (Temporal) are conditional on real triggers (a second user; a durability need), not scheduled dates — there is a real risk this becomes "never" under organizational pressure; mitigated by writing each phase gate as an explicit, checkable trigger condition in `10-phased-implementation-plan.md`, not an open-ended "later."

## Alternatives considered

- **Option A (minimal, never build the platform):** rejected as the sole path — does not deliver the enterprise capabilities (versioning UI, compare, lineage, governance) the user explicitly asked for; retained instead as Option C's Phase 1-2 shape.
- **Option B (full stack upfront):** rejected as the starting point — front-loads ~8-14GB of infrastructure and multi-service operational complexity before any scientific-quality improvement ships, and duplicates the brief's own §52 phased intent.
