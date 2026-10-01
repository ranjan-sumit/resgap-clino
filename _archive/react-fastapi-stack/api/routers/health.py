from fastapi import APIRouter
from pydantic import BaseModel

from apps.api.services.git_info import GIT_COMMIT
from utils.database import init_db

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    database: str
    git_commit: str | None


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Opens a real Postgres connection (via init_db(), the same
    idempotent liveness+migration check utils/database.py's own callers
    use) -- not a hardcoded {"status": "ok"}. A connection failure
    surfaces as a real 503 via main.py's psycopg.OperationalError
    handler, not a false-positive 200."""
    init_db()
    return HealthResponse(status="ok", database="ok", git_commit=GIT_COMMIT)
