"""
FastAPI app factory (Clinova Phase 5, Epic 5.1).

Must be launched from the repo root:
    python -m uvicorn apps.api.main:app --reload --port 8000
so that `import pipeline...` / `from utils... import ...` resolve
exactly as they already do for app.py/tests/evals -- uvicorn inserts the
CWD at sys.path[0], no sys.path hacking needed.
"""
import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api import settings
from apps.api.errors import DatabaseUnavailableError, NotFoundError
from apps.api.routers import compare, config, health, lineage, projects, runs


def create_app() -> FastAPI:
    app = FastAPI(
        title="Clinova API",
        description="Thin FastAPI wrapper over the existing pipeline/utils modules -- "
                     "reads/writes the same Postgres data as the Streamlit app.",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.exception_handler(NotFoundError)
    async def _not_found(_request: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": exc.detail})

    @app.exception_handler(DatabaseUnavailableError)
    async def _db_unavailable(_request: Request, exc: DatabaseUnavailableError):
        return JSONResponse(status_code=503, content={"detail": exc.detail})

    @app.exception_handler(psycopg.OperationalError)
    async def _psycopg_unavailable(_request: Request, exc: psycopg.OperationalError):
        return JSONResponse(status_code=503, content={
            "detail": f"Cannot reach PostgreSQL. Start it with pg_ctl before using the API. ({exc})",
        })

    @app.exception_handler(ValueError)
    async def _value_error(_request: Request, exc: ValueError):
        # pipeline/run_compare.py::compare_runs() and
        # pipeline/lineage.py::get_scientific_lineage() both raise a
        # real, already-human-readable ValueError on an unknown run_id
        # ("Run 'X' was not found -- cannot compare.") -- surfaced as-is,
        # not wrapped into a generic 500.
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    app.include_router(health.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(config.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.include_router(compare.router, prefix="/api")
    app.include_router(lineage.router, prefix="/api")

    return app


app = create_app()
