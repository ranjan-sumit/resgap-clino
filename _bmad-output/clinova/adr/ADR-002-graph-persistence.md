# ADR-002: Graph persistence — Neo4j CE + NetworkX hybrid

**Status:** Accepted (pending user review)
**Date:** 2026-08-20
**Deciders:** BMAD planning pass (Enterprise Architect, Data Architect roles)

## Context

The existing pipeline builds an in-memory (NetworkX-shaped, per the current codebase's architecture) knowledge graph per run, with no persistence, versioning, or cross-run querying. The brief (§9) asks for graph-based reasoning to surface cross-paper research gaps and specifies evaluating Neo4j CE, NetworkX, or a hybrid.

## Decision

Adopt **Neo4j CE for persisted, versioned, cross-run graph storage + NetworkX for in-process algorithmic operations** (path-finding, sparsity/centrality analysis feeding the Hybrid Gap Engine's graph-structural-reasoning signal), introduced together at Phase 3 (`03-system-architecture.md` AD-2) — this is the one port introduced with two real implementations from day one, since both are needed simultaneously (persistence vs. algorithm execution are different jobs).

## Consequences

- Graph version, quality score, and coverage metrics (`01-prd.md` FR-7) require a persisted, queryable store — NetworkX alone (in-memory, per-run) cannot support "Compare Graph Version" (`02-ux-specification.md` §5 row 5) across runs.
- Neo4j CE is free/open-source, satisfying the local-first requirement; its resource cost (JVM-based) is accounted for in the `research` Compose profile (`08-local-deployment-architecture.md`).
- Every graph edge written to Neo4j must carry a provenance reference to an Evidence Object (`05-data-architecture.md` §8-9) — enforced at the write layer, not left to convention.

## Alternatives considered

- **NetworkX only, with versioned GraphML/JSON exports instead of a graph database:** this is Option A's (`00-analysis-and-architecture-options.md`) approach — viable for Phase 1-2 quality-scoring, but does not scale to genuine cross-project/cross-run graph queries (e.g., "find all papers studying dataset X across every project") once the corpus grows, which is exactly the cross-paper reasoning the brief's Hybrid Gap Engine depends on.
- **Neo4j only (drop NetworkX):** rejected — NetworkX remains valuable for algorithmic operations that don't need persistence and are cheaper to run in-process than as Cypher queries; no reason to pay a network round-trip for every graph-algorithm call.
