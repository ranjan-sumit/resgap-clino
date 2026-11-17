# UI PR plan: from "works" to "looks and feels like one enterprise product"

Status: UI-00 (audit), UI-01 and UI-02 are done in the working tree (not committed). Everything else is a plan.
Continues `docs/frontend-proposal.md` (F1-F20) and refines PR-20 ("Design system and accessibility") in
`docs/fix-sequence-and-regression-plan.md`. Same rules as that plan: one PR per section, tests first, a PR never
exceeds its stated scope, every PR lists Closes, Depends on, Changes, New tests, Regression, Acceptance, Rollback.

## 1. How this was found

A screen-by-screen review of the running app (1440 px laptop window, plus 390 px phone for the home screen) covering
home, Overview, Gaps, Proposals, Evidence, References, Wiki, Graph, Lab, Trace, Export, New project, the four-step
New analysis wizard and every Settings tab; then a read of the code that draws them; then timings in a real browser.

### Measurements (this machine, warm server)
| What | Result |
|---|---|
| Server time for one rerun (AppTest, in process) | Overview 1.6 s, Gaps 2.0 s, Graph 3.7 s |
| Cold start (imports) | about 25 s |
| Click to content in a browser | first visit after a server start: Gaps 3.6 s, Evidence 6.7 s, Wiki 8.6 s; switching between sections already visited: about 1 s (see F56). The group switches that took 5.8 and 7.4 s ran the script twice before UI-01. |
| Space before the headline numbers (1000 px window) | about 680 px: 190 px padding, banner, header, toggle, run bar, Feedback row, group tabs, note, pills |

### How the UI code is built (the root causes behind most findings)
- `app.py` is 3,514 lines. 151 `style=` / `unsafe_allow_html` sites in `app.py`, 13 in `ui/components.py`.
- CSS lives in three places: `ui/theme.py` (476 lines, two generations stacked: the DM Sans / DM Mono / DM Serif
  rules in lines 1-273 and the Inter rules from line 299, fought over with `!important`), a large `<style>` block
  inside `app.py`, and inline styles. Four font families are self-hosted (`static/fonts`), three of them mixed on screen.
- `tests/test_html_escaping.py` needs a reviewed allowlist for HTML built inside `app.py`; it grew by about 20 entries
  this month. Ad hoc HTML in `app.py` is the reason.
- There are 19 `st.rerun()` calls in `app.py` (21 before UI-01 removed two); each one is a second full run of the script.
- Functional coverage is good (AppTest, golden and legacy runs, axe, three Playwright suites). Visual coverage is
  none: nothing fails when a screen gets uglier, a button turns the wrong colour, or copy regresses.

## 2. Findings (continuing the F-numbers)

