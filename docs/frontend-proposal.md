# Clinova frontend: proposal to reach a polished, trustworthy product

Status: proposal for review. Nothing here is implemented yet.
Based on a screen-by-screen review of the running app (1440x800 laptop window) with the latest run loaded.

## 1. What is wrong today (evidence, not opinion)

| # | Finding | Where |
|---|---|---|
| F1 | The first screen shows no results. Results start ~1,000 px down on every tab, below the hero, project header, "saved run" strip, upload form, models panel, run button and 9 stat cards. | Home |
| F2 | Pipeline Trace says "Run the main analysis to see the pipeline trace here" for a saved run that has a complete stored trace. | Trace tab |
| F3 | The 64 verified quotes (the main output of the redesign) are not shown anywhere except inside a gap expander. | Missing Evidence view |
| F4 | Three "Off Off Off" cards for a feature that is switched off. | Header |
| F5 | The Run button is disabled ("Add 2-5 PDFs") though the project already stores the papers; every re-run means re-uploading. | Run panel |
| F6 | Sidebar holds ~11 controls + 2 expanders (~1,100 px) mixing navigation with run settings and API keys. | Sidebar |
| F7 | New-project dialog asks only name + description; the landing state after creating is empty with no guidance. The Project view shows a local absolute path. | New project, Project view |
| F8 | Hero copy is stale ("Semantic Scholar and arXiv") and shown on every visit. | Hero |
| F9 | Run progress is one text line and a bar; users read slow stages as "stuck". | Running |
| F10 | Project run list is a plain table with hash IDs; no status, models, duration or tokens; duplicates and test runs mixed in; no rename, archive or merge. | Project view |
| F11 | Gaps, proposals, graph relations and lab parameters have no sort, filter or detail view. | Several tabs |
| F12 | `use_container_width` deprecation warnings spam the logs. | Everywhere |
| F13 | On Streamlit Cloud the disk is ephemeral: saved runs and papers are lost on redeploy. | Platform |

## 2. Target experience

