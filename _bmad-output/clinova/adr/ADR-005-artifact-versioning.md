# ADR-005: Artifact versioning — application-owned registry, MLflow scoped out by default

**Status:** Accepted
**Date:** 2026-08-20
**Deciders:** BMAD planning pass (Enterprise Architect, Data Architect roles)

## Context

The brief specifies both a bespoke Research Artifact Registry (§18) and MLflow OSS (§23) while explicitly stating "MLflow must NOT replace this application registry" — without defining what MLflow is actually for if not that. Left ambiguous, this produces duplicated tracking systems doing the same job. See `00-analysis-and-architecture-options.md` §2, C3.

## Decision

The **Research Artifact Registry** (Postgres-backed, `06-versioning-lineage-architecture.md`) is the single source of truth for all research artifacts (corpus, extraction, evidence, graph, gap set, proposal set, report, benchmark versions) and run manifests — introduced at Phase 4. **MLflow is scoped strictly to model/embedding training and evaluation experiments** and is not part of the default build — it is introduced only if/when a genuine local model fine-tuning need arises (none exists in this plan's current phased scope, since Phase 3's embedding/reranker models are used off-the-shelf, not trained).

## Consequences

- No duplicated tracking system for the same data — every artifact has exactly one authoritative record.
- MLflow's operational cost (an additional service, its own tracking database) is not paid unless a real training/fine-tuning workflow exists to justify it — consistent with the phase-gated infrastructure principle.
- If a future phase does introduce model fine-tuning (not currently planned), this ADR's boundary (MLflow = training/eval experiments only, Registry = research artifacts) still holds without modification.

## Alternatives considered

- **Use MLflow as the artifact registry too (skip the bespoke registry):** rejected — MLflow's data model (runs, experiments, model versions) is not shaped for the brief's specific artifact taxonomy (evidence sets, gap sets, proposal sets, lineage-linked scientific artifacts) and would require significant workarounds to represent scientific lineage (§4 of `06-versioning-lineage-architecture.md`) faithfully.
- **Skip MLflow entirely, forever:** not adopted as a permanent decision — left available as optional, conditional infrastructure per this ADR's decision, not removed from the architecture.
