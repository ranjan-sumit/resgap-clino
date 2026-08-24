from fastapi import APIRouter

from apps.api.models.challenger import ChallengerView
from apps.api.services.challenger_service import get_project_challenger

router = APIRouter(tags=["challenger"])


@router.get("/projects/{project_id}/challenger", response_model=ChallengerView)
def project_challenger(project_id: str) -> ChallengerView:
    return get_project_challenger(project_id)