- Sidebar: project switcher, compact run list (name, status chips, date), "New analysis" button, Settings link. Nothing else.
- A run opens on a **run header** (name, date, papers, models, duration, status chips, actions) and an **Overview** tab with the numbers that matter.
- Tabs: Overview, Evidence, Gaps, Proposals, Lab, Report, Audit trail (Wiki and Graph under an "Explore" group).
- "New analysis" is a 4-step dialog: Papers (upload or reuse the project's), Focus (domain, interest, gap type), Models ("Recommended" by default), Review and run.
- A live run shows a stage checklist with elapsed and expected time.
- Every screen has deliberate empty, loading and error states.

## 3. Testing strategy (applies to every step)

Layers, cheapest first. Each step adds tests in the layers it touches.

1. **View-model unit tests** (pytest, no Streamlit). All display logic moves into pure functions in `ui/viewmodels.py` (for example `run_header`, `evidence_rows`, `gap_rows`, `trace_rows`, `overview`, `stage_status`), so it is tested in milliseconds.
2. **Streamlit AppTest** (headless, no browser). Renders pages against a seeded database, asserts widgets, text, state and that no exception is raised. The pipeline is patched, so no model calls.
3. **Playwright end-to-end** (marker `ui`, skipped if Playwright is missing). Runs at 1440x800, 1024x768 and 390x844. Asserts: no `stException`, no console errors, key text above the fold, tab switching, filters, dialogs. Saves screenshots to `tests/ui/_artifacts/` for review. Accessibility check with axe: no critical violations.
4. **Fixtures.** `tests/fixtures/make_golden_run.py` builds a synthetic but realistic 3-paper run (no copyrighted text). A second fixture is a **legacy run** (old schema, no `paper_profiles`, no trace) so old saved runs never break.
5. **Real-model smoke** (manual, not CI): one real run on two small PDFs, to catch what mocks cannot.
6. **Budgets.** Loading the golden run under 3 s; tab switch under 1 s; fewer than 4,000 DOM nodes on any tab.

Definition of done for every step: new tests written first, full suite green (`python -m pytest tests -q`), no new console or log warnings, screenshots attached for your review, one commit per step so any step can be reverted alone.

## 4. Steps

### Step 0: Foundations (no visible change)
- Add `ui/` package: `theme.py` (CSS tokens), `components.py` (badge, card, stat, empty_state, error_card, run_header), `viewmodels.py`.
- Add golden and legacy run fixtures, a DB seeding helper, an AppTest helper, a Playwright harness with the three viewports.
- Add pytest markers `ui` and `e2e`; add Playwright to `requirements-dev.txt`.
- Tests: viewmodel unit tests for the first extracted functions; a smoke test that the app still loads both fixtures.
- Accept: no visual change, suite green, `app.py` shorter. Effort ~1 day. Risk: low.

### Step 1: Quick wins (fixes F1, F2, F4, F5, F8, F12)
1. **Trace from saved run.** `trace_rows(results, manifest)`; also show models, tokens per stage, fallbacks, gap-agent diagnostics.
   - Tests: golden run lists every stage; legacy run shows a clear "no trace stored" message, not the run-analysis prompt; AppTest asserts the old text is gone when results exist.
2. **Hide "Off" cards**, keep one-line note. Test: references off, no Off cards; references on, 3 real numbers.
3. **Run header** replaces the "Showing saved run" strip. Test: shows name, date, papers, models, duration, status chips; legacy run omits missing fields gracefully.
4. **Collapse "New analysis"** when a run is loaded (expander, open only when there is no run). Playwright: at 1440x800 the first tab heading is visible without scrolling.
5. **Slim hero**: shown only for an empty project; fix the copy. Test: hero absent when the project has runs, present when empty.
6. **Re-run with this project's papers**: list stored papers with checkboxes; button enabled at 2+ selected; no upload needed. Tests: `project_store.list_papers`; AppTest with patched pipeline; Playwright flow ending at a saved run.
7. **Semantic Scholar key status** in the keys line. Test with the variable set and unset.
8. **Replace `use_container_width`** with one helper. Test: a grep-style test that none remain.
- Accept: F1, F2, F4, F5, F8, F12 closed. Effort ~1.5 days. Risk: low.

### Step 2: Sidebar and new project (fixes F6, F7)
1. **Slim sidebar**: project switcher ("5 runs" label), compact run cards with status chips, "New analysis", Settings. Test: sidebar has at most 4 interactive controls plus the run list; run chips reflect Lab done and warnings.
2. **Settings page** (via `st.navigation`): API keys with "in use" status, models, advanced options, references. Test: keys never written to disk; env-var keys shown as "in use".
3. **New analysis dialog** (4 steps). Test: validation per step (needs 2-5 papers; keys present for chosen models); back and forward keep state; cancel changes nothing.
4. **New project**: name, domain, interest, optional papers, "use recommended models". After creation, open the New analysis dialog preset for that project; empty state shows three guided steps. Hide the local folder path unless running locally. Tests: creating a project stores domain and interest; the dialog opens preset; no absolute path on screen when `RESGAP_HIDE_PATHS=1`.
- Fallback if dialogs prove brittle for file upload: a dedicated "New analysis" page via `st.navigation`.
- Accept: F6, F7 closed. Effort ~2 days. Risk: medium (widget state rules; mitigated by AppTest coverage).

### Step 3: Run workspace views (fixes F3, F11)
1. **Overview tab** (default): papers, quoted-evidence %, gaps by status, proposals, Lab status, coverage table, top 3 gaps, top proposal, a warnings summary from the trace.
2. **Evidence tab**: filter by paper, type, has-page; quote, page, section; reverse links to the gaps and proposals that cite each item. Tests: filter logic (unit); the reverse index; AppTest render; Playwright filter flow.
3. **Wiki tab**: study-type chip, key facts with links to their quotes.
4. **Gaps tab**: sort and filter (rank, status, finder, paper), compact list with detail, paper chips, linked citations. Backend change: store a URL or DOI per found paper in the literature scout (with tests).
5. **Proposals tab**: collapsible sections, link to its gap and evidence, accept or star using the existing feedback table, side-by-side compare of two.
6. **Graph tab**: relations table with evidence text, filters by paper and entity type, a plain-language note on orphan signals.
7. **Lab tab**: sufficiency verdict first, parameter table per paper, clear skipped-simulation and council-error states.
8. **Report tab**: in-app preview, section checklist, "Save to project".
- Render only the active view (segmented control instead of rendering every tab) to keep large runs fast. Test: DOM-node and load-time budgets.
- Accept: every tab has sort/filter or a detail view; Evidence exists. Effort ~4-5 days. Risk: medium.

### Step 4: Live run experience (fixes F9)
- Stage checklist driven by the `progress` and `trace` callbacks, with elapsed time and an expected duration per stage.
- Backend: record `duration_s` per trace row (with tests); derive expected durations from past manifests, with defaults.
- Show sub-progress ("finders 3 of 5", "checking gap 4 of 8", "reviewing proposals").
- A stage running over twice its expected time shows a gentle notice (cannot cancel in Streamlit; say so plainly).
- On completion: toast, open Overview.
- Tests: viewmodel `stage_status` for pending, running, done, warning, over-time; AppTest with a patched pipeline that emits scripted callbacks; Playwright confirms the checklist updates and ends on Overview.
- Accept: no run shows only a spinner. Effort ~1.5 days. Risk: low.

### Step 5: Project and run management (fixes F10)
- **Run board** replaces the table: status chips, models, duration, tokens, Lab; rename, archive, delete, merge duplicate runs.
- Migration `0006_run_management.sql` (archived flag), rename and archive functions in `utils/database.py`.
- Compare view restyled (the comparison logic exists).
- Project settings: name, description, defaults, delete project.
- Tests: migration on a database with old rows; rename, archive, delete keep files consistent; the board hides archived runs by default; compare of a run with and without Lab.
- Accept: no hash IDs on screen; old runs still open. Effort ~2 days. Risk: medium (data migration, covered by the legacy fixture).

### Step 6: Design system and accessibility
- One token set (colour, spacing, type scale), one card component, consistent Material icons in tabs (supported by the pinned Streamlit version), consistent empty, loading and error components.
- Contrast at least 4.5:1, visible focus, labels on every control, readable at 390 px width.
- Microcopy pass on every screen.
- Tests: axe finds no critical violations on the five main screens at three widths; screenshots reviewed.
- Accept: the app looks like one product. Effort ~2-3 days. Risk: low.

### Step 7: Cloud readiness (fixes F13)
- Storage adapter for the database and project files (Supabase or S3), chosen with you; fall back to local disk.
- Secrets via Streamlit secrets; optional sign-in (`st.login`).
- Caching of `load_run`; shareable read-only run link if wanted.
- Tests: adapter contract tests run against a local fake; a redeploy-survival check; secrets never rendered.
- Effort ~3-5 days. Risk: medium-high, and depends on decisions below.

## 5. Effort and order

| Step | Effort | Ship alone? |
|---|---|---|
| 0 Foundations | ~1 day | yes |
| 1 Quick wins | ~1.5 days | yes |
| 2 Sidebar and new project | ~2 days | yes |
| 3 Workspace views | ~4-5 days | yes, by tab |
| 4 Live run | ~1.5 days | yes |
| 5 Run management | ~2 days | yes |
| 6 Design system | ~2-3 days | yes |
| 7 Cloud | ~3-5 days | after decisions |

About 3 to 4 weeks of focused work in total; steps 0 and 1 alone remove the most visible problems. Review checkpoints after steps 1, 3 and 6 with screenshots.

## 6. Risks and how they are handled

- **`app.py` is a ~3,000-line file.** Extract piece by piece into `ui/`, always with the suite green; never a big-bang rewrite.
- **Streamlit widget-state rules** (a widget key cannot be set after creation) caused bugs earlier. Every stateful flow gets an AppTest.
- **Stale modules**: the server must be restarted after non-app changes; the plan's checklist includes a restart before each manual review.
- **Playwright flakiness**: use stable labels and roles, never pixel positions; screenshots are reviewed by a person, not diffed automatically, at first.
- **Old runs**: the legacy fixture runs in every AppTest suite.

## 7. Decisions needed from you

1. Stay on Streamlit through Step 6 (recommended; Cloud-friendly), or plan a move to the archived React front end later?
2. For Cloud: which storage (Supabase, S3, or none for now)?
3. Do you need sign-in or sharing, or is this internal-only?
4. Is a dark theme wanted?
5. Who are the users (just you, your team, external)? That sets how much onboarding copy is worth keeping.


---

## Second pass: additional frontend findings (F14-F20)

| # | Finding | Where | Change |
|---|---|---|---|
| F14 | **No URL state.** Refreshing or sharing a link always returns to the latest run on the first tab; the back button does nothing useful. | Whole app | Keep project, run and tab in query parameters; deep links to a gap or an evidence item. |
| F15 | **No notice when a long run finishes.** A 6-10 minute run needs a signal if the user switched tabs. | Running | Update the browser tab title and show a toast on completion; optional sound off by default. |
| F16 | **No copy or permalink actions.** Users cannot copy a quote with its citation, or link to one gap. | Evidence, Gaps | "Copy quote with citation" and "Copy link" buttons. |
| F17 | **Unexplained jargon.** "Partial", "Orphan signals", "Communities", "Coverage 2/10", "Simulation skipped" are not defined on screen. | Many | Short inline definitions and a glossary popover. |
| F18 | **Destructive actions need confirmation and undo.** Delete run and delete project must confirm and name what is removed. | Project view | Confirm dialog listing the files and runs affected; archive before delete. |
| F19 | **A failed run cannot be resumed.** Cached stages make a retry cheap, but there is no button. | Running, run board | "Resume" on a failed run (reuses caches, retries from the failed stage). |
| F20 | **No search across a run.** | Workspace | Search box over gaps, evidence and proposals (stretch goal). |