| # | Finding | Where | PR |
|---|---|---|---|
| F21 | Hovering the primary sidebar button wipes its fill (a rule for all sidebar buttons set a pale background, text stayed white): the button looks empty. | Sidebar | UI-01 |
| F22 | The relations table's Page column mixes numbers and a dash, so Arrow conversion fails and Streamlit logs a traceback on every rerun of the Graph tab. | Graph | UI-01 |
| F23 | The wizard's step indicator is markdown text; on step 3 it starts with "1." and renders as a list. | Wizard | UI-01 |
| F24 | Paper chips on gap cards are cut mid-word ("Modeling pulmonary cystic fi"). | Gaps | UI-01 |
| F25 | Trace shows raw role keys (council_chair), glues a row number to a stage's own name ("STAGE 1 - Stage 1 - PDF Parse"), and the Wiki shows tier codes ("T1 Uploaded PDF"). | Trace, Wiki | UI-01 |
| F26 | Switching the Results / Evidence / Audit group ran the script twice. | Results | UI-01 |
| F27 | Every main-area button is the same solid blue: Back, Cancel, Clear (destructive), Download, Create backup. No screen has a clear primary action. | Everywhere | UI-02 |
| F28 | Three field styles: white inputs, blue text areas, blue number boxes. | Forms | UI-02 |
| F29 | Page titles at Streamlit's 2.5 rem and 190 px of empty padding above every screen. | Everywhere | UI-02 |
| F30 | About 680 px of stacked chrome before content (see measurements). | Results | UI-03 |
| F31 | The project name and counts are repeated above Settings, New project and the wizard, where they are irrelevant or misleading (New project still says "Cystic Fibrosis Review"). | Pages | UI-03 |
| F32 | Four font families, two CSS generations, three style locations. | Code | UI-04 |
| F33 | Emoji in headings (Computational Lab, Pipeline Trace), em dashes in titles and copy, Title Case next to sentence case, jargon (T1, council seat, stage numbers). | Copy | UI-05 |
| F34 | Trace is a stack of cards in monospace plus a run-on paragraph of token counts; Lab uses a grey-brown box and a red alarm card; Wiki and References use the old card style. | Audit group, Wiki, References | UI-06 |
| F35 | Proposals are collapsed one-line rows with lowercase "accept"; Gaps use a serif title and monospace chips. | Proposals, Gaps | UI-07 |
| F36 | Export: nine dark-blue chips for sections, three download buttons detached from their cards. | Export | UI-08 |
| F37 | Settings: eight identical key fields with status at the bottom, six blue Clear buttons, the full database path on screen. | Settings | UI-09 |
| F38 | Wizard review: plain paragraphs, cost as a small caption, the planner collapsed, an unformatted token cap (2000000). | Wizard | UI-10 |
| F39 | Phone: five headline tiles stack to 600 px; wide planner cards stack three high. | Phone, tablet | UI-11 |
| F40 | Slow feel: blank skeletons for seconds, no progress text, 19 `st.rerun()` calls, heavy view-models recomputed on every rerun, all runs loaded for the run header. | Everywhere | UI-12 |
| F41 | No screenshot baselines, no "one primary button per screen" rule, no copy lint. | Tests | UI-14 |
| F42 | Not yet reviewed: the live run screen, the Project view (run board), the Compare view, the Audit log tab, Analysis defaults, the lower half of Lab results. | Several | UI-00 (done: F43-F54) |
| F43 | **Not a UI defect, found by the audit: test runs write to the real audit log.** `test_run_pipeline_extraction`, `test_run_pipeline_gap_detection_failure` and `test_challenger_stage` call the pipeline without redirecting the database, and the pipeline records `run.started` / `run.finished` / `run.failed`. All 16 entries in the real, tamper-evident audit log (which the app says "cannot be edited or removed") are test events (`run-id-123`, model `test-model`), written during test runs on 30 Oct. The run history itself is untouched (5 runs). | `tests/conftest.py`, Settings > Audit log | TEST-01 |
| F44 | **Live run:** the full first-visit hero (about 400 px) is shown above the progress list for a project with no runs, so progress starts about 570 px down. Stage messages are raw ("Stage 1 - Parsing PDFs..."). The checklist is an unstyled list mixing native checkboxes, emoji (check mark, hourglass) and grey dashes; steps that will not run (references off) look like steps still to come until the end. | Running | UI-03, UI-17 |
| F45 | **Project view:** the project name appears three times (header, then again as a heading) and the full local folder path is shown in monospace blue; the banner still sits on top; actions for a selected run appear below the table and the duplicate-runs expander, away from the selection; the four download buttons sit at column starts with uneven gaps; the Status column shows "No manifest" with no explanation. | Project | UI-17 |
| F46 | **Compare:** the model line is a raw dump (`extraction=gemini:gemini-3.5-flash-lite; wiki=...; fallback=... -> ...`, five lines of monospace); durations in raw seconds (857.0s -> 389.0s); metrics are stacked bold paragraphs, not a table; new and removed gaps use tiny icons with no colour meaning; the lists touch the next expander. | Compare | UI-17 |
| F47 | **Audit log:** the Details column shows raw JSON cut off at the table edge; targets and ids are raw (`run run-id-123`); the green "Intact" message fails the contrast check (axe, serious). | Settings | UI-09 |
| F48 | **Analysis defaults** overlap the planner: a tier switches the same options on or off (deep validation, quality check, references) and the tab does not say so. The disabled "References per paper" label fails contrast (axe, serious), in Settings and again in the wizard's options step (found by UI-14). | Settings, wizard | UI-09 |
| F49 | **Lab, lower half:** an emoji chart icon on every parameter group ("Rate (2 total: 2 T1 + 0 T2)"), T1 / T2 jargon, "Stage 8 - Extracted Parameters" headings, hypothesis cards with heavy green / amber / red left borders and monospace chips ("High Conf") that fail contrast (axe, serious, 5 nodes). | Lab | UI-06 |
| F50 | **Planner:** the "off" items on the tier cards (grey on white) failed contrast (axe, serious, 4 nodes). Introduced with the planner; fixed during UI-00 (colour `#5f7389`, 4.9:1) and added to the contrast list in `ui/tokens.py`. | Settings > Models | done |
| F51 | **Phone (390 px):** the planner's purpose control clips its last label ("Publication or decisio"); the 190 px gap above the banner remains; the review step, tables and headers fit. No screen scrolls sideways at 390 or 768 px (checked 10 screens at each width). | Phone | UI-11 |
| F52 | **Accessibility baseline (axe, 1440 px, 20 screens):** no serious or critical finding of ours except the contrast items in F47-F50; the two framework rules the repo already ignores (`aria-allowed-attr`, `region`) appear on every screen. | All | UI-14 |
| F53 | The wizard's review step lists only three of the jobs ("Models: Extraction, Wiki, Analysis"), not review, council or fallback. | Wizard | UI-10 |
| F54 | Empty values are shown as a long dash ("Research interest: -"). | Wizard | UI-05 |
| F55 | **Regression from UI-01, found while building UI-14:** removing `st.rerun()` from the group and section controls made their widget keys change with every click, so the browser's next click went to a widget the new run no longer drew and was dropped. The last pill of a row (Proposals, Wiki, Export) looked dead. No server or browser error; the repo's accessibility test never noticed because it does not check which screen it lands on. Fixed with stable keys and an explicit click-versus-jump check (`ui/navigation.py`), still one script run per click. | Results | done (UI-14) |
| F57 | **Found by looking at the first screenshot baselines (1024 px window):** the slim banner's pills squeezed its title to one syllable per line (fixed: pills hide under 1100 px); the headline tile label "COMMUNITIES" breaks mid-word; the planner's purpose and provider controls are clipped. The last two are frozen into the approved baselines until UI-11 fixes them and re-approves the pictures. | Tablet | UI-11 (banner: done) |
| F56 | Timings, corrected: the first visit to a section after a server start costs 7 to 9 s (Evidence 6.7 s, Wiki 8.6 s: cold code); switching between sections already visited takes about 1 s. The 3 to 7 s figures measured earlier mixed the two. | Results | UI-12 |

