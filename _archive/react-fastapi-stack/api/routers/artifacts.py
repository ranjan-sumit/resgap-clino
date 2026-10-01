from fastapi import APIRouter

from apps.api.models.artifacts import ArtifactListResponse
from apps.api.services.artifacts_service import list_all_artifacts

router = APIRouter(tags=["artifacts"])


@router.get("/artifacts", response_model=ArtifactListResponse)
def get_artifacts() -> ArtifactListResponse:
    return list_all_artifacts()
