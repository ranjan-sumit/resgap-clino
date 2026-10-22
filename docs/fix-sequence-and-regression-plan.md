# Fix sequence, PR plan and end-to-end regression plan

Covers every finding in `docs/backend-fix-list.md` (B1-B26) and `docs/frontend-proposal.md` (F1-F13 and Steps 0-7).
Each PR is small enough to review and revert on its own. Nothing here is implemented yet.

## 1. Ground rules

- One PR per section below, in this order. A PR merges only when its **gate** passes (section 4).
- Every PR adds tests first, then code. A bug fix includes a test that fails before the fix.
- A PR never changes more than its stated scope; unrelated cleanup goes in its own PR.
- Every PR description lists: Closes, Depends on, Changes, New tests, Regression suites run, Acceptance, Rollback.
- Old saved runs must keep opening after every PR (the legacy-run fixture is in the gate).
- After any change outside `app.py`, restart the app before manual review (Streamlit keeps modules in memory).

## 2. Sequence at a glance

| PR | Title | Closes | Depends on | Size | Risk |
|---|---|---|---|---|---|
| 00 | Baseline: commit existing work in logical commits, untrack junk | hygiene, B25 (part) | none | M | low |
| 01 | Test infrastructure, fixtures and CI | none (enables all) | 00 | M | low |
| 02 | Resilience: cross-links failure, paper limit, duplicates | B1, B6 | 01 | S | low |
| 03 | Unreadable PDFs: scanned, encrypted, corrupt | B2 | 02 | S | low |
| 04 | Per-run call log and error list | B4 | 01 | M | low |
| 05 | Shared rate limiter and provider-keyed options | B5, B7 | 04 | M | medium |
| 06 | UI foundations: `ui/` package and view models | F-Step 0 | 01 | M | low |
| 07 | Frontend quick wins A: trace, run header, layout, key status | F1, F2, F4, F8, F12 | 06, 04 | M | low |
| 08 | Frontend quick wins B: re-run with the project's papers | F5 | 07 | S | low |
| 09 | Background run worker and live stage checklist | B3, F9 | 04, 07 | L | high |
| 10 | Run storage slimming, UTC timestamps, lazy loading | B18, B22 | 01 | M | medium |
| 11 | Cost guard, quality metrics, manifest versions, golden eval | B19, B20, B21 | 04, 10 | M | medium |
| 12 | Sidebar, Settings, New analysis, New project, cache inspector | F6, F7, B26 | 07, 08 | L | medium |
| 13 | Evidence tab, Overview, Wiki | F3 | 07 | M | low |
| 14 | Literature scout upgrade, Gaps tab, feedback wiring, coverage rule | B14, B8, B16, F11 (gaps, proposals) | 13 | L | medium |
| 15 | Parsing quality and grounded graph, Graph tab | B9, B10, B11, F11 (graph) | 13 | L | medium |
| 16 | Parameters and Lab, Lab tab | B12, B15, F11 (lab) | 11 | L | medium |
| 17 | Critic and reviewer calibration, variance control | B13, B17 | 11, 14 | M | medium |
| 18 | Run management and project settings | F10 | 10, 12 | M | medium |
| 19 | Report tab, preview and export regression | Export | 13 | M | low |
| 20 | Design system and accessibility | Step 6 | 12-19 | L | low |
| 21 | Security hardening, memory profile, dead-code removal | B24, B23, B25 | 01 | M | medium |
| 22 | Audit and fix of unaudited modules (8 small PRs) | "Not audited" list | 11 | L | varies |
| 23 | Cloud readiness: storage adapter, secrets, optional sign-in | F13 | 10, 18 | L | high |
| 24 | Release candidate: full regression, docs, tag | all | all | M | low |

Why this order: PRs 00-05 remove silent failures and give every later PR a test net and logs; 06-09 fix what users see first and the run lifecycle; 10-11 make runs cheap and measurable before the heavy quality work; 12-20 build the new workspace and quality features on that base; 21-24 harden, audit and release.

## 3. PR descriptions

