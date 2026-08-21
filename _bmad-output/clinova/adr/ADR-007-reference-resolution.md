# ADR-007: Canonical reference resolution — priority chain + explicit status model

**Status:** Accepted
**Date:** 2026-08-20
**Deciders:** BMAD planning pass (Data Architect, Research Methodology Specialist roles)

## Context

Problem B (brief §3): fallback reference parsing can resolve citations incorrectly, contaminating the corpus, graph, gaps, and proposals downstream. This is not hypothetical — the existing project's own Story 2.3 code review already documented the exact failure mode: title-only cache identity causes two genuinely different papers sharing an exact title to silently share cached metadata, with whichever is enriched first "donating" its DOI/abstract/authors to every later reference with the same title.

## Decision

Adopt the canonical resolution priority chain **DOI → PMID → OpenAlex ID → Semantic Scholar ID → normalized(title + first-author-surname + year)** (`05-data-architecture.md` §5), with the fallback level requiring **all three** of title, author, and year to match (stricter than the existing project's title-only fallback), plus a five-value resolution status model (`VERIFIED / ACCEPTED / QUARANTINED / UNRESOLVED / REJECTED`, `05-data-architecture.md` §6) gating which references are trusted for gap analysis by default.

## Consequences

- Directly closes the documented title-collision failure mode: a title-only match is no longer sufficient at any resolution level.
- Multiple provider records for the same paper merge into one canonical identity, with provider-specific metadata preserved separately (auditable, reversible if a merge is later found wrong) — never discarded.
- Only `VERIFIED`/`ACCEPTED` references feed gap analysis by default; `QUARANTINED`/`UNRESOLVED` references are visible but held out, requiring an explicit promotion action — this is the structural fix for Problem C (fallback ≠ trusted) applied specifically to references.

## Alternatives considered

- **Title-only fallback matching (status quo):** rejected — proven collision risk, already documented as a known limitation in the baseline project.
- **Fuzzy/similarity-threshold title matching instead of exact normalized match:** considered for a future refinement (could catch near-duplicate titles with typos) but not adopted in this pass — introduces a tunable threshold with its own false-positive risk that needs benchmark-driven calibration (`07-evaluation-architecture.md`) before being trusted; the exact-match-on-three-fields rule is the safer, benchmark-testable starting point.
