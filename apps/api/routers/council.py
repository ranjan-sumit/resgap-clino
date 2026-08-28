from fastapi import APIRouter

from apps.api.models.council import ResearchCouncilView
from apps.api.services.council_service import get_project_council

router = APIRouter(tags=["council"])


@router.get("/projects/{project_id}/council", response_model=ResearchCouncilView)
def project_council(project_id: str, run_id: str | None = None) -> ResearchCouncilView:
    """Optional run_id pins every workspace tab to the same run. Omitted = the
    most recent run that has Computational Lab output, which is not
    necessarily the most recent run overall."""
    return get_project_council(project_id, run_id)