### PR-00 Baseline checkpoint
- **Closes:** hygiene; part of B25.
- **Changes:** split the existing uncommitted work into logical commits (each builds and passes tests): (1) SQLite migrations 0001-0005 and `utils/database.py`; (2) PyMuPDF parser and section building; (3) projects: store, feedback, Project view; (4) per-role models: router, settings, providers; (5) agentic pipeline: Evidence Reader, gap agents, literature scout, proposal reviewer, grounding, Lab gate and module, coverage; (6) UI changes so far; (7) tests and docs. Untrack `.claude`, `_bmad`, `_bmad-output`, `evals` images; extend `.gitignore` (`data/`, `*.db`, scratch files).
- **New tests:** none. Verify the suite is green at every commit (`git rebase --exec "python -m pytest tests -q"`).
- **Regression:** full suite; secret scan of the new history.
- **Acceptance:** clean `git status`; repo size down ~16 MB; no keys in history.
- **Rollback:** the commits are independent; revert any one.

### PR-01 Test infrastructure, fixtures and CI
- **Changes:** `tests/conftest.py` with markers `ui`, `e2e`, `real`; `pytest.ini`; `tests/fixtures/make_golden_run.py` (synthetic 3-paper run, no copyrighted text) and a **legacy-run** fixture (old schema: no `paper_profiles`, no trace, no `supplementary_gaps`); DB seeding helper; AppTest helper; Playwright harness at 1440x800, 1024x768, 390x844 (saves screenshots to `tests/ui/_artifacts/`); fake model client with scripted replies and failures; `scripts/smoke_real_run.py` (two tiny PDFs, token cap); `.github/workflows/ci.yml` (unit + AppTest on every PR, Playwright nightly, secret scan with gitleaks, dependency audit). Review or remove the stale `scripts/e2e_poll.py`.
- **New tests:** fixtures load; seeding is idempotent; the fake client scripts failures; marker selection works.
- **Regression:** full suite on the new CI.
- **Acceptance:** CI green on a clean checkout; a deliberate failing test turns CI red.
- **Rollback:** infra only; revert the workflow file.

### PR-02 Resilience: cross-links, paper limit, duplicates (B1, B6)
- **Changes:** `pipeline/wiki_compiler.py` catches a failed cross-links call, records a trace warning, continues; `run_pipeline.py` warns and lists papers beyond the limit; duplicates collapse by content hash with a notice.
- **New tests:** cross-link failure completes the run with a warning row; six uploads give a visible warning naming the dropped files; the same PDF twice is analysed once.
- **Regression:** R-02, R-04, R-12.
- **Acceptance:** none of the three cases can crash or silently change the paper set.

### PR-03 Unreadable PDFs (B2)
- **Changes:** Stage 1 detects "no text layer", encrypted and corrupt files; such a paper is skipped with a per-paper error shown in the trace and coverage table; if fewer than 2 readable papers remain, the run stops with a clear message. Optional follow-up flag for vision OCR (off by default).
- **New tests:** scanned PDF (image-only fixture), encrypted PDF, corrupt PDF, one bad paper among three, all papers bad.
- **Regression:** R-02, R-03, R-04.
- **Acceptance:** the wiki model is never called on empty text.

### PR-04 Per-run call log and error list (B4)
- **Changes:** `utils/call_log.py`; the router writes `runs/<id>/llm_calls.jsonl` (stage, model, latency, tokens, error, prompt hash; full prompts only if enabled); swallowed exceptions in the pipeline record a structured error in the manifest; log size cap and redaction of keys.
- **New tests:** a failed call appears in the log and manifest errors; keys never appear in the log; log is written when the run fails midway.
- **Regression:** R-11, R-12, R-18.
- **Acceptance:** any failed or degraded stage can be explained from the saved run alone.

### PR-05 Rate limiter and provider-keyed options (B5, B7)
- **Changes:** per-(provider, model) token bucket in the router, honouring `Retry-After` globally; `_MODEL_EXTRA_BODY` and token boosts keyed by (provider, model); documented limits per model in the registry.
- **New tests:** 20 parallel calls on a 5 rpm model never exceed the limit (fake clock); a 429 pauses all callers for that model; Groq and NVIDIA `gpt-oss-20b` receive different options.
- **Regression:** R-04, R-05, R-07, R-11.
- **Acceptance:** a full run on the free tier produces no 429 in the log.