## 3. Sequence

| PR | Title | Closes | Depends on | Size | Risk |
|---|---|---|---|---|---|
| UI-00 | Audit of the screens not yet reviewed (no code) | F42 -> F43-F54 | none | S | none (done) |
| UI-01 | Defects | F21-F26 | none | S | low (done) |
| UI-02 | One button system, one field style, heading scale, top padding | F27-F29 | UI-01 | S | low (done) |
| TEST-01 | Tests never touch the real database (autouse fixture); decide what to do with the 16 test entries already in the audit log | F43 | none | S | low |
| UI-14 | Visual and rule tests: screenshot baselines, one primary per screen, copy lint, axe on new components | F41 | UI-02 | M | low |
| UI-05 | Copy and tone pass | F33 | UI-14 | S | low |
| UI-03 | Header consolidation: first screen shows results | F30, F31 | UI-14 | M | medium |
| UI-04 | Theme consolidation: one font stack, one stylesheet | F32 | UI-14 | M | medium |
| UI-12 | Perceived performance: fewer reruns, cached view-models, progress text | F40 | UI-01 | M | medium |
| UI-06 | Audit group and reading screens on the shared components | F34 | UI-04 | M | low |
| UI-07 | Gaps and Proposals lists | F35 | UI-04 | S | low |
| UI-08 | Export | F36 | UI-02 | S | low |
| UI-09 | Settings screens | F37 | UI-02 | M | low |
| UI-10 | New analysis wizard | F38 | UI-03 | M | low |
| UI-11 | Responsive pass (390, 768, 1024) | F39 | UI-03 | M | low |
| UI-17 | Live run, Project view and Compare | F44, F45, F46 | UI-03, UI-04 | M | medium |
| UI-13 | Split `app.py` into `ui/screens/`; HTML builders into components | root cause | UI-04, UI-06..10, UI-17 | L | medium-high |
| UI-15 | URL state and deep links (F14, F16) | F14, F16 | UI-13 | M | medium |
| UI-16 | Dark theme (only if wanted) | decision 4 in the proposal | UI-04 | M | low |

