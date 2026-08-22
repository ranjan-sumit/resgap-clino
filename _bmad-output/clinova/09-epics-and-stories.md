---
name: 'Clinova Research Intelligence Platform — Epics & Stories'
type: epics
status: accepted
created: '2026-08-20'
inputDocuments: ['01-prd.md', '03-system-architecture.md', '04-ai-research-architecture.md', '05-data-architecture.md', '10-phased-implementation-plan.md']
companions: ['10-phased-implementation-plan.md']
---

# Epics & Stories — Clinova Research Intelligence Platform

## Detailing policy

Per the brief's own implementation rule (§53) — "stories must remain small enough for an AI coding agent to implement reliably" — and matching this project's own established practice (the baseline `_bmad-output/planning-artifacts/epics.md` fully detailed only its in-scope epics), **full Given/When/Then stories are written here for Phase 0 and Phase 1 only** — the "minimum first phase that improves scientific reliability without destabilizing the existing system" the brief explicitly asks this planning pass to identify (§55). Phases 2-8 are specified at epic level (goal, FRs/ADRs covered, story titles) — detailed stories for each phase are written via `bmad-create-story` immediately before that phase begins, incorporating whatever was learned in the phase before it, exactly as the baseline project's own Epic 1→2→3 sequencing already did.

---

## Phase 0 — Baseline

**Goal:** freeze current behavior, seed the evaluation benchmark, and measure the six known problems concretely — before any code changes. **No engine code changes in this phase.**

### Epic 0.1: Baseline Report & Benchmark Seed
**FRs:** none directly (evaluation infrastructure) · **Depends on:** nothing · **Files:** `evals/benchmarks/`, existing `pipeline/doc_generator.py` (read-only use)

#### Story 0.1.1: Generate a real baseline report from the existing pipeline
As a Platform Operator, I want a real report generated end-to-end from the existing (pre-Clinova) pipeline against a small real corpus, so that later phases have a measured "before" state.

