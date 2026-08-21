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

Planning complete; implementation underway (Phase 0-2, see "Current phase" below).

## Things you need to take care of (consolidated, updated as they come up)

**Environment / infrastructure — outside what I can do myself:**
- **Docker isn't available on this machine** (company laptop, no admin rights — `amendments/2026-08-20-environment-constraints.md`). This blocks GROBID's normal setup and all of Phase 3+'s planned infra (Qdrant, Neo4j). GROBID has an untried no-Docker fallback (build+run via Gradle against the Java 11 already on this machine) — real but slow on first build, not attempted yet. If you get admin rights or move to a different machine, GROBID and the later-phase infra become straightforward again.
- **Your `.env` file (NVIDIA_API_KEY) is gitignored** — it's on this machine only, not backed up anywhere by me. Keep your own copy of the key somewhere safe.

**Decisions only you (or a domain expert) can make:**
- The medical/healthcare-AI deterministic gap-pattern list (`04-ai-research-architecture.md` §4) needs a real domain-expert pass — I can draft candidate patterns, but their clinical/methodological validity needs your judgment or a subject-matter expert's, not mine.
- Quality-gate thresholds and the Search Coverage Score threshold (currently placeholder values — 0.35/0.60 fail/pass, 0.6 coverage) need real tuning once there's a bigger benchmark corpus than the current 2-3 papers. Don't treat the current numbers as final.
- Phase 6 (governance/Keycloak/OPA) has no trigger yet — explicitly don't ask me to build it until there's a real second user or compliance need; building it speculatively contradicts the plan's own reasoning.

