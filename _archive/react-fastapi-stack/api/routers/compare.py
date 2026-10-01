from fastapi import APIRouter, Query

from apps.api.models.compare import RunComparison
from apps.api.services.compare_service import get_run_comparison

router = APIRouter(tags=["compare"])


@router.get("/compare", response_model=RunComparison)
def compare(baseline: str = Query(...), candidate: str = Query(...)) -> RunComparison:
    return get_run_comparison(baseline, candidate)