Why this order: UI-14 comes right after the two done PRs so that every later PR is protected by a visual and rule test
net; copy and header first because they change what the first screen says and shows; theme consolidation before the
per-screen PRs so they build on one stylesheet; `app.py` split last because it is the largest change and is easier once
every screen already uses shared components.

## 4. PR descriptions

### UI-01 Defects (implemented)
- **Closes:** F21, F22, F23, F24, F25, F26.
- **Changes:** sidebar hover rule excludes the primary button; `relation_table_rows` (all cells text, "n/a" for a missing page);
  `stepper_html` for the wizard; `shorten` (word boundary, full text in the chip's title); Trace shows "Models used" with
  role labels and "1. PDF Parse" instead of "STAGE 1 - Stage 1 - PDF Parse"; Wiki expander says "Uploaded paper"; group
  and section switches no longer call `st.rerun()` (the first version of this broke clicks on the last pill of a row; see F55 and
  `ui/navigation.py`, which replaced it).
- **New tests:** `tests/test_ui_polish.py` (7): `shorten` at word boundaries, stepper states and escaping, the wizard shows the
  stepper on every step, relation cells are text and convert to Arrow, the sidebar hover rule names no bare selector.
  `test_frontend_quick_wins.py` updated for the new trace labels.
- **Regression run:** `test_ui_polish`, `test_html_escaping`, `test_frontend_quick_wins`, `test_design_system`, `test_settings_and_wizard`,
  `test_app_smoke`, `test_overview_evidence_wiki`, `test_graph_screen`, `test_gaps_proposals_screens`, `test_golden_run_renders`,
  `test_lab_screen`, `test_report_export`, `test_run_planner`.
- **Acceptance:** no Arrow traceback in the server log on the Graph tab; "New analysis" readable under the mouse; no raw role keys on Trace.
- **Rollback:** revert the commit; no data or schema change.

### UI-02 One button system, one field style, headings, top padding (implemented)
- **Closes:** F27, F28, F29.
- **Changes (`ui/theme.py`, one marked block):** secondary buttons outlined, primary solid, disabled flat; Clear and Delete outlined in
  red (keys `clear_*`, `delete_*`, `empty_deleted`); text, text-area and number fields share one white field and border; h1-h4 scale
  1.9 / 1.55 / 1.2 / 1.02 rem; main container top padding 2.5 rem. Download buttons follow the same rule.
- **New tests:** covered by UI-14 (rule tests). Checked in the browser for the wizard, New project and Saved results.
- **Acceptance:** at most one solid button per form step; destructive buttons are visibly different.
- **Rollback:** delete the marked block.

### UI-00 Audit of the unreviewed screens (done)
- **Method:** the repo's own browser harness (`tests/ui/a11y.py`: vendored axe, the "settled" wait) against the running app at 1440 px for
  Overview, Gaps, Proposals, Evidence, References, Graph, Wiki, Lab, Trace, Export, the Project view (no run, one run, two runs selected),
  all six Settings tabs; the live-run screen using `tests/ui/fake_runner_app.py` on a throwaway database; sideways-scroll checks at 390 and
  768 px for ten screens. Screenshots and the axe output are kept with the working notes, not in the repo.
- **Result:** findings F43-F54 above. The audit changed the plan in four ways: a new PR (UI-17) for the live run, Project view and Compare;
  F47-F49 moved into UI-09 and UI-06; F44 added to UI-03 (hide the hero while a run is going); and one non-UI defect (F43) got its own small PR.
- **Fixed during the audit:** F50 (planner contrast), because it was a regression from this month's planner work.

### TEST-01 Tests never touch the real database
- **Closes:** F43.
- **Changes:** an autouse fixture in `tests/conftest.py` that points `RESGAP_DB_PATH` and `RESGAP_PROJECTS_DIR` at a temporary folder for every
  test (and clears `db._INITIALIZED`), so a test that forgets `isolated_env` cannot write to `data/`. Decide separately what to do about the 16 test
  entries already in the audit log: the log cannot be edited from the app, so options are to leave them (the chain stays valid and the entries are
  obviously test data), or to reset the table once with a documented script and record that reset as the first real entry.
- **New tests:** a test that, with the guard on, a pipeline run leaves the real database's audit count unchanged.
- **Regression:** the three offending files, the audit-log tests, a sample of AppTest suites.
- **Acceptance:** the count of audit entries in `data/run_history.db` does not change when the suite runs.
- **Rollback:** delete the fixture.

### UI-14 Visual and rule tests (implemented)
- **Design choice:** a rule that today's UI already breaks is a **ratchet**. The known violations are written down, a new one fails, and a fixed
  one fails until it is removed from the list, so the later PRs can only shrink the lists.
- **Changes (all tests, no app code):**
  - `tests/ui_rules.py` and `tests/test_ui_rules.py` (default suite, marker `ui`): AppTest renders 16 screens against a synthetic project
    (empty home, the 10 result sections, Settings, New project, wizard steps 1 to 4) and checks three rules on what is visible:
    (1) at most one solid button per screen in the main area (a form's own Save button is not counted); (2) no long dash anywhere, and no emoji in a
    heading or a label (status marks such as a check mark are allowed; data tables are skipped); (3) a warm rerun of each section within a budget
    (6 s today, `UI_RENDER_BUDGET_S` to change; UI-12 tightens it). Today's 20 copy violations are in `tests/data/ui_rules_baseline.json`;
    no screen has more than one solid button.
  - `tests/ui/visual.py`, `tests/test_visual_compare.py` (default suite) and `tests/ui/test_visual_baselines_e2e.py` (marker `e2e`): nine result
    sections plus Settings > Models at 1440x800, 1024x768 and 390x844 against approved screenshots in `tests/ui/_baselines/<platform>/`. Dates and
    run ids are hidden (not removed) so the layout around them is still checked; a platform without baselines skips; `UPDATE_BASELINES=1` writes them.
    A change fails when more than 0.5% of pixels move, and the picture, the baseline and the changed pixels are saved side by side.
  - `tests/ui/test_accessibility_screens_e2e.py` (marker `e2e`): axe on all six Settings tabs and all four wizard steps at desktop and phone width,
    as a ratchet (`KNOWN`: F47 and F48, the two contrast failures UI-09 will fix).
  - `tests/test_navigation.py` (default suite, 7 tests): the click-versus-jump logic with a simulated browser, and a click-through of the real app
    (pills, groups and a button jump, each checked to take effect); this is the test that would have caught F55.
- **Each rule has a test that a deliberate violation fails:** a long dash, an emoji heading, two solid buttons, a recoloured block and a size change
  are each checked to fail, and the allowed cases (status marks, form submit buttons, one-level colour noise) to pass.
- **Not covered, on purpose:** the Graph tab's charts are in the baselines but not scanned separately (UI-14's axe reaches them through the main
  accessibility test); the live-run screen and Compare need fixtures that do not exist yet (UI-17).
- **Acceptance:** a PR that adds an emoji heading, a second solid button, a slow section, or moves a key screen turns CI red.
- **Rollback:** tests only.

### UI-05 Copy and tone
- **Changes:** sentence-case headings; remove emoji from headings and labels (keep status marks that carry meaning, as text); no em dashes in
  UI strings; plain names for T1/T2/T3, council seats and stage numbers; one wording for each concept across screens (Evidence, Gaps).
- **New tests:** the UI-14 copy lint; existing tests updated for renamed headings.
- **Acceptance:** lint green; a read-through of every screen shows no jargon without a definition.
- **Implemented:** `ui/copy.py` cleans stored text at display time (saved runs keep their emoji statuses and long dashes and still open
  unchanged); trace rows and warnings show `✓ ! ✗` marks and plain stage names; headings are sentence case; empty cells read "n/a"; the tier
  badge shows the plain label (no "T1"). The UI-14 copy baseline is now empty, so any new emoji or long dash fails the lint.
  Visual baselines are re-approved after the diff review.

### UI-03 Header consolidation
- **Changes:** project title and the Analysis / Project toggle on one row; the run bar gains a Feedback button (popover) replacing the full-width
  expander; the banner collapses to nothing once a project has a run (the hero stays for an empty project); the project header is hidden on
  Settings, New project and the wizard (each shows its own title); the group note moves beside the group control.
- **New tests:** at 1440x800 the headline numbers are fully visible without scrolling and start above 480 px; feedback saved from the run bar
  is stored as before; the project header is absent on Settings.
- **Acceptance:** first screen shows results; F30 and F31 closed.
- **Rollback:** revert; widget keys for feedback unchanged.

### UI-04 Theme consolidation
- **Changes:** delete the superseded DM-era rules; one font stack (Inter for text, one monospace for ids and code only); move the `<style>`
  block from `app.py` into `ui/theme.py` in sections (tokens, base, components, screens); remove unused font files and their licence entries;
  extend `REQUIRED_PAIRS` with every colour pair the new components use.
- **New tests:** contrast for the new pairs; a test that no rule uses a font family that is not shipped; UI-14 baselines unchanged except
  where a change is intended.
- **Acceptance:** one stylesheet, one source of tokens, fewer bytes on first load.
- **Rollback:** revert; the old file is in git.

### UI-12 Perceived performance
- **Changes:** replace `st.rerun()` where state can be updated in the same run (19 call sites; keep the ones that change widget state
  after creation); cache pure view-models per run (`st.cache_data` keyed by run id and a content hash); load one run's metadata for the header,
  not all runs; show a short progress line while a heavy section builds; Plotly `displayModeBar` off and a lighter graph for large runs.
- **New tests:** a render budget on the golden run per section; a test that switching group makes one script run.
- **Acceptance:** warm click-to-content under 2 s for Gaps, Evidence, Proposals; Graph under 3 s.

### UI-06 Audit group and reading screens
- **Also (from UI-00):** the lower half of Lab: no emoji on parameter groups, "Tier 1 / Tier 2" in words, hypothesis cards without the heavy
  coloured borders, confidence as a text chip that passes contrast.
- **Changes:** Trace as a table (Stage, Input, Output, Tokens, Status) with a token summary line; Lab: verdict card first, neutral cards,
  one outlined action, no emoji; Wiki and References use the Communities card and the shared table.
- **New tests:** trace table lists every stage of the golden and legacy runs; no raw role key; Lab renders for a run without simulation.

### UI-07 Gaps and Proposals
- **Changes:** one gap card (Inter title, rank badge, status chip, source and score, chips with ellipsis); Proposals as cards with rank, status
  chip and a two-line summary; clearer compare control ("Pick two proposals to compare").
- **New tests:** card content for golden and legacy runs; compare of two proposals; feedback unchanged.

### UI-08 Export
- **Changes:** sections as a checkbox grid; the three downloads inside their cards; "Generate final report" the only primary button; list of saved reports.
- **New tests:** the section checklist still drives the report; downloads present for every format.

### UI-09 Settings
- **Also (from UI-00):** the Audit log table shows readable details instead of raw JSON and readable targets; the success message passes contrast;
  "Analysis defaults" says that the planner's tier sets these options and shows which tier did; the disabled "References per paper" label passes contrast.
- **Changes:** API keys as one row per provider with a status badge ("in use from the environment", "typed this session", "not set") and the
  field behind an edit control; Saved results right-aligned with a confirm step; Backup with the restore command in a copy block; the database
  path shown only when running locally (`RESGAP_HIDE_PATHS` already exists).
- **New tests:** keys still never written to disk; clear still removes rows; path hidden when paths are hidden.

### UI-10 New analysis wizard
- **Changes:** review step as a summary card (papers, domain, models, options) with the cost range prominent and the planner open; options
  grouped into basic and advanced; formatted token cap; Back left, Next right, Cancel as a text link.
- **New tests:** review step shows the estimate; Next is the only primary button; state kept when going back.

### UI-11 Responsive pass
- **Also (from UI-00):** the planner's purpose control wraps or scrolls instead of clipping "Publication or decision" at 390 px.
- **Changes:** two-column headline tiles under 600 px; planner cards scroll horizontally or stack with a compact variant under 768 px;
  tables scroll inside their container; header fits one row at 390 px.
- **New tests:** Playwright at 390, 768 and 1024 for ten screens: no horizontal page scroll, key text visible.

### UI-17 Live run, Project view and Compare
- **Closes:** F44, F45, F46.
- **Changes:** while a run is going the first-visit hero is hidden and the progress list is the first thing on screen; the checklist as one
  component (done, running, waiting, skipped as text and icon, with the stage message under the running step in plain words); the Project view
  loses its repeated title and shows the folder path only when running locally; actions for the selected run sit directly above the table; the
  four downloads in one aligned row; "No manifest" explained on hover. Compare: a table (Metric, Older, Newer, Change) for papers, evidence,
  graph, gaps and proposals; models as two readable lines; durations as "14 min 17 s"; new gaps in green and removed gaps in grey with a count.
- **New tests:** hero absent while a job runs; the checklist marks a skipped step as skipped; compare shows no `provider:model` key dump and no
  raw seconds; one-run and two-run selection views render for the golden and legacy fixtures.
- **Acceptance:** at 1440x800 the running checklist is fully visible; Compare reads as a table.

### UI-13 Split `app.py`
- **Changes:** screens move to `ui/screens/<name>.py` one at a time (overview, graph, gaps, proposals, evidence, wiki, references, lab, trace,
  export, settings, wizard, project); ad hoc HTML moves into `ui/components.py` helpers that escape by construction; the reviewed allowlist in
  `test_html_escaping.py` shrinks to what is genuinely constant.
- **New tests:** the existing suite plus the baselines are the net; no behaviour change.
- **Acceptance:** `app.py` under 800 lines; the allowlist for `app.py` is empty.

### UI-15 URL state and deep links
- **Changes:** project, run and section in query parameters; a copy-link button on a gap and an evidence item.
- **New tests:** open a link, land on the section; a link to a deleted run shows a clear message.

### UI-16 Dark theme (optional)
- **Changes:** a second token set and `prefers-color-scheme`; every colour pair in `REQUIRED_PAIRS` repeated for dark.
- **Only if:** the pending decision in `frontend-proposal.md` section 7 says yes.

## 5. Decisions needed
1. Keep a serif for gap titles, or move everything to one sans family (recommended)?
2. Keep monospace for ids and chips, or limit it to code and ids (recommended)?
3. Emoji policy: none in headings (recommended), or keep status marks only?
4. Dark theme wanted (UI-16)?
5. Rename the Analysis / Project toggle? ("Results" and "Project files" say more.)

## 6. Not verified yet
- The Playwright suites in `tests/ui` were not run for UI-01 and UI-02; the AppTest suites listed under UI-01 were.
- UI-00 covered one project and one set of five saved runs; screens that only appear with other data (a failed run, a gate-blocked run, a
  run with no Lab, archived runs, feedback entries) were not reviewed and need seeded fixtures (UI-14).
- UI-02 was checked in the browser on the wizard, New project and Saved results, not yet on every screen or at phone width.
- The click-to-content timings are from one machine with one saved project; the budgets in UI-12 and UI-14 need a second reading on the target machine.
