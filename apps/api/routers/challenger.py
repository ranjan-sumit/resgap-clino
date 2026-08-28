from fastapi import APIRouter

from apps.api.models.challenger import ChallengerView
from apps.api.services.challenger_service import get_project_challenger

router = APIRouter(tags=["challenger"])


@router.get("/projects/{project_id}/challenger", response_model=ChallengerView)
def project_challenger(project_id: str, run_id: str | None = None) -> ChallengerView:
    """Optional run_id pins every workspace tab to the same run. Omitted = the most recent run, which is what every screen did before the workspace gained a run switcher (Slice 15)."""
    return get_project_challenger(project_id, run_id)
