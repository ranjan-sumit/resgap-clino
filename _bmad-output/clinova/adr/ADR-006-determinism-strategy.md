# ADR-006: Determinism strategy — bounded nondeterminism, not false determinism

**Status:** Accepted
**Date:** 2026-08-20
**Deciders:** BMAD planning pass (AI/LLM Architect, QA/Evaluation Architect roles)

## Context

Problem F (brief §3): the same project can return materially different conclusions across runs with no way to tell whether a conclusion is stable or model-sensitive. LLMs are not fully deterministic even at low temperature/fixed seed. The brief explicitly warns against pretending otherwise (§16: "maximize reproducibility without pretending LLMs are deterministic").

## Decision

Adopt the reproducibility-control set in `04-ai-research-architecture.md` §6 (low temperature where appropriate, fixed seed where supported, versioned prompts, structured JSON-schema outputs, deterministic sort ordering, immutable corpus/search snapshots, model/prompt/tool version tracking, semantic-hash caching, run manifests, transient-failure-vs-reasoning-variation-aware retries) as the **bounding strategy**, and introduce a measured **Repeatability Score** (§6.1) computed by running the frozen benchmark multiple times per pipeline version — rather than asserting a fixed determinism guarantee that would be false.

## Consequences

- The product communicates nondeterminism honestly (UX convention, `02-ux-specification.md` §6: never present a conclusion as more certain than it is) rather than implying reruns will always agree.
- The Repeatability Score becomes a real, trackable champion/challenger input (`07-evaluation-architecture.md`) — a pipeline change that reduces repeatability is visible and can block promotion under the acceptance-threshold rule.
- Consensus (multi-model council) is reserved for the two highest-impact decision points only (`04-ai-research-architecture.md` §3) — determinism is bounded through engineering controls first, and consensus is used sparingly as a cost-justified addition, not the default determinism strategy.

## Alternatives considered

- **Temperature=0 everywhere and claim full determinism:** rejected — even temperature=0 does not guarantee bit-identical LLM output across calls on most hosted providers (including NVIDIA NIM), and claiming it would be a false product promise the brief explicitly warns against.
- **Run every stage through a 5-model consensus to average out variance:** rejected — brief explicitly says "do NOT run five LLMs for every task" (§16); also directly conflicts with the token/cost-budget constraint (§14, §48) of a free-tier API.
