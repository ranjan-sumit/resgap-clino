# ADR-008: Gap confidence — Search Coverage Score gates every terminal status

**Status:** Accepted (pending user review)
**Date:** 2026-08-20
**Deciders:** BMAD planning pass (Research Methodology Specialist, AI/LLM Architect, QA/Evaluation Architect roles)

## Context

Problem D (brief §3): "no relevant papers found" must not automatically mean "gap is open" — an empty search result can mean the gap is genuinely open, or it can mean poor query construction, vocabulary mismatch, provider failure, or insufficient coverage. The brief lists 11 possible gap statuses (§11) without defining the decision rule that assigns one — a real gap in the brief itself (`00-analysis-and-architecture-options.md` §2, C9) that would otherwise produce silent inconsistency between the Gap Challenger's logic and what the UI shows.

## Decision

Adopt the deterministic terminal-status decision table in `04-ai-research-architecture.md` §5.2: a computed **Search Coverage Score** (fraction of planned query families executed × fraction of queried providers that responded) gates every outcome. A score below the coverage threshold (initial value 0.6, tuned against the benchmark) **always** routes to `INSUFFICIENT_EVIDENCE`, regardless of how many or few results were found — a technically-empty search can never resolve to `OPEN` without first clearing the coverage bar. Only once coverage clears the bar do relevant-result-count and contradiction-count determine `OPEN`/`PARTIALLY_OPEN`/`CONTESTED`/`LIKELY_CLOSED`/`CLOSED`.

## Consequences

- This is the literal, testable fix for Problem D — enforced as a hard branch in the decision table, not left to LLM judgment or convention.
- False Novelty Rate (`07-evaluation-architecture.md` §1, the product's top-priority metric) is directly protected: a poorly-covered search cannot masquerade as a confident "this is open" claim.
- The 0.6 threshold and Search Coverage Score formula weighting are explicitly named as Phase 3 tuning parameters, not permanently fixed by this ADR — recorded so a future implementer knows to calibrate against the Clinova Benchmark rather than treating the number as sacred.

## Alternatives considered

- **LLM judges gap status holistically (status quo pattern, single prompt decides open/partial/solved):** rejected as the sole mechanism — this is exactly the pattern that let the existing project's arXiv query bug silently produce false "no relevant papers found" verdicts before Story 2.6 fixed the underlying query construction; a deterministic gate in front of the LLM's judgment is a structural safeguard the old pattern lacked.
- **Binary gate only (searched vs. not) with no graduated coverage score:** rejected — insufficiently granular to distinguish "one provider was down" (partial coverage, still potentially usable) from "query planning failed entirely" (no usable coverage), both of which need different downstream handling.