### PR-06 UI foundations (Frontend Step 0)
- **Changes:** `ui/theme.py`, `ui/components.py`, `ui/viewmodels.py` (`run_header`, `trace_rows`, `overview`, `evidence_rows`, `gap_rows`, `stage_status`); move existing display logic out of `app.py` without changing output.
- **New tests:** view-model unit tests; golden-vs-before screenshot comparison shows no visible change.
- **Regression:** R-16, R-17.
- **Acceptance:** `app.py` shorter, identical screens.

### PR-07 Frontend quick wins A (F1, F2, F4, F8, F12)
- **Changes:** Trace tab reads the saved trace (models, tokens per stage, fallbacks, agent diagnostics); run header replaces the "Showing saved run" strip; "New analysis" collapses when a run is loaded; hero only for an empty project and with correct copy; "Off" cards replaced by one note; Semantic Scholar key status in the keys line; `use_container_width` replaced by one helper.
- **New tests:** trace for golden and legacy runs; hero absent with runs, present when empty; no Off cards; no deprecated call left (grep test); Playwright: first result heading visible at 1440x800 without scrolling.
- **Regression:** R-13, R-16.
- **Acceptance:** F1, F2, F4, F8, F12 closed.

### PR-08 Re-run with the project's papers (F5)
- **Changes:** `project_store.list_papers`; New-analysis panel lists stored papers with checkboxes; run enabled at 2-5 selected; no upload needed.
- **New tests:** list and read papers; AppTest with patched pipeline; Playwright flow ends at a saved run; duplicate selection blocked.
- **Regression:** R-01, R-02, R-12.

### PR-09 Background run worker and live checklist (B3, F9)
- **Changes:** pipeline runs in a worker thread with progress persisted in a `run_jobs` table (migration 0006a); `duration_s` per trace row; UI polls and shows a stage checklist with elapsed and expected time (from past manifests, with defaults); sub-progress for finders, scout and reviewer; completion toast opens Overview; a stage over twice its expected time shows a notice. Honest limit: cannot cancel from the UI.
- **New tests:** job lifecycle (queued, running, done, failed); drop the session and reconnect, run still completes; scripted callbacks update the checklist; stuck-stage notice; app restart marks orphaned jobs failed.
- **Regression:** R-12, R-16, full pipeline e2e with fakes.
- **Acceptance:** refreshing the tab never loses a run. Risk note: highest-risk PR; ships behind a setting for one release.
- **Rollback:** setting off returns to the in-session run.

### PR-10 Storage slimming, UTC, lazy loading (B18, B22)
- **Changes:** stop storing `corpus` text; store section text and the Lab zip as files in the project folder; lazy `load_run`; migration converting old rows (idempotent, keeps a backup); timestamps stored in UTC with timezone.
- **New tests:** new run under 300 KB; old runs open and report identically; migration twice is a no-op; timezone round trip.
- **Regression:** R-13, R-17.
- **Rollback:** migration keeps a backup file; reader accepts both layouts.

### PR-11 Cost guard, quality metrics, manifest versions, golden eval (B19, B20, B21)
- **Changes:** pre-run token and cost estimate, per-run cap and warning near quota; `run_quality` in the manifest (quote rate, unsupported-number rate, duplicate rate, coverage, latency, tokens); prompt and agent-config versions recorded; `scripts/golden_eval.py` fails when metrics regress; stale `AgentConfig.model` labels removed.
- **New tests:** over-cap run stops cleanly; metrics present and correct on fixtures; eval fails when quote rate is forced down; manifest lists every agent version.
- **Regression:** R-12, R-17.

### PR-12 Sidebar, Settings, New analysis, New project, cache inspector (F6, F7, B26)
- **Changes:** slim sidebar (project switcher, compact run list with chips, New analysis, Settings); Settings page via `st.navigation` (keys with "in use" status, models, advanced options, references, cache size and clear per stage); 4-step New analysis dialog; New project with domain, interest, optional papers; empty-state guide; local paths hidden outside local mode.
- **New tests:** at most 4 interactive controls in the sidebar; dialog validation per step; back and forward keep state; cancel changes nothing; project stores domain and interest; cache clear forces recompute; keys never written to disk.
- **Regression:** R-01, R-11, R-16.
- **Fallback:** if dialogs are brittle with file upload, use a dedicated page.

