# ADR-001: Vector database — Qdrant

**Status:** Accepted
**Date:** 2026-08-20
**Deciders:** BMAD planning pass (Enterprise Architect, AI/LLM Architect roles)

## Context

The Gap Challenger's search-and-rerank funnel (`04-ai-research-architecture.md` §5) needs embedding-based retrieval once BGE-M3 embeddings are introduced (Phase 3). The brief specifies Qdrant explicitly (§23); no other vector store was requested, and no existing project code has an opinion here (the current pipeline does no vector retrieval at all).

## Decision

Adopt **Qdrant** as the `VectorStore` port's adapter, introduced at Phase 3 (`03-system-architecture.md` AD-2) — not earlier, since no consumer exists before the Gap Challenger's embedding retrieval stage.

## Consequences

- Open-source, self-hostable, satisfies the local-first requirement (brief §23) and the no-new-infra-technology-beyond-necessity constraint.
- `VectorStore` is a genuinely thin port (index, upsert, search-by-vector, filter) — low risk of interface mis-design even introduced without a second implementation, since the operation set is small and standard across vector DBs generically.

## Alternatives considered

- **pgvector (Postgres extension):** would avoid a fourth datastore technology, and is worth revisiting once Postgres is already running (Phase 4) if Qdrant's operational cost proves unjustified at the project's actual scale. Not selected now because Qdrant is introduced (Phase 3) before Postgres is (Phase 4) under this plan's phase gating — deferring vector search to Phase 4 solely to enable pgvector would delay the Gap Challenger, a higher-priority capability. Revisit if Phase 3's real usage suggests pgvector would have sufficed.
- **In-memory/no vector DB (embeddings computed on the fly):** rejected — does not scale past a trivial corpus size and defeats the purpose of introducing embeddings at all.
