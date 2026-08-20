# ADR-004: Model gateway — LLMProvider / EmbeddingProvider / RerankerProvider abstraction

**Status:** Accepted (pending user review)
**Date:** 2026-08-20
**Deciders:** BMAD planning pass (AI/LLM Architect role)

## Context

The existing `utils/azure_client.py` (misnamed — actually an NVIDIA NIM wrapper) already implements a typed `Result[str, ErrorInfo]` boundary (Stories 1.1-1.2 of the baseline project) — a sound, tested pattern. The brief requires the ability to swap LLM providers (future vLLM local, another OpenAI-compatible provider, a private enterprise endpoint) without business-logic changes (§13), plus separate local embedding/reranking model support (§14).

## Decision

Introduce three separate provider ports — `LLMProvider`, `EmbeddingProvider`, `RerankerProvider` — per `04-ai-research-architecture.md` §1. `LLMProvider`'s contract is the existing `Result[str, ErrorInfo]`/`LLMCallError` pattern verbatim, with the current NVIDIA NIM client becoming its first adapter (Phase 1 — introduced immediately, since the pattern already has real usage history to design against, unlike the other two ports). `EmbeddingProvider`/`RerankerProvider` are introduced at Phase 3 with BGE-M3/BGE-reranker as their first (and initially only) local adapters.

## Consequences

- Zero rewrite of the proven `azure_client.py` error-handling logic — it is the reference implementation the port interface is extracted from, not replaced.
- Future provider swaps (a paid API, a self-hosted vLLM instance) require only a new adapter implementing `LLMProvider`, never a change to `packages/research-engine` business logic (PRD FR-17).
- Embeddings/reranking run locally by default (§14's minimize-LLM-use discipline), keeping the free NVIDIA API as the only network-dependent LLM call, and bounding per-run cost.

## Alternatives considered

- **A single unified `ModelProvider` interface covering chat + embeddings + reranking:** rejected — chat, embedding, and reranking have materially different call/response shapes and failure modes; forcing them into one interface would either be overly generic (losing type safety) or force awkward parameter overloading. Three focused ports is a better fit for the existing `azure_client.py` precedent and for local-model swap-in.