### PR-13 Evidence tab, Overview, Wiki (F3)
- **Changes:** Overview (default) with the numbers that matter, coverage table, top gaps and proposal, warnings summary; Evidence tab (filter by paper, type, has-page; quote, page, section; reverse links to citing gaps); Wiki shows study type and links facts to quotes; render only the active view.
- **New tests:** filter logic and reverse index (unit); AppTest render on golden and legacy runs; Playwright filter flow; load-time and DOM budgets.
- **Regression:** R-05, R-13, R-16, R-19.

### PR-14 Literature scout upgrade, Gaps tab, feedback wiring, coverage rule (B14, B8, B16, F11)
- **Changes:** parallel providers, batched planner, DOI dedupe, URL and DOI stored, cache TTL; Gaps tab with sort and filter (rank, status, finder, paper), compact list and detail, paper chips, linked citations; Proposals tab with collapsible sections, gap link, accept or star (feedback table), compare two; feedback ratings fed into critic and reviewer prompts and shown in the trace; warning when a paper supports no gap and optional per-paper minimum.
- **New tests:** 8 gaps in under half the time on fakes; expired cache entry re-searched; URLs present; downvoted gap type penalised next run; coverage rule on a synthetic one-paper-dominant set; sort and filter unit tests; Playwright flow.
- **Regression:** R-07, R-08, R-09, R-14, R-16.

### PR-15 Parsing quality and grounded graph, Graph tab (B9, B10, B11)
- **Changes:** table extraction pass with vision fallback, fed to the reader and parameter extractor; filter repeated header text and short title-like blocks; graph built from quoted evidence, orphan-linking pass, fixed type list per corpus, quote ids on relations; Graph tab with relations table and evidence, filters, orphan explanation.
- **New tests:** ruled-table fixture yields rows; header text absent in sections; orphan share below threshold on the golden corpus; every relation has an evidence id; relations table filters.
- **Regression:** R-03, R-05, R-06, R-16.

### PR-16 Parameters and Lab (B12, B15)
- **Changes:** tag parameters as measured or opinion and exclude opinion from simulation and the gate count; numeric sanity pass; audit each simulation algorithm's input requirements and refuse unsuitable inputs; de-duplicate council output; extend grounding to named entities; Lab tab with sufficiency verdict first and a per-paper parameter table.
- **New tests:** survey proportions tagged opinion; each algorithm on known inputs (and refuses bad ones); duplicate insights merged; grounding flags an unsupported entity; Lab tab states.
- **Regression:** R-10, R-15, R-16.

### PR-17 Critic and reviewer calibration, variance (B13, B17)
- **Changes:** rubric anchors with examples; different model for the critic when available; score-spread tracking; lower temperature on structured stages; repeatability metric stored per run.
- **New tests:** score distribution not constant on a mixed-quality fixture; two runs on the golden corpus overlap above a threshold (recorded replies); metric stored.
- **Regression:** R-07, R-09, R-12.

### PR-18 Run management and project settings (F10)
- **Changes:** run board with status chips, models, duration, tokens, Lab; rename, archive, delete, merge duplicates; migration 0006 (archived flag); project settings (name, description, defaults, delete project); compare view restyled.
- **New tests:** migration on old rows; rename, archive, delete keep files consistent; archived hidden by default; compare with and without Lab; no hash IDs on screen.
- **Regression:** R-01, R-13, R-17.

### PR-19 Report tab and export regression
- **Changes:** in-app preview, section checklist, "Save to project"; export paths covered by tests for every format.
- **New tests:** HTML, PDF, Markdown, JSON with and without Lab; preview equals the saved file; saved report replaces the automatic one.
- **Regression:** R-15.

### PR-20 Design system and accessibility
- **Changes:** one token set, one card component, consistent icons, consistent empty, loading and error components; contrast, focus, labels; readable at 390 px; microcopy pass.
- **New tests:** axe finds no critical violations on the five main screens at three widths; screenshot review.
- **Regression:** R-16.

