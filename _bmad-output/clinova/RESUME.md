---
name: 'Clinova Planning — Resume Index'
type: index
status: planning-complete-pending-review
created: '2026-08-20'
---

# Clinova Research Intelligence Platform — Resume Index

**Read this file first when picking this project back up.**

## Where this repo came from

`Research_Gap_Analyzer_V1` is a Phase 0 baseline import of `Research_Gap_Analyzer` (the original ResGap repo), copied 2026-08-20 with its own independent git history. The original repo was **not modified** and is unaffected by anything in this repository — see the first commit message (`git log --oneline` — "Baseline import...") for exactly what was carried over, including the already-completed Epic 1-3 pipeline-soundness work and the in-progress Streamlit UI theme change.

## What stage this project is at

**Planning complete, pending your review. No implementation has started.** Per the enterprise brief's explicit instruction (§55): "Stop and request review before implementation begins."

## Document reading order

1. `00-analysis-and-architecture-options.md` — brief analysis, contradictions/complexity found, current-system retain/refactor/replace/deprecate table, three architecture options, recommendation (Option C — Staged Hybrid), self-challenge. **Read this first — everything else assumes its conclusions.**
2. `01-prd.md` — product vision, personas, problem statement, functional/non-functional requirements, non-goals.
3. `02-ux-specification.md` — design system, information architecture, full screen inventory (implemented Phase 5; Streamlit is the interim UI through Phase 4).
4. `03-system-architecture.md` — hexagonal ports introduced phase-by-phase, repo structure, branding independence, dependency rules.
5. `04-ai-research-architecture.md` — provider abstraction, LLM-use discipline, small specialized agents, Hybrid Gap Engine, **Gap Challenger state machine** (the concrete 11-status decision table), determinism envelope.
6. `05-data-architecture.md` — ingestion pipeline, parser tool evaluation (GROBID+PyMuPDF+Docling), canonical identity resolution, resolution status model, Corpus Quality Engine, Evidence Objects.
7. `06-versioning-lineage-architecture.md` — Research Artifact Registry, Run Manifest, lineage views, version status lifecycle.
8. `07-evaluation-architecture.md` — False Novelty Rate (the top-priority product metric), Clinova Benchmark, champion/challenger comparison metrics.
9. `08-local-deployment-architecture.md` — Docker Compose profiles mapped to phases, onboarding flow.
10. `09-epics-and-stories.md` — full epic list across all 8 phases; **fully detailed stories for Phase 0 and Phase 1 only** (the recommended starting point).
11. `10-phased-implementation-plan.md` — phase-gate trigger conditions, Definition of Done, rollback posture, testing strategy per phase. **This is the plan to resume from.**
12. `adr/ADR-000` through `ADR-008` — the eight (nine, including ADR-000) binding architecture decisions, each with context/decision/consequences/alternatives-considered.

## Current phase

**Phase 0 — Baseline** (not started). Entry trigger: always true. See `10-phased-implementation-plan.md`'s phase-gate table and `09-epics-and-stories.md`'s Epic 0.1 for the concrete next stories.

## Key decisions already made (don't re-litigate without a new ADR)

- Architecture: **Option C, Staged Hybrid** (ADR-000) — infrastructure introduced per-phase, not upfront.
- Product name **"Clinova Research Intelligence Platform"**, tagline **"Evidence → Gaps → Hypotheses → Studies"**, landing headline **"Find the research nobody has done yet"** — all three live in a branding config layer, never in engine code (ADR-004-adjacent, `03-system-architecture.md` AD-3).
- False Novelty Rate is the single highest-priority product metric — missing a real gap is preferred over inventing a false one, everywhere thresholds are tuned.
- Vector DB: Qdrant (ADR-001). Graph: Neo4j CE + NetworkX hybrid (ADR-002). Workflow engine: deferred, no Temporal until a real trigger (ADR-003). Model gateway: three separate provider ports, `azure_client.py` becomes `LLMProvider`'s first adapter (ADR-004). Artifact versioning: bespoke Postgres registry, MLflow scoped out by default (ADR-005). Determinism: bounded, measured via Repeatability Score, never claimed as full determinism (ADR-006). Reference resolution: DOI→PMID→OpenAlex→S2→normalized(title+author+year), five-status trust model (ADR-007). Gap confidence: Search Coverage Score gates every terminal status — a poorly-covered search can never resolve to `OPEN` (ADR-008).

## What's explicitly NOT decided yet (open items)

- Concrete quality-gate thresholds (`05-data-architecture.md` §7) — tuned in Phase 1 against the real benchmark, not fixed in planning.
- Concrete Search Coverage Score threshold value (0.6 is a starting point, `04-ai-research-architecture.md` §5.2) — tuned in Phase 3.
- Exact deterministic gap-pattern list for the medical/healthcare-AI domain (`04-ai-research-architecture.md` §4) — needs a Research Methodology Specialist pass at Phase 3 kickoff.
- Frontend component library choice, Knowledge Graph rendering library — deferred to Phase 5 kickoff (`02-ux-specification.md` §9).
- GROBID's real local resource cost — a Phase 1 spike (Story 1.1.1b), not assumed from the desk evaluation in `05-data-architecture.md` §2. **Update 2026-08-20:** this dev machine (company laptop) has no admin rights / Docker access; GROBID is deferred to a Gradle-based (non-Docker) build against the already-installed Java 11 — see `amendments/2026-08-20-environment-constraints.md`. Phase 1 proceeds in the meantime with PyMuPDF + Docling (Docling needs no Docker/JVM).
- Phase 6 (governance) has no trigger yet — do not build it speculatively.
- NVIDIA NIM API key: user will add it to a local `.env` (not committed) — needed to unblock Story 0.1.1's real end-to-end baseline report.
- Sample papers for the seed corpus / Benchmark v1: user is providing specific papers (not yet received as of this note).

## Next action

Awaiting your review of this planning set. Once reviewed/adjusted, Phase 0 (Epic 0.1, `09-epics-and-stories.md`) is the first implementation work — starting with generating a real baseline report from the existing pipeline.
