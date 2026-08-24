from fastapi import APIRouter

from apps.api.models.dashboard import ProjectDashboard, ProjectSummary
from apps.api.services.dashboard_service import get_project_dashboard, list_projects

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[ProjectSummary])
def get_projects() -> list[ProjectSummary]:
    return list_projects()


@router.get("/projects/{project_id}/dashboard", response_model=ProjectDashboard)
def get_dashboard(project_id: str) -> ProjectDashboard:
    return get_project_dashboard(project_id)