### PR-21 Security, memory, dead code (B24, B23, B25)
- **Changes:** page cap, parse timeout, size check and optional worker-process isolation for PDFs; memory profile and fixes (free session results and report bytes, cap caches); remove the single-call gap detector, `_LegacyBackend`, old validator, archived React/FastAPI and Postgres remnants; delete tests that only covered removed code.
- **New tests:** 2,000-page PDF refused quickly; memory flat across 20 simulated session loads; suite green after removal.
- **Regression:** R-18, R-19, full suite.

### PR-22 Audit and fix of unaudited modules (8 small PRs)
Each follows the same pattern: run the module on real input, write the findings, fix, add tests. 22a reference extraction (Stage 1B); 22b Corpus Quality Engine (2B, 1C); 22c Gap Challenger (5b) and its NVIDIA rerank dependency; 22d figure analysis; 22e OpenAI, Groq and custom providers; 22f graph snapshots and diffs; 22g lineage and the project zip; 22h Docker image.
- **Regression:** R-11, R-13, plus each module's own scenarios.

### PR-23 Cloud readiness (F13)
- **Changes:** storage adapter for the database and project files (Supabase or S3, chosen with you), local-disk fallback; Streamlit secrets; optional sign-in; caching of `load_run`; optional read-only share link.
- **New tests:** adapter contract tests against a local fake; redeploy-survival check; secrets never rendered; app starts with only secrets configured.
- **Regression:** R-17, R-18, R-20.

### PR-24 Release candidate
- Run the full regression (section 5) including the real-model smoke and the manual checklist; update DEPLOY.md and README; tag; record known issues.

## 4. Regression system

**Layers**
- U: pure unit tests (view models, parsers, scoring, migrations). A: Streamlit AppTest on seeded databases with the pipeline patched. E: Playwright end to end at three viewports. R: real-model smoke (manual trigger, token-capped). M: manual checklist at release.

**Gates**
- Per PR (about 5 minutes): `python -m pytest tests -q -m "not ui and not real"`; secret scan; migration test; legacy-run fixture opens.
- Pre-merge for UI PRs: `python -m pytest tests/ui -m ui` at three viewports; screenshots attached to the PR; no `stException`, no console errors, no new log warnings.
- Nightly: full Playwright suite, memory and load-time budgets, golden eval.
- Release: all of the above, plus R-layer smoke and the M checklist.

**Fixtures:** golden run (3 papers, quoted evidence, gaps, proposals, Lab skipped), golden run with Lab results, legacy run (old schema), empty project, scanned PDF, encrypted PDF, corrupt PDF, ruled-table PDF, six-paper upload, duplicate upload, scripted failure client (timeout, 429, malformed JSON, empty reply).

**Budgets:** golden run loads in under 3 s; tab switch under 1 s; under 4,000 DOM nodes per tab; a new run's saved JSON under 300 KB; free-tier run produces no 429.

## 5. End-to-end regression matrix

