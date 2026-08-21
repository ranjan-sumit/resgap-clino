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

**Phase 0 — Baseline: COMPLETE** (Epic 0.1 + Epic 0.2 hotfix, 2026-08-20/21). **Phase 1 — Data Foundation: IN PROGRESS.** Epic 1.1's Stories 1.1.1a, 1.1.2, 1.1.3, 1.1.4 are done (2026-08-21) — see `09-epics-and-stories.md` for status notes on each. Story 1.1.1b (GROBID) remains deferred, not blocking. **Next up: Epic 1.2 (Corpus Quality Engine & Quality Gates) and Epic 1.3 (Canonical Reference & Paper Identity Resolution)** — see `10-phased-implementation-plan.md`.

**Epic 1.1 results:** `pipeline/docling_parser.py` (new, cached via `utils/database.py`'s `docling_extractions` table) and `pipeline/extraction_reconciler.py` (new) reconcile PyMuPDF + Docling extractions for `full_text`, `doi`, and `tables`, with LLM recovery scoped narrowly to an unresolved DOI. Docling measured heavy on this CPU-only machine (~1.1GB RSS, ~86s/paper) — revises the original desk estimate; see `evals/benchmarks/baseline/docling-resource-measurement.md`. Real-data validation against `Data-17072026/AuDHD_1.pdf` caught and fixed a genuine bug in the DOI-disambiguation logic (see `evals/benchmarks/baseline/doi-disambiguation-note.md`) before it shipped.

**Epic 1.2 (Corpus Quality Engine) and Epic 1.3 (Canonical Reference Resolution): DONE (logic + tests), NOT YET WIRED into `app.py`.** `pipeline/corpus_quality.py` scores per-paper completeness against the 16-field checklist (honestly: 5 fields have no extraction path anywhere yet) and computes the corpus-level funnel + PASS/DEGRADED/FAIL gate — real corpus scored 52.1% completeness, DEGRADED. Real-data validation caught and fixed a second genuine bug: an initial DOI-resolution-rate calculation divided two diagnostics fields that weren't actually numerator/denominator of the same fraction, producing a rate of 4.25 (impossible) before the fix. `pipeline/canonical_resolver.py` implements the DOI→PMID→OpenAlex→SS→title+author+year priority chain and the 5-value status model (ADR-007) — verified against Benchmark v1's real duplicate-DOI and contamination fixtures. **Known open gap, not fixed this pass:** OpenAlex ID resolution is structurally present but can never match, because `reference_extractor.py`'s OpenAlex query doesn't request an `id` field. **Integration gap, not fixed this pass:** neither the quality gate nor the reference-status filtering is actually wired into `app.py`'s live pipeline run yet — both modules are built and tested standalone; wiring them into the real run (and the corresponding UI surfacing) is real remaining work for a future story, not silently implied done. Full test suite now 207 passing (63 new across Phase 1 so far).

**Environment status:** Python 3.11.9 installed per-user (no admin rights on this machine — see `amendments/2026-08-20-environment-constraints.md`), venv at repo root `.venv/`, `requirements-dev.txt` installed. All 155 existing tests pass unmodified.

**Phase 0 results — read `evals/benchmarks/baseline/phase0-findings.md` before starting Phase 1.** The real baseline run against a 3-paper AuDHD (co-occurring Autism/ADHD) corpus surfaced a **severe live bug, not a hypothetical one**: `detect_gaps` returned 0 gaps (nondeterminism — an immediate re-run with identical input returned 5 well-grounded gaps), and `generate_proposals` had no guard against an empty gap list — it called the LLM anyway and fabricated 4 plausible-sounding, completely ungrounded proposals. **Fixed 2026-08-21 (Epic 0.2, B19):** see below. Three more real cases were found and fixtured, still open (Phase 1/3 scope): a Spanish-textbook citation contaminating the AuDHD reference corpus (Problem B, live — `case-reference-contamination-espanol.json`), three exact-DOI reference duplicates the baseline never merges (`case-reference-duplicate-doi.json`), and truncated-DOI/"Unknown"-title extraction loss (Problem A, live — `case-truncated-doi.json`).

**Epic 0.2 — Zero-Gap Fabrication Hotfix: DONE (2026-08-21).** `pipeline/gap_detector.py`'s `detect_gaps` now retries once on a JSON-parse failure and raises `GapDetectionError` (not silently `[]`) if both attempts fail — genuine empty `[]` results are preserved as distinct from parse failures. `pipeline/proposal_generator.py`'s `generate_proposals` now returns `[]` immediately on an empty gap list instead of calling the LLM. Verified against the exact real data that exposed the bug: the same wiki/graph/context that originally produced 0 gaps now produces 5 real, evidence-grounded ones. 10 new tests added (`tests/test_gap_detector_parse_retry.py`, `tests/test_proposal_generator_empty_guard.py`); full suite at 165 passing. Full details: `_bmad-output/clinova/09-epics-and-stories.md` Epic 0.2, `evals/benchmarks/baseline/phase0-findings.md`'s Resolution section.

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
- **Resolved 2026-08-21:** the zero-gap fabrication bug was fixed immediately (Epic 0.2, B19) rather than deferred to Phase 3 — see above. Phase 3's Gap Challenger will still subsume this with the proper state-machine treatment (`04-ai-research-architecture.md` §5); this hotfix is a narrow safety net, not a substitute for that.

## Next action

Awaiting your review of this planning set. Once reviewed/adjusted, Phase 0 (Epic 0.1, `09-epics-and-stories.md`) is the first implementation work — starting with generating a real baseline report from the existing pipeline.
