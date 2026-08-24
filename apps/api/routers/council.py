from fastapi import APIRouter

from apps.api.models.council import ResearchCouncilView
from apps.api.services.council_service import get_project_council

router = APIRouter(tags=["council"])


@router.get("/projects/{project_id}/council", response_model=ResearchCouncilView)
def project_council(project_id: str) -> ResearchCouncilView:
    return get_project_council(project_id)