| ID | Area | Scenarios (each is an automated test unless marked) | Layer |
|---|---|---|---|
| R-01 | Projects | create with domain and interest; switch; default project exists; delete project; path hidden outside local mode; project papers listed | A, E |
| R-02 | Input | 2 papers ok; 1 paper blocked; 6 papers warns and names dropped; duplicates collapse; non-PDF rejected; reuse project papers; 200 MB limit | A, E |
| R-03 | Parse | headings and sections; header furniture removed; table rows extracted; scanned, encrypted, corrupt PDFs flagged; reading order on two columns (fixture) | U |
| R-04 | Wiki | one page per paper; parallel order preserved; cache hit and version bump; one paper failing; cross-link failure; empty page never cached | U, A |
| R-05 | Evidence | every item has quote and page; unverified quote dropped; unsupported number dropped; study type recorded; long paper read in parts; fallback to wiki recorded | U |
| R-06 | Graph | vocabulary follows study type; orphan share under threshold; every relation has evidence id; snapshot saved and diffed | U, A |
| R-07 | Gaps | three finders run; ungrounded gap dropped; critic merge, drop, rank; max gaps; coverage warning; supplementary list separate; last-resort fallback | U |
| R-08 | Literature | planner queries; two providers called; throttle respected; failed search is unverified; partial failure noted and not cached; TTL expiry; URL stored | U |
| R-09 | Proposals | draft; review accept, revise once, reject; keep gap link; zero-result trace warning; "Generate proposals now" fills a run | U, A, E |
| R-10 | Lab | parameters tagged; gate skips simulation when data is thin; discovery runs; council with fallback; empty-council banner; grounding flags invented numbers; Lab attaches to the same run | U, A |
| R-11 | Models and keys | presets; Test models; fallback chain; quota error falls back; each provider fake; keys from env, never persisted or logged; settings file persists choices | U, A |
| R-12 | Run lifecycle | start, progress, finish; refresh mid-run survives; failure mid-run saves what exists; token meter; budget cap stops cleanly; manifest and call log saved; orphaned job marked failed after restart | U, A, E |
| R-13 | History and Project view | recent runs; load; rename, archive, delete; compare two runs; repeatability; lineage; graph history; files; project zip | A, E |
| R-14 | Feedback | per-gap rating, reason, comment; run note; export JSON; feedback shapes next critic prompt | A |
| R-15 | Reports | HTML, PDF, Markdown, JSON with and without Lab; preview equals file; save replaces automatic report | U, A |
| R-16 | UI/UX | results above the fold; tabs and filters; empty, loading, error states; three viewports; axe no critical; no deprecation warnings | E |
| R-17 | Data and migrations | fresh DB; upgrade from each earlier schema; legacy run opens; concurrent init; run size under budget; UTC round trip | U |
| R-18 | Security | secret scan clean; no keys in logs or files; path traversal refused; oversize and page-cap PDFs refused; upload parse timeout | U |
| R-19 | Performance | load, tab switch, DOM and memory budgets; memory flat over 20 sessions | E |
| R-20 | Cloud | starts with secrets only; storage adapter survives redeploy; read-only share link | E, M |
| R-21 | Real model (R) | one real run on two tiny PDFs: all stages complete, quote rate above threshold, no 429, tokens under cap | R |
| R-22 | Manual (M) | read one full report end to end; open every tab on a real run; try the New project and New analysis flows as a new user | M |

## 6. Traceability: every finding to its PR and regression

| Finding | PR | Regression IDs |
|---|---|---|
| F1, F2, F4, F8, F12 | 07 | R-13, R-16 |
| F3 | 13 | R-05, R-13, R-16 |
| F5 | 08 | R-01, R-02, R-12 |
| F6, F7 | 12 | R-01, R-11, R-16 |
| F9 | 09 | R-12, R-16 |
| F10 | 18 | R-13, R-17 |
| F11 | 14, 15, 16 | R-07, R-06, R-10 |
| F13 | 23 | R-20 |
| B1, B6 | 02 | R-02, R-04 |
| B2 | 03 | R-02, R-03 |
| B3 | 09 | R-12 |
| B4 | 04 | R-11, R-12, R-18 |
| B5, B7 | 05 | R-11 |
| B8, B14, B16 | 14 | R-07, R-08, R-14 |
| B9, B10, B11 | 15 | R-03, R-06 |
| B12, B15 | 16 | R-10 |
| B13, B17 | 17 | R-07, R-09 |
| B18, B22 | 10 | R-13, R-17 |
| B19, B20, B21 | 11 | R-12 |
| B23, B24, B25 | 21 | R-18, R-19 |
| B26 | 12 | R-11 |
| Not-audited list | 22a-h | module scenarios |

## 7. Decisions needed before PR-12 and PR-23

1. Stay on Streamlit through PR-20 (recommended).
2. Cloud storage: Supabase, S3, or none for now (PR-23).
3. Sign-in and sharing needed, or internal only.
4. Dark theme wanted or not (PR-20).
5. Who the users are (sets how much onboarding copy to keep).


---

## 8. Amendments after the second pass

New findings B27-B41, T1-T2 (backend list) and F14-F20 (frontend proposal) are placed as follows. The original numbering is kept; new PRs use letters.

### New PRs

#### PR-02a Cache correctness (B27)
- **Changes:** every stage cache key includes (provider, model); all stage versions bumped once (this invalidates old caches by design); trace rows say "served from cache"; manifest records the model that actually ran.
- **New tests:** same input with two models gives two entries; switching the model forces a recompute; manifest names the real model.
- **Regression:** R-04, R-05, R-08, R-11, R-23.
- **Depends on:** PR-02. **Size:** S. **Risk:** low. **Rollback:** revert; old keys are simply unused.

