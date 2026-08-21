---
name: 'Clinova Research Intelligence Platform — Evaluation Architecture'
type: architecture
altitude: capability
status: accepted
created: '2026-08-20'
inputDocuments: ['00-analysis-and-architecture-options.md', '01-prd.md', '04-ai-research-architecture.md']
companions: ['06-versioning-lineage-architecture.md', '10-phased-implementation-plan.md']
---

# Evaluation Architecture — Clinova Research Intelligence Platform

## 1. False Novelty Rate — the primary product metric (brief §21, binding priority)

**Definition:** the proportion of gaps the system reports as novel (`OPEN`, `PARTIALLY_OPEN`, or `LIKELY_CLOSED`/`CLOSED` misclassified as open) that the benchmark's known-closed-gap set proves are, in fact, already addressed by existing research.

**Product priority rule (non-negotiable, stated explicitly because it will otherwise erode under normal recall-maximizing instincts during implementation):** minimizing False Novelty Rate is prioritized over maximizing gap recall. A missed real gap is a lost opportunity; a confidently invented gap is a false claim the product makes to a researcher, which is the more damaging failure mode. Every threshold-tuning decision in this document defaults toward reducing false novelty, even at the cost of more gaps landing in `INSUFFICIENT_EVIDENCE` rather than a confident `OPEN`.

## 2. The Clinova Benchmark (brief §22)

A versioned, immutable internal test corpus, built incrementally starting Phase 0:

| Case type | Purpose |
|---|---|
| Known genuine research gaps | Positive control — the system must be able to find these |
| Known closed gaps | Directly measures False Novelty Rate — the system must NOT report these as open |
| Intentionally false/fabricated gaps | Stress-tests the Gap Challenger's ability to reject a plausible-sounding but unsupported claim |
| Ambiguous gaps | Measures whether `CONTESTED`/`PARTIALLY_OPEN` is correctly assigned instead of a false-confident terminal status |
| Contradictory research pairs | Tests contradiction-analysis recall (§4 below) |
| Duplicate references (same paper, different providers) | Tests canonical identity resolution (`05-data-architecture.md` §5) |
| Malformed citations | Tests reference-parsing robustness |
| Unrelated references (title-collision risk) | Directly tests the exact contamination failure mode already documented in the existing project's Story 2.3 review |
| Missing abstracts | Tests Corpus Quality Engine completeness scoring under degraded input |
| Parser failures (corrupted/unusual PDF layouts) | Tests the multi-parser reconciliation's graceful-degradation path |

**Immutability rule:** benchmark versions are never edited in place — a correction or addition produces a new benchmark version (`evaluation_benchmark` artifact type, `06-versioning-lineage-architecture.md`), so a metric reported against benchmark v3 is never silently compared against a different v3 later.

**Tooling:** `pytest` for deterministic/structural assertions (schema validity, canonical-identity correctness, reference-status transitions) plus a dedicated evaluation layer (`evals/regression/`) for the metrics in §3, which are statistical/threshold-based rather than pass/fail unit assertions.

## 3. Champion / Challenger comparison metrics (brief §20)

Run both pipeline versions against the identical frozen benchmark version; report:

| Metric | What it measures | Direction |
|---|---|---|
| Extraction completeness | `05-data-architecture.md` §7 metric, benchmark-averaged | Higher better |
| Reference resolution precision | Fraction of resolved references that are correctly canonicalized (no false merges) | Higher better |
| Reference recall | Fraction of true references successfully detected/resolved | Higher better |
| Corpus contamination | Rate of unrelated papers incorrectly merged/retained (benchmark's title-collision cases) | **Lower better — weighted heavily** |
| Retrieval recall | Fraction of benchmark's known-relevant search results actually retrieved by the Gap Challenger's search funnel | Higher better |
| Gap precision | Fraction of reported gaps that are genuinely novel per the benchmark's ground truth | Higher better |
| **False Novelty Rate** | §1 | **Lower better — the single highest-weighted metric in the promotion decision** |
| Contradiction recall | Fraction of the benchmark's known contradictory-research pairs correctly flagged | Higher better |
| Evidence coverage | Fraction of gap explanations with a valid, traceable Evidence Object reference | Higher better |
| Consistency (Repeatability Score) | `04-ai-research-architecture.md` §6.1, run against the same benchmark | Higher better |
| Latency | Wall-clock run duration | Lower better, but never traded against False Novelty Rate |
| Token usage | From the Run Manifest | Lower better, but never traded against False Novelty Rate |

### Promotion decision rule

A `CANDIDATE` pipeline is eligible for promotion to `CHAMPION` (`06-versioning-lineage-architecture.md` §2) only if:
1. False Novelty Rate is **no worse** than the current CHAMPION's, and
2. No other metric regresses beyond a defined tolerance band, and
3. Corpus contamination is **no worse** than the current CHAMPION's.

Concrete tolerance-band values are a Phase 4 tuning exercise (calibrated once the benchmark has enough real cases to be statistically meaningful) — the rule's *shape* (False Novelty Rate and contamination are hard gates, not tunable trade-offs) is the binding architectural decision.

## 4. Contradiction analysis evaluation

Measured directly against the benchmark's contradictory-research-pairs case set (§2) — recall (did the system flag the contradiction) and precision (did it flag genuine contradictions only, not merely differing methodologies) both tracked, since a system that over-flags contradictions to appear cautious is its own quality failure.

## 5. Relationship to the Repeatability Score

The Repeatability Score (`04-ai-research-architecture.md` §6.1) is computed using the same benchmark infrastructure described here (run N times, same pipeline version) and feeds into the Consistency row of §3's comparison table — one evaluation harness serves both purposes, not two separate systems.

## 6. Phase 0 seed action

Per `00-analysis-and-architecture-options.md` §8's flagged action item: the first concrete benchmark cases are seeded from a real baseline report generated against a small real corpus using the *existing* (pre-Clinova) pipeline, specifically capturing at least one known title-collision case and one arXiv-query-topic-mismatch case — both failure modes the existing project's own code review already proved are real and reproducible, making them the highest-confidence, lowest-effort first benchmark entries rather than synthetic ones.