**Known, intentional code gaps (not urgent, but real — don't be surprised by them):**
- 4 of the 13 Evidence Object types aren't extracted yet (InterventionModel, ComparatorBaseline, Metric, a "Finding" distinct from "Result").
- `wiki_compiler.py` still does its own independent LLM extraction, not yet unified with Evidence Objects — deliberately deferred to Phase 3 to avoid two risky edits to the same downstream consumers.
- Evidence extraction currently only runs when the "Corpus Quality Engine" sidebar toggle is on (it reuses Docling's page data for provenance). If you want evidence extraction without paying Docling's ~90s/paper cost, that needs its own toggle — not built.
- The Phase 0-era `generate_baseline_report.py`/diagnostic scripts and Playwright verification scripts in `evals/benchmarks/baseline/` are one-off manual verification tools, not part of the automated test suite — expect to re-run them by hand, not via `pytest`.

**Housekeeping (cosmetic, whenever convenient):**
- All planning docs (`00`-`10` + every ADR) still carry `status: draft-for-review` in their frontmatter. You've clearly been endorsing the plan by directing implementation against it, but I never got an explicit "approved" — say the word if you want that status flipped to `accepted` across the set (I haven't done it unprompted since it's a plan-approval action, not an engineering one).

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

**Phase 0 — Baseline: COMPLETE** (Epic 0.1 + Epic 0.2 hotfix, 2026-08-20/21). **Phase 1 — Data Foundation: COMPLETE** (Epics 1.1-1.4, 2026-08-21). **Phase 2 — Evidence Foundation: Epics 2.1 + 2.2 COMPLETE** (2026-08-21) — the only intentionally-deferred piece is the wiki_compiler rendering-layer rewrite, pushed to Phase 3 (reasoning below). See `09-epics-and-stories.md` for full status notes.

**Story 2.2.2 (report citation) done and wired into the live app.** `utils/export.py`'s HTML report gained a new, purely additive "Evidence" section. A new "Stage 2C — Evidence Extraction" step runs per paper (same opt-in toggle as Stage 2B). Verified end-to-end via a real browser session: 56 real evidence objects saved and correctly rendered in the actual generated report (20 + 36 across the two real papers), confirmed via direct database query and a rendered-report screenshot (`evals/benchmarks/baseline/screenshots/08_report_evidence_section.png`).

**Phase 2 kickoff finding that shaped real scope:** neither parser tracked page numbers for body text (only tables). Inspected Docling's actual document model directly before assuming anything — confirmed `doc.texts` carries real per-segment page numbers, extended `pipeline/docling_parser.py` to capture them (`text_segments`, `DOCLING_STAGE_VERSION` bumped 1→2). This is what gives Evidence Objects genuine page provenance instead of a guess.

**Epic 2.1 results:** `packages/research_schemas/evidence_object.py` (schema — note the underscore; `research-schemas` isn't a valid Python package name, corrected in `03-system-architecture.md` too) + `pipeline/evidence_extractor.py`. Deliberately NOT a fresh LLM re-extraction of the whole paper: 6 of 13 evidence types are derived deterministically from wiki_compiler's already-extracted fields (zero extra LLM cost), with real provenance from Docling's page-tagged segments; only 3 genuinely-uncaptured types (ResearchQuestion, Problem, StudyDesign) get one small scoped LLM call. Verified against real `AuDHD_1.pdf`: 20 evidence objects, 10 with real resolved pages, 10 honestly `page: null` (no fabrication). 4 types (InterventionModel, ComparatorBaseline, Metric, a distinct "Finding") remain unextracted — named gap, not hidden.

**Story 2.2.1:** Evidence Objects persisted via a new `evidence_objects` SQLite table, same cache-aside pattern as Phase 1, verified with a real (not mocked) cache round-trip.

**Deferred, with reasoning recorded:** the original Epic 2.2 scope ("wire wiki_compiler as a rendering layer over Evidence Objects") is pushed to Phase 3 — `wiki_compiler.py` is an existing, tested, working module with its own independent LLM call; replacing its extraction path is a real behavior change, not a safe additive step, and Phase 3 is already touching the graph/gap engine's Evidence-Object consumption, so both changes should land together.

Full test suite: 281 passing (91 new since Phase 1 completed).

**Epic 1.1 results:** `pipeline/docling_parser.py` (new, cached via `utils/database.py`'s `docling_extractions` table) and `pipeline/extraction_reconciler.py` (new) reconcile PyMuPDF + Docling extractions for `full_text`, `doi`, and `tables`, with LLM recovery scoped narrowly to an unresolved DOI. Docling measured heavy on this CPU-only machine (~1.1GB RSS, ~86s/paper) — revises the original desk estimate; see `evals/benchmarks/baseline/docling-resource-measurement.md`. Real-data validation against `Data-17072026/AuDHD_1.pdf` caught and fixed a genuine bug in the DOI-disambiguation logic (see `evals/benchmarks/baseline/doi-disambiguation-note.md`) before it shipped.

**Epic 1.2 (Corpus Quality Engine) and Epic 1.3 (Canonical Reference Resolution): DONE — logic, tests, AND wired into `app.py`'s live pipeline (2026-08-21).** `pipeline/corpus_quality.py` scores per-paper completeness against the 16-field checklist (honestly: 5 fields have no extraction path anywhere yet) and computes the corpus-level funnel + PASS/DEGRADED/FAIL gate. `pipeline/canonical_resolver.py` implements the full DOI→PMID→OpenAlex→SS→title+author+year priority chain and the 5-value status model (ADR-007). Both are wired into `app.py` behind one opt-in sidebar toggle (`🔬 Corpus Quality Engine`, default off — Docling is heavy, ~90s/paper, so it never silently taxes every run) as new "Stage 1C — Reference Resolution" and "Stage 2B — Corpus Quality Engine" pipeline steps, plus a `⚠️ Proceed even if FAIL` override checkbox.

**Verified end-to-end via a real Playwright browser session against the live app** (not just unit tests): uploaded the real `Data-17072026/AuDHD_1-2.pdf`, enabled the toggle, ran the full pipeline. Confirmed by querying the saved run directly from the database: 72 enriched references resolved to 71 VERIFIED, 1 QUARANTINED, 3 duplicates merged → 68 trusted references feeding downstream; corpus scored 50% extraction completeness, 100% DOI resolution, `gate=DEGRADED`; the full pipeline still completed successfully end-to-end (6 real gaps, 5 real proposals — contrast with Phase 0's original 0 gaps / 4 fabricated proposals).

**Three more real bugs found and fixed during this work, each caught by testing against real data rather than mocks alone:**
- An initial DOI-resolution-rate calculation divided two `ref_diagnostics` fields that weren't actually numerator/denominator of the same fraction — produced a rate of 4.25 (impossible) on the real corpus before the fix.
- **B20:** OpenAlex ID resolution was structurally present in the priority chain but could never match — `reference_extractor.py`'s OpenAlex query didn't request an `id` field at all. Fixed and verified live against the real OpenAlex API.
- **B21, more consequential:** while fixing B20, found `canonical_resolver.py`'s PMID detection checked a field name (`source_api`) that only exists on internal provider-function dicts, never on the real enriched reference dict any caller sees (the real field is `source`) — PMID resolution would have silently never matched on real data. Not caught by the original unit tests because they used the same wrong field name as the implementation. Fixed, plus added `RealCorpusFieldShapeTests`, which runs resolution against every reference in the actual Phase 0 corpus (not hand-written fixtures) specifically so a future field rename can't silently slip through the same way again.

Full test suite now 230 passing (89 new across Phase 1 so far). Verification artifacts: `evals/benchmarks/baseline/playwright_smoke_test.py`, `playwright_check_trace.py`, and screenshots in `evals/benchmarks/baseline/screenshots/`.

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
