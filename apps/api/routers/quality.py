from fastapi import APIRouter

from apps.api.models.quality import QualityView
from apps.api.services.quality_service import get_project_quality

router = APIRouter(tags=["quality"])


@router.get("/projects/{project_id}/quality", response_model=QualityView)
def project_quality(project_id: str, run_id: str | None = None) -> QualityView:
    """Optional run_id pins every workspace tab to the same run. Omitted = the most recent run, which is what every screen did before the workspace gained a run switcher (Slice 15)."""
    return get_project_quality(project_id, run_id)
