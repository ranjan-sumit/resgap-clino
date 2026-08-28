from fastapi import APIRouter

from apps.api.models.quality import QualityView
from apps.api.services.quality_service import get_project_quality

router = APIRouter(tags=["quality"])


@router.get("/projects/{project_id}/quality", response_model=QualityView)
def project_quality(project_id: str) -> QualityView:
    return get_project_quality(project_id)
