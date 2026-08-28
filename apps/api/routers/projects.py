from fastapi import APIRouter

from apps.api.models.dashboard import ProjectDashboard, ProjectSummary, WorkspaceHeader
from apps.api.services.dashboard_service import (
    get_project_dashboard, get_workspace_header, list_projects,
)

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[ProjectSummary])
def get_projects() -> list[ProjectSummary]:
    return list_projects()


@router.get("/projects/{project_id}/dashboard", response_model=ProjectDashboard)
def get_dashboard(project_id: str, run_id: str | None = None) -> ProjectDashboard:
    """Optional run_id pins every workspace tab to the same run. Omitted = the most recent run, which is what every screen did before the workspace gained a run switcher (Slice 15)."""
    return get_project_dashboard(project_id, run_id)


@router.get("/projects/{project_id}/workspace", response_model=WorkspaceHeader)
def get_workspace(project_id: str, run_id: str | None = None) -> WorkspaceHeader:
    """The workspace header strip. Deliberately not the full dashboard --
    that costs ~14.7s building four fields the workspace never renders."""
    return get_workspace_header(project_id, run_id)
