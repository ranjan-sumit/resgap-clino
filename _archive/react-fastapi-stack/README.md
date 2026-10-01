# Archived: Next.js + FastAPI stack

This directory holds the Phase 5 Next.js/FastAPI frontend and API, archived
(not deleted) on 2026-10-01 on branch `refactor/streamlit-simplification-oct1`.

## Why

The stakeholder evaluated both UIs side by side and preferred Streamlit
(see commit `3d44a10`, "Phase 5 - Slice 15: re-converge the workspace after
comparing against Streamlit" — their own words: *"streamlit was more cleaner
not liking this react not user friendly"*). FastAPI (`apps/api`) had no
consumer other than this web app — no external integrations, no auth
boundary, no scheduled jobs, nothing that survives `web`'s removal. Going
forward, Streamlit (`app.py`) is the only supported UI, calling `pipeline/`
and `utils/` directly, as it always has.

## What's here

- `web/` — the Next.js app (was `apps/web`)
- `api/` — the FastAPI app (was `apps/api`)
- `branding/` — shared copy/text used only by the web app (was `packages/branding`)
- `contracts-typescript/` — TS API types for the web app (was `packages/contracts/typescript`)
- `tests-api/` — the 9 `test_api_*.py` files that exercised `apps/api` (was `tests/`)
- `playwright-ui/` — manual Playwright verification scripts for the React UI (was `evals/benchmarks/ui/`)
- `Dockerfile.web` — the web app's container build

## How to restore

Nothing was deleted from git history. To bring this stack back:

```
git checkout pre-simplification-baseline-2026-10-01 -- apps/ packages/branding packages/contracts/typescript Dockerfile.web
```

(or `git revert` the specific archival commit on this branch), then restore
the `api`/`web` services in `docker-compose.yml`/`docker-compose.compat.yml`
from the same tag.

## What did NOT move

`pipeline/`, `utils/`, `packages/contracts/llm_provider.py` and
`search_provider.py`, `packages/research_schemas/` — all genuinely shared,
Streamlit-free domain/infrastructure code, untouched by this archival.
