---
name: 'Amendment — Phase 5 Slice 1 (App Shell + Landing + Dashboard + Runs + Compare + Lineage) deviations'
type: amendment
status: active
created: '2026-08-24'
amends: ['03-system-architecture.md', '02-ux-specification.md', '06-versioning-lineage-architecture.md', '09-epics-and-stories.md']
---

# Amendment — Phase 5 Slice 1 deviations

Recorded per this project's own convention of dating findings rather than silently rewriting prior artifacts. This slice built the first real Next.js + FastAPI frontend (`apps/web`, `apps/api`) alongside the existing Streamlit app, covering App Shell, Landing, Project Dashboard, Runs (list, detail, Compare, Lineage). Full build detail: the plan file used to drive this slice (`playful-snuggling-umbrella.md` in the working session) and the `apps/api`/`apps/web` source itself, which documents each decision inline at its point of use.

## 1. `packages/research-engine/` was not created

`03-system-architecture.md`'s repository-structure section names `packages/research-engine/` as the intended home for the pipeline/utils code that `apps/api` wraps. That directory is **not created** — `apps/api` imports `pipeline`/`utils` directly from the repo root, and is launched with `python -m uvicorn apps.api.main:app --reload --port 8000` from the repo root so its imports resolve exactly like `app.py`/`tests/`/`evals/` already do.

**Why:** moving 34+ files to satisfy an aspirational path is pure risk (import breakage across the existing Streamlit app, tests, and eval scripts) for zero behavior change. AD-1's actual binding constraint — `apps/api` depends on the engine code, never the reverse — is preserved exactly; only the physical path differs from what the architecture doc pictured.

**Status:** deliberate, not a placeholder. Revisit only if/when a second consumer of `pipeline`/`utils` outside `apps/api` and `app.py` emerges and package boundaries start to matter for real (e.g. a separate deployable worker).

## 2. No auth UI this slice

Landing page CTAs go straight into the workspace shell — no login screen, no session concept anywhere in `apps/web`.

**Why:** `IdentityProvider` (AD-2) is explicitly Phase-6-gated on "a real second user" — no such trigger exists yet. Building a login screen now would be speculative UI with no real backend behind it. The TopBar's profile menu says so directly ("Local workspace — authentication arrives in Phase 6") rather than pretending to be a real account switcher.

## 3. Run status is derived, not a persisted column

`runs` has no `status` column in Postgres. `apps/api/services/run_status.py::derive_run_status()` reconstructs a `StatusChip` at read time from `results.gate_blocked`, `manifest.warnings`, and `quality_gate_results`, in a fixed priority order. It never invents a RUNNING/QUEUED state — nothing in this read-only API layer can observe a run mid-flight, so no such state is offered.

**Why:** this is a factual discovery about the existing schema (`06-versioning-lineage-architecture.md` never specified a `runs.status` column), not a choice this slice made. Deriving it is the correct fix, not a workaround to flag for later removal.

## 4. Three manifest version fields are honestly "Not recorded"

`input_corpus_version`, `pipeline_version`, and `prompt_bundle_version` are structurally never written by `app.py`'s manifest-recording call (confirmed by reading `app.py`'s manifest-write block directly, not assumed from the schema doc). The API surfaces each as `VersionField(recorded=False, note="<specific reason>")` — e.g. "No pipeline version constant is recorded by app.py's manifest write" — rather than a bare dash or a fabricated value.

**Why:** matches this project's standing honest-data discipline (never claim `recorded=True` with no real value behind it). This is a pre-existing gap in what `app.py` records, not something Phase 5 introduced or is expected to fix — flagged here so it isn't mistaken for a Phase 5 bug later.

## 5. "Research Confidence" ships unmeasured, not invented

The Dashboard's 5th confidence tile (alongside corpus/graph/evidence/search-coverage) has no real value — no composite research-confidence score is computed anywhere in this codebase. It renders `recorded=False` with a basis explaining that it will become real "when an aggregate scoring rule is defined (07-evaluation-architecture.md)."

**Why:** inventing an average-of-the-other-four score would be a fabricated number presented as a finding — exactly what this project's honest-data discipline forbids. The tile is a placeholder for a real future decision, not a stand-in metric.

## 6. Tailwind pinned at v3.4, not v4

`apps/web` uses Tailwind CSS v3.4 (`tailwind.config.ts`), not the current v4.

**Why:** v4 is CSS-first (`@theme` in a stylesheet) and cannot cleanly import `packages/branding/theme.json` at build time the way v3's JS/TS config can. Keeping the palette single-sourced from `theme.json` (AD-3/NFR-1, "never a hex literal duplicated outside branding config") mattered more than being on the latest major version. Revisit if/when Tailwind v4 gains a first-class JSON-import story for theme tokens.

## 7. Responsive/mobile is out of scope

`apps/web/app/globals.css` sets `body { min-width: 1280px; }` — no responsive breakpoints, no mobile layout anywhere in this slice.

**Why:** `02-ux-specification.md` §7 states this explicitly as out of scope for a "premium, clean, clinical" desktop research tool, not a dev-tool-style responsive dashboard. This slice simply follows that existing decision; it is not a new deviation Phase 5 introduced.

## Also worth recording (not in the plan's original 7, found during the build)

- **`POST /api/runs/{id}/promote` (the plan's optional Step 13) was not built.** Every real run in the registry today has `evaluation_metrics = NULL` in its manifest, so there is no real run to exercise a promotion write path against. Building it now would be an unexercisable write endpoint with no real test data — deferred until at least one run has gone through `evals/regression/run_champion_challenger.py`. The Compare page's "Promote candidate" button is present but permanently disabled with this reason visible as body text, not hidden.
- **`build_run_summary()` (Runs list) uses an N+1 read pattern** — one `load_run()` + `get_run_manifest()` call per row from `list_runs()`. Acceptable at the real current run count (single digits); `utils/database.py` could gain an additive `list_runs_with_manifests()` LEFT JOIN if/when this matters at scale. Not built this pass — no real performance problem exists yet to justify it.
- **A live end-to-end pipeline run (fresh papers → a run with a genuine `run_manifests` row and full Technical Lineage spine) was attempted via Playwright during this slice's build and did not complete within a 900-second timeout.** All frontend verification against "a run with a manifest" instead uses `b18ae1c95838`, a run manually backfilled with one `pipeline` artifact during earlier Phase 4 work — real registry data, but not a full multi-stage lineage spine. Revisit if a richer Lineage-view visual pass is needed later; not a blocker for this slice, since every honest-empty-state path (no manifest, no lineage nodes, no gap identity) is itself real, verified behavior on the other 4 runs.
