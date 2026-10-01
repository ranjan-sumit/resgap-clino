"""
FastAPI thin wrapper (Clinova Phase 5, Epic 5.1) over the existing
`pipeline`/`utils` modules -- a new interface onto the same real Postgres
data Streamlit already reads/writes, not a reimplementation.

Must be launched from the repo root so `pipeline`/`utils` resolve exactly
as they do for app.py/tests/evals today:

    python -m uvicorn apps.api.main:app --reload --port 8000
"""