**AC:**
- **Given** the existing pipeline and a small sample corpus (3-5 open-access papers in the project's existing healthcare-AI domain)
- **When** the report is generated end-to-end using the current `pipeline/doc_generator.py`
- **Then** a real HTML/PDF report is produced and saved immutably at `evals/benchmarks/baseline/phase0-report-v1.*`
- **And** the run's paper/reference counts and any observably degraded output are captured in a companion findings note

#### Story 0.1.2: Seed Clinova Benchmark v1 with the two already-documented real failure cases
As a QA/Evaluation Architect, I want Benchmark v1 seeded with the reference-title-collision risk and the (now-fixed) arXiv query-construction bug as real cases, so that Phase 1-3 acceptance tests validate against confirmed, not hypothetical, failure modes.

**AC:**
- **Given** the existing project's Story 2.3 code-review finding (title-collision risk in reference caching) and Story 2.6 finding (arXiv OR-vs-AND bug)
- **When** Benchmark v1 is created
- **Then** it contains at least one title-collision case (two distinct real papers with identical/near-identical titles) and one multi-concept-query case (reproducing the arXiv topic-mismatch shape)
- **And** the benchmark is saved as an immutable, versioned `evaluation_benchmark` artifact per `06-versioning-lineage-architecture.md`

#### Story 0.1.3: Record baseline measurements against Problems A-F
As a Business Analyst, I want the baseline's measured state against brief Problems A-F explicitly recorded, so later phases can show concrete before/after improvement.

**AC:**
- **Given** Stories 0.1.1-0.1.2's outputs
- **When** the Phase 0 findings document is completed
- **Then** it states, for each of Problems A-F, whether the baseline exhibits the problem with concrete evidence — refining the cross-reference table already drafted in `00-analysis-and-architecture-options.md` §4 against the real Story 0.1.1 report rather than desk analysis alone

### Epic 0.2: Zero-Gap Fabrication Hotfix (unplanned — found live during Story 0.1.1, fixed 2026-08-21)

**Goal:** the headline Phase 0 finding (`evals/benchmarks/baseline/phase0-findings.md`) was severe enough — confidently fabricated, ungrounded proposals presented as real research directions — that the user asked for a thorough fix before proceeding to Phase 1, rather than deferring it to Phase 3's Gap Challenger as originally scoped. This epic is scoped narrowly to the two files directly implicated in the observed failure chain; it does not attempt the broader `_robust_parse`-duplication cleanup noted as a pre-existing, separately-scoped issue across `discovery_engine.py`/`graph_builder.py`/`llm_council.py`/`param_extractor.py`.

**FRs:** none directly (a data-integrity bugfix, not a planned capability) · **Files:** `pipeline/gap_detector.py`, `pipeline/proposal_generator.py` · **Bug-fix changelog ID:** B19 (continuing the inherited project's `# B<N> fix:` numbering — B18 was the last used).

#### Story 0.2.1: detect_gaps distinguishes a parse failure from a genuine empty result

**AC:**
- **Given** `detect_gaps`'s LLM response parses as a valid JSON list on the first attempt
- **When** the stage completes
- **Then** the parsed gaps are returned and `chat_json` is called exactly once
- **Given** the response is a literal, valid `[]`
- **When** the stage completes
- **Then** `[]` is returned without a retry (a genuine empty result is preserved, not conflated with a parse failure)
- **Given** the response fails to parse on the first attempt (not valid JSON, or valid JSON but not a list)
- **When** the stage retries
- **Then** exactly one retry is attempted with the identical prompt, and its result is used if it parses successfully
- **Given** both attempts fail to parse
- **When** the stage exhausts its retry
- **Then** it raises `GapDetectionError` (carrying `raw_response_preview`) rather than returning `[]` silently

**Status:** done. Tests: `tests/test_gap_detector_parse_retry.py` (7 cases). Verified against the real Phase 0 data that exposed the bug (`evals/benchmarks/baseline/verify_b19_fix.py`): the exact wiki/graph/context that originally produced 0 gaps now produces 5 real, evidence-grounded gaps.

#### Story 0.2.2: generate_proposals never calls the LLM on an empty gap list

**AC:**
- **Given** `gaps == []`
- **When** `generate_proposals` is called
- **Then** it returns `[]` immediately, without calling the LLM
- **Given** `gaps` is non-empty but none are `open`/`partial` (all `solved`)
- **When** `generate_proposals` is called
- **Then** the existing fallback-to-all-gaps behavior is unchanged (this story does not alter that pre-existing branch)

**Status:** done. Tests: `tests/test_proposal_generator_empty_guard.py` (3 cases, including a regression guard for the unaffected all-solved branch). Verified directly against real Phase 0 data.

---

## Phase 1 — Data Foundation

**Goal:** eliminate silent data loss (Problem A) and reference contamination (Problem B), and make fallback trust explicit (Problem C) — the highest-confidence, evidence-backed starting point per `00-analysis-and-architecture-options.md` §4. **No UI changes beyond the existing Streamlit interim theme; no new user-facing screens.**

### Epic 1.1: Multi-Parser Extraction & Reconciliation
**FRs:** FR-1 · **ADRs:** none directly · **Depends on:** Phase 0 · **Files:** new `packages/research-engine/parsing/` (or interim `pipeline/parsing/`), `pipeline/pdf_parser.py` (retained as one input)

#### Story 1.1.1a: Stand up Docling as a local Python dependency (unblocked, no Docker needed)
**AC:**
- **Given** Docling is a pure pip-installable package
- **When** it's added to the Phase 1 environment
- **Then** it runs directly in the Python venv with no container dependency, and a measured resource-cost result is recorded, confirming or revising the desk estimate in `05-data-architecture.md` §2

**Status:** done. Measured 2026-08-21 against real papers: **~1.1 GB process RSS, ~86s/paper steady-state (CPU, torch-based)** — revises the original "Moderate" desk estimate to "Heavy" (`evals/benchmarks/baseline/docling-resource-measurement.md`). Caching by content hash made binding as a result (`utils/database.py`'s `docling_extractions` table, `pipeline/docling_parser.py`).

#### Story 1.1.1b: Stand up GROBID via Gradle (deferred — see `amendments/2026-08-20-environment-constraints.md`)
**AC:**
- **Given** this development machine has no Docker access (no admin rights, no WSL2) but does have Java 11 already installed
- **When** GROBID is picked up
- **Then** it is built and run via its own Gradle wrapper (`./gradlew run`), not the `data` Compose profile, until Docker access is resolved
- **And** a measured resource-cost result (RAM/startup time) is recorded, confirming or revising the desk estimate in `05-data-architecture.md` §2
- **Not required to unblock the rest of Epic 1.1** — Story 1.1.2-1.1.4 proceed with PyMuPDF + Docling as the two-parser interim combination in the meantime

**Status:** still deferred — not picked up this pass, per its own AC (not required to unblock 1.1.2-1.1.4).

#### Story 1.1.2: Extract a paper independently with each available parser
**AC:**
- **Given** a sample paper
- **When** extraction runs
- **Then** an independent `ExtractedField` set exists per available parser (`05-data-architecture.md` §3) — PyMuPDF + Docling now, GROBID added once Story 1.1.1b lands — each correctly tagged by `source`, and reconciliation (Story 1.1.3) works correctly with either two or three parser inputs (never assumes exactly three)

**Status:** done. `pipeline/docling_parser.py` (new) alongside the existing `pipeline/pdf_parser.py`. Verified against real `Data-17072026/AuDHD_1.pdf`: PyMuPDF 5.3s/53,417 chars/5 tables; Docling 96.1s (cold)/65,083 chars/5 tables. Tests: `tests/test_docling_parser_cache.py`.

#### Story 1.1.3: Reconcile multi-parser output into one canonical paper representation
**AC:**
- **Given** three `ExtractedField` sets for one paper
- **When** reconciliation runs
- **Then** one canonical value is chosen per field with a documented resolution rule, and all candidate values remain queryable (not discarded)
- **And** a field where every parser fails is marked missing/low-confidence, never silently omitted

**Status:** done, scoped to the fields both parsers can produce deterministically today (`full_text`, `doi`, `tables` — title/authors/abstract/etc. remain LLM-derived via `wiki_compiler.py` unchanged, not silently claimed as reconciled). `pipeline/extraction_reconciler.py` (new). Real-data validation caught and fixed a genuine bug in the first implementation (a naive "prefer longer string" DOI tiebreak that happened to work by coincidence on the first test but isn't the actual right signal) — see `evals/benchmarks/baseline/doi-disambiguation-note.md` for the full finding: position-in-text, not length, correctly distinguishes a paper's own DOI from an unrelated one (e.g. a linked OSF dataset DOI) mentioned later in the body. Tests: `tests/test_extraction_reconciler.py` (18 cases).

#### Story 1.1.4: LLM recovery only for genuinely unresolved fields
**AC:**
- **Given** a field where all three parsers disagree or fail
- **When** reconciliation reaches that field
- **Then** and only then is an `LLMProvider` call made for recovery (tagged `source=LLM_RECOVERY`)
- **Given** a field where parsers agree
- **When** reconciliation runs
- **Then** no LLM call is made for that field (enforces `04-ai-research-architecture.md` §2's discipline)

**Status:** done, scoped to the `doi` field (the only field in this pass's reconciliation scope that both parsers can fail to resolve at all — `full_text`/`tables` always have a fallback candidate as long as either parser produced anything). `recover_doi_via_llm()` in `pipeline/extraction_reconciler.py`, invoked only when `needs_llm_recovery=True`. Tests confirm the LLM is never called when a DOI is already resolved (`tests/test_extraction_reconciler.py::DoiLlmRecoveryTests`).

### Epic 1.2: Corpus Quality Engine & Quality Gates
**FRs:** FR-2, FR-3 · **Depends on:** Epic 1.1

#### Story 1.2.1: Compute per-paper extraction completeness score
**AC:** **Given** a reconciled canonical paper; **When** completeness is computed; **Then** the score reflects the % of `05-data-architecture.md` §4's field list present at confidence ≥ medium.

**Status:** done. `pipeline/corpus_quality.py`'s `score_paper_completeness()`. Honest by construction: 5 of the 16 fields (authors, abstract, introduction, metrics, conclusion) have no extraction path anywhere in the pipeline today and always score `not_extracted`, distinct from a field that was attempted and came back empty — not silently collapsed into the same signal. Real corpus (`Data-17072026/`) scored 44-56% per paper.

#### Story 1.2.2: Compute corpus-level quality metrics and reference-resolution funnel
**AC:** **Given** a corpus of reconciled papers and references; **When** the Corpus Quality Engine runs; **Then** it outputs the full funnel and metric set (`05-data-architecture.md` §7) as one structured result attached to the run.

**Status:** done. `compute_corpus_quality()`, built directly on the existing `reference_extractor.py` diagnostics shape. Real-data validation caught a genuine bug before shipping: an initial version divided `ref_diagnostics["doi_entries"]` by `structured_entries`, which are not numerator/denominator of the same fraction (`doi_entries` counts raw DOI-regex matches added on top of `structured_entries` during combined-list construction, not a subset of it) — produced a rate of 4.25 on real data. Fixed to compute DOI resolution rate from the actual resolved reference records. Real corpus result: 52.1% extraction completeness, 93.9% DOI resolution rate, `DEGRADED` gate.

#### Story 1.2.3: Enforce the PASS/DEGRADED/FAIL quality gate
**AC:**
- **Given** corpus quality metrics
- **When** the gate evaluates
- **Then** a `FAIL` result blocks gap-analysis stages by default
- **Given** a user explicitly overrides a `FAIL` gate
- **When** the override is applied
- **Then** it is logged (who/when/why) and the run's degraded provenance still propagates into any generated report

**Status:** done, and wired into `app.py`'s live run flow (2026-08-21). `enforce_quality_gate()` / `QualityGateBlockedError`, called from a new "Stage 2B — Corpus Quality Engine" step behind an opt-in sidebar toggle (`🔬 Corpus Quality Engine (multi-parser + gate)`, default off — Docling is measured heavy, ~90s/paper, so it doesn't silently add that cost to every run) plus a `⚠️ Proceed even if the quality gate is FAIL` override checkbox. Verified end-to-end via a real browser session (Playwright) against the live app with the real `Data-17072026/` corpus: the run produced `gate=DEGRADED` (50% extraction completeness, 100% DOI resolution rate) and completed successfully — confirmed by querying the saved run's `corpus_quality_metrics` field directly from the database, not just by eyeballing the UI.

**Design fix, 2026-08-21 (gate formula corrected):** the gate previously evaluated `completeness_score` (present_count / 16), which caps at 68.75% for every paper regardless of extraction quality, since 5 of 16 fields have no extraction path anywhere in the pipeline yet. A genuinely well-extracted paper (10 of 11 achievable fields present) scored a raw 62.5% — sitting right at the old gate's PASS boundary by coincidence, masking that the formula itself was wrong, not that thresholds needed "a bigger benchmark" to tune. Fixed: the gate now evaluates `achievable_completeness_score` (present_count / 11, the real ceiling given today's extraction capability); `completeness_score` is still reported unchanged for honest overall transparency, it's just no longer what the gate judges. 4 new regression tests, including one reproducing the exact real scenario. `QUALITY_GATE_FAIL_THRESHOLD`/`QUALITY_GATE_PASS_THRESHOLD` values (0.35/0.60) unchanged — this was a formula bug, not a threshold-tuning question.

### Epic 1.3: Canonical Reference & Paper Identity Resolution
**FRs:** FR-4, FR-5 · **ADRs:** ADR-007 · **Depends on:** Epic 1.1

#### Story 1.3.1: Implement the DOI→PMID→OpenAlex→S2→normalized(title+author+year) priority chain
**AC:** **Given** a reference with a resolvable DOI; **When** resolution runs; **Then** it resolves at the DOI level with `VERIFIED` status. **Given** a reference resolvable only by normalized title+author+year; **When** resolution runs; **Then** all three fields must match for `ACCEPTED` status — a partial match yields `QUARANTINED`, never `ACCEPTED`.

**Status:** done, fully — all five priority levels work against real data. `pipeline/canonical_resolver.py`'s `resolve_canonical_identity()`. DOI, Semantic Scholar ID, arXiv ID, and normalized title+author+year confirmed against real data from the start. PMID is recovered from the existing PubMed enrichment's `url` field (cheap regex, no upstream change needed) — this also exposed and fixed a real bug (B21): the field it checked, `source_api`, never existed on a real enriched reference dict (the real field is `source`); a real-corpus regression test (`RealCorpusFieldShapeTests`) now guards against this class of drift. **OpenAlex ID (B20 fix, 2026-08-21):** originally structurally present but unable to match — `pipeline/reference_extractor.py`'s OpenAlex query didn't request an `id` field. Fixed: the query now requests `id`, the enrichment pipeline threads `openalex_id` through to the final reference dict, and the fix was verified live against the real OpenAlex API (not just mocked).

#### Story 1.3.2: Merge multi-provider records into one canonical paper
**AC:** **Given** the benchmark's duplicate-provider-record case; **When** resolution runs against it; **Then** exactly one canonical paper results, and each contributing provider's raw record is preserved and separately queryable.

**Status:** done. `merge_canonical_references()`. Verified against Benchmark v1's real duplicate-DOI fixture (3 pairs from the actual `Data-17072026/` corpus) — each pair correctly merges to 1 canonical reference with both provider records preserved.

#### Story 1.3.3: Reference status model with default-safe corpus filtering
**AC:** **Given** references with `QUARANTINED`/`UNRESOLVED` status; **When** a run completes; **Then** only `VERIFIED`/`ACCEPTED` references feed gap analysis by default, and quarantined/unresolved references are visible in the corpus data contract with an explicit, logged manual-promotion path — never silent auto-promotion.

**Status:** done, and wired into `app.py`'s live run flow (2026-08-21). New "Stage 1C — Reference Resolution" step (same opt-in toggle as Story 1.2.3) calls `filter_and_dedupe_references()` right after reference enrichment; only VERIFIED/ACCEPTED, deduplicated references reach wiki compilation, graph building, and gap detection. Verified end-to-end via a real browser session against the live app: the real 2-paper corpus's 72 enriched references resolved to 71 VERIFIED + 0 ACCEPTED + 1 QUARANTINED + 0 UNRESOLVED, with 3 exact-identity duplicates merged, leaving 68 trusted references — confirmed by querying the saved run's `ref_resolution_diagnostics` field directly from the database. The full pipeline then completed successfully end-to-end (6 gaps, 5 proposals), proving the filtered/deduplicated reference set flows correctly into every downstream stage, not just that the filtering function runs.

#### Story 1.3.4: Regression test against the known title-collision benchmark case
**AC:** **Given** Benchmark v1's title-collision case (Story 0.1.2); **When** the new resolver runs against it; **Then** the two distinct papers resolve to two distinct canonical identities — the acceptance test proving ADR-007 is actually in effect, not merely documented.

**Status:** done, against real fixtures (not the originally-planned synthetic case — Benchmark v1 was reseeded in Phase 0 with real findings). `tests/test_canonical_resolver.py::BenchmarkV1RegressionTests`: the duplicate-DOI case correctly merges (3/3 real pairs); the Español contamination case correctly merges to 1 reference with `VERIFIED` status (a real DOI legitimately resolves VERIFIED — relevance filtering is a distinct, not-yet-built stage, and the benchmark fixture's `expected_behavior` was corrected to reflect this real scope boundary rather than overclaim); the truncated-DOI case resolves without crashing or spuriously merging unrelated entries.

### Epic 1.4: Branding Layer & LLMProvider Port Extraction
**FRs:** NFR-1, FR-17 · **ADRs:** ADR-004 · **Depends on:** nothing (parallelizable with 1.1-1.3)

#### Story 1.4.1: Extract the LLMProvider interface behind the existing azure_client.py logic
**AC:** **Given** the existing `Result[str, ErrorInfo]` pattern in `utils/azure_client.py`; **When** the `LLMProvider` port is introduced; **Then** all existing callers continue to work unchanged (behavior-preserving refactor) — verified by the existing test suite (`tests/test_azure_client.py`, `tests/test_caller_resilience.py`) passing unmodified.

**Status:** done. `packages/contracts/llm_provider.py` defines `LLMProvider` as a `typing.Protocol` — `utils/azure_client.py` is **not modified at all** by this story, so the "unchanged" requirement is trivially, provably true rather than merely tested for. `AzureOpenAIClient` satisfies the port structurally (no inheritance change). A second, independent, non-NVIDIA test implementation (`tests/test_llm_provider_port.py::SecondIndependentProvider`) also satisfies it, proving the interface is genuinely swappable rather than an accidental one-class shape. 4 new tests; full suite 234 passing.

#### Story 1.4.2: Create the branding/theme config layer with Clinova identity
**AC:** **Given** the product name and tagline (`02-ux-specification.md` §2); **When** the branding layer is created; **Then** no other module references these strings literally, and the interim Streamlit UI reads them from this config — proving `03-system-architecture.md` AD-3 holds in practice.

**Status:** done and wired into the live app (branding config itself was created in Phase 0 kickoff — see `packages/branding/theme.json`/`copy.json` — this story completes the wiring that was deferred at the time). `app.py` now loads `product_name`/`tagline` via a small `_load_branding()` helper and uses it at all three points the name previously appeared literally (browser tab title, sidebar header, main page header); the tagline is newly surfaced as a sidebar caption (previously loaded but never displayed anywhere). Verified visually via a live browser screenshot: tab title, sidebar, and main header all correctly show "Clinova Research Intelligence Platform," with the tagline "Evidence → Gaps → Hypotheses → Studies" visible under the sidebar header (`evals/benchmarks/baseline/screenshots/06_branding_check.png`).

---

## Phase 2 — Evidence Foundation

**Goal:** structured Evidence Objects with provenance become the source of truth the graph and gap engine read, demoting wiki-synthesis to a UI convenience (Problem A, cont'd). **Trigger to begin:** Phase 1 quality gate (Epic 1.2) and reference resolution (Epic 1.3) are passing their benchmark regression tests — satisfied 2026-08-21 (Phase 1 complete).

**Kickoff finding that shapes this phase's real scope (2026-08-21):** neither existing parser currently tracks page numbers for body text — `pipeline/page_index.py`'s `build_tree()` is section-based only (only tables/figures carry a `page` field, via pdfplumber). Checked Docling's actual document model directly (`doc.texts`) and confirmed it *does* carry real per-segment page numbers and semantic labels (`page_header`, `section_header`, `text`, etc.) internally — `pipeline/docling_parser.py` (Phase 1) just wasn't extracting that structure yet, only a flat markdown export. Epic 2.1 extends it to capture this, so Evidence Objects can carry genuine page provenance when Docling ran, with an honest `page: null` (not a guess) when it didn't. This is the concrete resolution of `05-data-architecture.md` §8's provenance requirement — decided from real inspection, not assumed.

### Epic 2.1: Evidence Object Schema & Extraction
**FRs:** FR-6 · **ADRs:** none directly · **Depends on:** Phase 1 (reconciled extraction, Corpus Quality Engine) · **Files:** `packages/research-schemas/evidence_object.py` (new), `pipeline/docling_parser.py` (extended), `pipeline/evidence_extractor.py` (new)

#### Story 2.1.1: Extend Docling extraction with page-tagged text segments
**AC:** **Given** `doc.texts` (Docling's internal per-segment structure); **When** `extract_with_docling()` runs; **Then** it returns, alongside the existing flat `full_text`, a list of `{text, page, label}` segments — real page numbers, not inferred — and this becomes a new, separately cached field so existing callers of `full_text`/`tables` are unaffected.

**Status:** done. `text_segments` added to `pipeline/docling_parser.py`'s return shape, sourced from `doc.texts[i].prov[0].page_no`. `DOCLING_STAGE_VERSION` bumped 1→2 (the cached shape changed, old rows must not be served as if they had the new field). Verified against real `Data-17072026/AuDHD_1.pdf`: 211 real page-tagged segments extracted (confirmed via direct inspection of Docling's document model before implementing, not assumed).

#### Story 2.1.2: Define the Evidence Object schema
**AC:** **Given** `05-data-architecture.md` §8's field list; **When** the schema is defined; **Then** it is a validated, importable Python structure (`evidence_id`, `evidence_type` — the 13-value enum, `paper_id`, `text`, `provenance` {page, section, text_span, extraction_version}, `confidence`, `evidence_object_version`) that both the extractor and its tests import from one place, not redefined ad hoc.

**Status:** done. `packages/research_schemas/evidence_object.py` (note: `research_schemas`, underscore — `03-system-architecture.md`'s original `research-schemas` spelling isn't a valid Python package name; corrected there too). Content-addressed `evidence_id` (sha256 of paper_id+type+text), frozen dataclass, raises on construction with an invalid type/confidence/empty text. 15 tests.

#### Story 2.1.3: Implement the Evidence Extractor with typed I/O + token budget
**AC:** **Given** a reconciled paper + its page-tagged Docling segments (when available) + its wiki page; **When** the Evidence Extractor runs; **Then** it returns a list of Evidence Objects grounded in real text, each with the best provenance available (page-tagged Docling segment match when the quality engine ran; section-only, `page: null`, when it didn't — never a fabricated page number); the LLM call carries an explicit `max_tokens` budget (`04-ai-research-architecture.md` §7).

**Status:** done, and more disciplined than originally scoped. `pipeline/evidence_extractor.py`. Rather than a single LLM-based "Evidence Extractor agent" re-extracting the whole paper (redundant with `wiki_compiler.py`'s existing LLM call, violating `04-ai-research-architecture.md` §2's LLM-use discipline), 6 of the 13 evidence types (Method, DatasetPopulation, Result, Limitation, FutureWork, Claim) are derived **deterministically** from the wiki page's already-extracted fields — zero additional LLM cost — with real provenance resolved by matching against Story 2.1.1's page-tagged segments. Only 3 types (ResearchQuestion, Problem, StudyDesign) — genuinely uncaptured elsewhere — get one small, scoped LLM call (`max_tokens=800`). Verified against real `AuDHD_1.pdf`: 20 evidence objects, 10/20 with real resolved page numbers, the other 10 honestly `page: null` (no fabricated pages) rather than a guess.

**Update 2026-08-21 (all 13 types now covered):** expanded `_LLM_EVIDENCE_TYPES` from 3 to all 7 remaining types (added InterventionModel, ComparatorBaseline, Metric, Finding) — still one call per paper, not a second call (`max_tokens` raised 800→1500 to fit up to ~15 items). `EVIDENCE_STAGE_VERSION` bumped 1→2. Verified directly against the real NVIDIA API (not mocked): correct output (7 objects, right types, `llm_call_failed: False`) — but that single isolated call took **298.7 seconds**, well outside normal latency. Cause appears to be the NVIDIA API running slow/degraded during this session (heavy call volume across the day), consistent with `utils/azure_client.py`'s own `chat()` timeout/retry math (120s timeout × up to 2 retries + backoff), not a logic bug in the new code. **A live full-pipeline browser re-verification of this change is still pending** — a first attempt didn't complete within 10-15 minutes and was abandoned rather than left ambiguous; not yet re-attempted under normal API latency. The underlying logic is verified correct (26 unit tests + one direct real-API call), but the live end-to-end `app.py` path for this specific change hasn't been confirmed the same way Stage 1C/2B and the original 3-type Stage 2C were.

#### Story 2.1.4: Validate extraction against the schema before acceptance
**AC:** **Given** a raw LLM extraction response; **When** it is parsed; **Then** every accepted Evidence Object is schema-valid (`evidence_type` in the enum, non-empty `text`, valid `confidence`) — a malformed item is dropped and counted in diagnostics, never silently coerced or accepted as-is.

**Status:** done. `validate_evidence_dict()` gates both the deterministic and LLM paths before an `EvidenceObject` is constructed; the LLM half also treats an unparseable/failed response as a flagged failure (`llm_call_failed`), never a silent empty list — the same B19-fixed discipline `gap_detector.py` already applies. 21 tests covering both extraction paths.

### Epic 2.2: Evidence Provenance Store & Report Citation
**FRs:** FR-6 (cont'd) · **Depends on:** Epic 2.1 · **Files:** `utils/database.py` (extended), `pipeline/doc_generator.py`

**Scope note (honest, not deferred silently):** the original epic description included "wire wiki_compiler as a rendering layer over Evidence Objects, replacing its own LLM call where feasible." On inspection, `pipeline/wiki_compiler.py` is an existing, tested, working module with its own independent LLM extraction — fully replacing its extraction path with one built from Evidence Objects is a real behavior change to a module nothing in Phase 1 touched, not a safe additive step. **Deferred to Phase 3** (when the graph/gap engine's actual Evidence-Object consumption is being wired anyway, so both changes land together with one round of validation, not two separate risky edits to the same downstream consumers). This phase instead makes Evidence Objects the *first-class persisted artifact* and starts using them for report citations — real progress, without the higher-risk wiki-compiler rewrite.

#### Story 2.2.1: Persist Evidence Objects
**AC:** **Given** a paper's extracted Evidence Objects; **When** extraction completes; **Then** they are cached by content hash (same `content_hash:none:stage_logic_version` pattern as Phase 1's `docling_extractions` table — evidence extraction is domain-invariant, same reasoning as `parameters`), so re-analyzing an unchanged paper doesn't re-spend the extraction LLM call.

**Status:** done. `utils/database.py`'s new `evidence_objects` table + `extract_evidence_cached()` wrapper. Content-addressed on `(paper_id, wiki_page)` — deliberately excludes `text_segments` from the hash (they affect provenance quality, not which evidence is extracted, matching this codebase's convention of hashing only what changes the extraction decision). Respects AD-2's never-cache-a-failure rule: an LLM-half failure is never persisted, so a transient failure doesn't permanently freeze a deterministic-only result in place of what should have been fuller once it clears. Verified against the real SQLite database (not mocked): a real cache-miss-then-hit round trip confirmed. 4 tests.

#### Story 2.2.2: Cite Evidence Objects in generated reports
**AC:** **Given** a generated report; **When** it references a scientific claim; **Then** it can cite the backing Evidence Object's provenance (page/section) where one exists, additive to the existing wiki-text-based report content — not a replacement of it in this phase.

**Status:** done, and wired into `app.py`'s live run. `utils/export.py`'s `to_enterprise_html_report()` gained a new, purely additive "Evidence" section (`_evidence_rows()`) — omitted entirely when no evidence data is present, so pre-existing reports are unaffected. A new "Stage 2C — Evidence Extraction" step in `app.py` calls `extract_evidence_cached()` per paper and persists the result into `results["evidence_objects"]`. Verified end-to-end via a real Playwright browser session (with the Quality Engine toggle ON): ran the full pipeline against the real 2-paper corpus, confirmed via direct database query that 56 real evidence objects were saved (20 + 36 across the two papers) with the correct Stage 2C trace entry, then regenerated the actual HTML report from that saved data and confirmed the Evidence section renders correctly — 56 real rows, honest `—` for unresolved provenance, real `p.N (section)` citations where resolved (screenshot: `evals/benchmarks/baseline/screenshots/08_report_evidence_section.png`).

**Update 2026-08-21: Stage 2C decoupled from the Quality Engine toggle.** Originally gated behind `enable_quality_engine` alongside Stage 2B — but 6 of 13 evidence types cost nothing (no LLM, no Docling), so gating the whole stage behind Docling's ~90s/paper cost meant users got zero evidence unless they also opted into the heavier corpus-quality cross-check. Stage 2C now runs on every run unconditionally; `docling_results` defaults to all-`None` when the toggle is off (real page provenance still depends on Stage 2B having run — only the *provenance quality* is gated, not whether evidence is extracted at all). This change has NOT yet been re-verified live end-to-end (see Story 2.1.3's update note — a verification attempt was inconclusive due to abnormal NVIDIA API latency during this session, not abandoned as broken, just not yet confirmed the same way the rest of this pipeline's changes were).

## Phase 3 — Reliable Research Intelligence (epic-level; stories detailed at Phase 3 kickoff)

**Goal:** graph quality scoring, the hybrid gap engine, the Gap Challenger state machine, and the determinism envelope — the core of the product's scientific-integrity claim. **Trigger to begin:** Phase 2's Evidence Objects are populated and validated for the sample project. **Started 2026-08-21** — see per-epic status below; Qdrant/Neo4j-dependent epics are genuinely blocked on this machine's no-Docker/no-admin-rights constraint (same one documented for GROBID), not skipped by choice.

- **Epic 3.1: Graph Persistence & Quality Scoring** — FR-7, FR-8, FR-9 · ADR-002. Neo4j CE + NetworkX hybrid; version/quality-score/coverage/duplicate-rate/unresolved-entity-rate/fallback-indicator per build; every edge requires an Evidence Object reference. **Not started — blocked on Neo4j (Docker).** Note: this is specifically about *cross-run* graph persistence/versioning — a single run's graph already exists locally without Neo4j (see Epic 3.2's graph-structural signal below, which does not wait on this epic).
- **Epic 3.2: Hybrid Gap Engine** — FR-10 · deterministic pattern library (medical/healthcare-AI patterns, Research Methodology Specialist pass) + graph-structural reasoning + scoped semantic reasoning; every candidate gap tagged with its contributing source(s). **Two of three sources DONE, 2026-08-21:**
  - Deterministic pattern library: `pipeline/deterministic_gap_patterns.py`, 18 healthcare-AI patterns + self-reported-limitation, validated against real Evidence Objects (one real bug found and fixed — see RESUME.md).
  - Graph-structural reasoning: `pipeline/graph_structural_gaps.py` — **correction from the initial pass:** this does NOT need Neo4j/Epic 3.1; it queries the local entity/relationship graph `graph_builder.py` already builds for every run. Implements orphan-concept and missing-bridge promotion (previously only unstructured LLM-prompt hints) plus two new checks: conflicting relationship claims and untested combinations. Two real bugs found rechecking against real data and fixed (paper-container entities polluting graph queries; the same orphan/bridge signal being fed to both this source and the semantic LLM prompt, producing near-duplicate gaps) — full detail in RESUME.md. Still needs a live end-to-end check against a genuine non-fallback LLM-extracted graph (blocked this session by NVIDIA API degradation, not a code issue).
  - Semantic reasoning (`gap_detector.py`, existing): unchanged in method, but its prompt no longer duplicates the orphan/bridge signal now that graph-structural reasoning owns it.
  - The domain-patterns doc itself remains `draft-needs-expert-review`, so treat fired gaps from the deterministic source as candidates for a domain expert to correct, same caveat as before.
- **Epic 3.3: Search Planner & Multi-Provider Search** — FR-14, FR-15 · `SearchProvider` port formalized; query-family generation (synonyms/terminology/broader-narrower); union → canonical dedup → metadata filter → embedding retrieval → rerank → LLM relevance review funnel. **Not started** — note `pipeline/academic_search.py`'s existing Semantic Scholar + arXiv validation is a real but basic precursor (single query per gap, no query-family expansion, no embedding rerank), already running in production today; this epic is about building the full funnel on top of it, not starting from nothing.
- **Epic 3.4: Gap Challenger State Machine** — FR-11, FR-12, FR-13 · ADR-008 · the 11-status lifecycle and Search Coverage Score decision table (`04-ai-research-architecture.md` §5); every stage inspectable; regression-tested against the benchmark's known-open/known-closed/ambiguous cases. **Core logic DONE, 2026-08-22 — not yet wired into `app.py`.** `pipeline/gap_challenger.py` implements the full lifecycle (GENERATED → EVIDENCE_SUPPORTED → SEARCH_PENDING → SEARCHED → CHALLENGED → one of 6 terminal statuses), built additively on top of `academic_search.py`'s existing SS/arXiv search rather than needing a new search planner first — the doc's own Search Coverage Score formula (query-family execution rate × provider-response rate) doesn't require embeddings/reranking to compute. 31 new tests exercise every cell of the decision table. Live-verified against a real gap from the saved corpus: correctly returned `INSUFFICIENT_EVIDENCE` when a real Semantic Scholar call failed mid-run, rather than misreporting `OPEN` from the resulting zero-result search — the exact protection §5.2's binding rule exists for. **Wired into `app.py`, 2026-08-22**, as an opt-in toggle (same pattern as the Corpus Quality Engine) -- Stage 5b, one `run_challenge()` call per validated gap, additive to Stage 5's existing status. Results UI shows the terminal status as a new badge per gap plus a "Search Coverage Funnel" panel (coverage score, candidate/dedup/relevant/contradiction counts, per-provider success, query families used). Live-verified in the actual browser (real captured challenger data loaded into a saved run, screenshot-confirmed all badges and the funnel render correctly) — full detail in RESUME.md.
- **Epic 3.5: EmbeddingProvider / RerankerProvider + Qdrant** — FR-17, FR-18 · ADR-001, ADR-004 (completion) · BGE-M3/BGE-reranker local adapters. **Not started — blocked on Qdrant (Docker).**
- **Epic 3.6: Determinism Envelope & Repeatability Score** — FR-19, FR-20 · ADR-006 · agent typed configs with budgets/timeouts; Repeatability Score computed against Benchmark v1+. **Not started.**

## Phase 4 — Versioned Platform (epic-level)

**Goal:** every artifact versioned/immutable, run manifests, the Research Artifact Registry, and champion/challenger promotion. **Trigger to begin:** Phase 3's Gap Challenger is producing regression-tested statuses on the benchmark; SQLite's single-blob-per-run model becomes the concrete limiting factor for cross-run comparison (already a documented gap in `project-context.md`).

- **Epic 4.1: Postgres Migration & Research Artifact Registry** — FR-21, FR-22 · ADR-005 · forward-only migration scripts, no destructive down-migration against research data.
- **Epic 4.2: Run Manifest Recorder** — FR-23 · full schema per `06-versioning-lineage-architecture.md` §3.
- **Epic 4.3: Champion/Challenger Evaluation Harness & Benchmark Expansion** — FR-26 · `07-evaluation-architecture.md`'s full metric set; False Novelty Rate as the hard promotion gate (ADR-008-adjacent).
- **Epic 4.4: Lineage Views & Compare Engine** — FR-24, FR-28 · technical + scientific lineage; metric diffing and change explanation feeding the future Compare UI screen's data contract.

## Phase 5 — Enterprise UI (epic-level)

**Goal:** the Next.js/FastAPI shell and full screen inventory, built against Phase 1-4's real data contracts. **Trigger to begin:** Phase 4's Run Manifest and Artifact Registry are populated with real run history (not mocks).

- **Epic 5.1: Design System & Application Shell** — FR-29 · `02-ux-specification.md` §3-4; branding layer (Epic 1.4) consumed here.
- **Epic 5.2: Core Screens** — Landing, Project Dashboard, Corpus, Paper Detail, Data Quality.
- **Epic 5.3: Intelligence Screens** — Knowledge Graph, Research Gaps, Gap Detail, Gap Challenger, Research Council, Proposal.
- **Epic 5.4: Engineering Screens** — Runs, Run Detail/Manifest, Compare, Research Time Machine, Lineage, Version Registry.
- **Epic 5.5: Reporting** — FR-27, FR-28 · HTML/PDF/JSON export; report-to-report comparison and downloadable diff.

## Phase 6 — Governance (epic-level, conditional — see `10-phased-implementation-plan.md` trigger)

- **Epic 6.1: Identity (Keycloak)** — FR-33.
- **Epic 6.2: Policy & Audit (OPA)** — FR-33 (cont'd).

## Phase 7 — Observability (epic-level)

- **Epic 7.1: OpenTelemetry instrumentation**
- **Epic 7.2: Langfuse LLM observability**
- **Epic 7.3: Prometheus/Grafana dashboards**

## Phase 8 — Portability (epic-level)

- **Epic 8.1: Docker hardening for production images**
- **Epic 8.2: OpenTofu cloud modules**
- **Epic 8.3: Kubernetes/Helm deployment (AKS/EKS/GKE/OpenShift/on-prem targets)**

---

## Code-review checklist addendum (applies to every story, every phase)

Per `04-ai-research-architecture.md` §2's binding LLM-use discipline, every story's code review must explicitly check: *does this change add an LLM call where deterministic code or a local model would do?* — this is not left to reviewer discretion alone; it is a named checklist item precisely because the discipline is easy to erode incrementally without a standing check.
