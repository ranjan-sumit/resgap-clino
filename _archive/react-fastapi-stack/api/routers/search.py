from fastapi import APIRouter, Query

from apps.api.models.search import SearchResponse
from apps.api.services.search_service import MAX_HITS, search_project

router = APIRouter(tags=["search"])


@router.get("/projects/{project_id}/search", response_model=SearchResponse)
def project_search(project_id: str, q: str = Query(""), limit: int = Query(MAX_HITS)) -> SearchResponse:
    return search_project(project_id, q, limit=limit)