#### PR-03a Safe rendering and input hygiene (B28, B33, B37)
- **Changes:** one `esc()` helper used in every HTML f-string, plus a lint test; strip invisible text from PDFs; wrap paper text as quoted data with an explicit instruction; flag instruction-like phrases in the trace; warn and read in further parts beyond 200,000 characters.
- **New tests:** hostile title renders as text on every tab; injection fixture produces a flag and no behaviour change; 300,000-character fixture is fully read or exactly reported.
- **Regression:** R-16, R-18, R-24.
- **Depends on:** PR-03. **Size:** M. **Risk:** low.

#### PR-04a Agent output schemas (B38)
- **Changes:** JSON schema per agent (reader, finders, critic, scout, reviewer, parameters, council); validation errors counted and written to the call log.
- **New tests:** invalid item rejected and logged for each agent; valid items unchanged.
- **Depends on:** PR-04. **Size:** M. **Risk:** low.

### Changes to existing PRs

| PR | Added scope | New tests |
|---|---|---|
| 01 | T1 recorded real-response fixtures per agent; T2 coverage measurement with a rising floor; dependency lock and Python-version matrix (B34) | fixtures replay; CI installs from the lock file |
| 02 | B30: content-hash paper ids everywhere (filename for display only) | two different PDFs with one filename both keep their evidence |
| 03 | B29: temp copies deleted on every exit path | no temp files after a failed run |
| 09 | F15 completion notice; F19 "Resume" of a failed run | resume reuses caches and retries only the failed stage |
| 12 | F14 URL state (project, run, tab, deep links); B32 privacy notice and per-project "confidential" flag | confidential project refuses a free-tier model; refresh keeps the place |
| 13 | F16 copy-with-citation and copy-link; F20 search (stretch) | copied text includes page and section |
| 15 | B36 DOI and metadata extraction; defensive filter for uploaded papers in "existing work" | DOI fixture; uploaded paper excluded |
| 18 | F18 confirm dialogs and archive-before-delete | confirm lists affected runs and files |
| 19 | full references in the report from stored metadata | report lists authors, journal, year, DOI |
| 20 | F17 inline definitions and glossary | every status label has a definition |
| 21 | B31 licence decision (keep, buy, or switch parser); B39 backup and restore | decision recorded; restore test |
| 22e | B35 model health check and retired-model handling; B41 non-English fixture | 404 model hidden; warning on non-English paper |
| 24 | B40 documentation refresh | release checklist item |

### New regression scenarios

| ID | Area | Scenarios | Layer |
|---|---|---|---|
| R-23 | Cache correctness | model change recomputes; version bump recomputes; trace shows cache hits; manifest names the real model | U |
| R-24 | Safe rendering and hostile input | markup in titles is text on every tab; prompt-injection PDF is flagged and harmless; hidden text stripped; long paper handled | A, E |
| R-25 | Identity | same filename, different content; same content, different filename; DOI de-duplication | U |
| R-26 | Privacy | confidential project blocks free-tier providers; keys and paper text absent from logs; temp files removed | U, A |
| R-27 | Licensing and dependencies | licence report generated in CI; lock-file install; Python version matrix | CI |
| R-28 | Navigation state | refresh keeps project, run and tab; deep link opens the right gap; back button works | E |
| R-29 | Recovery | resume a failed run; backup and restore; failed-run notice | U, E |

### Traceability additions

| Finding | PR | Regression IDs |
|---|---|---|
| B27 | 02a | R-23 |
| B28, B33, B37 | 03a | R-16, R-18, R-24 |
| B29 | 03 | R-26 |
| B30 | 02 | R-25 |
| B31, B39 | 21 | R-27, R-29 |
| B32 | 12 | R-26 |
| B34 | 01 | R-27 |
| B35, B41 | 22e | R-11 |
| B36 | 15, 19 | R-25, R-15 |
| B38 | 04a | R-07, R-09 |
| B40 | 24 | release checklist |
| F14 | 12 | R-28 |
| F15, F19 | 09 | R-12, R-29 |
| F16, F20 | 13 | R-13 |
| F17 | 20 | R-16 |
| F18 | 18 | R-13 |
| T1, T2 | 01 | all |
