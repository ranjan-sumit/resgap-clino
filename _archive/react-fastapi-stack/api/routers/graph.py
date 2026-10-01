from fastapi import APIRouter

from apps.api.models.graph import GraphView
from apps.api.services.graph_service import get_project_graph

router = APIRouter(tags=["graph"])


@router.get("/projects/{project_id}/graph", response_model=GraphView)
def project_graph(project_id: str, run_id: str | None = None) -> GraphView:
    """Optional run_id pins every workspace tab to the same run. Omitted = the most recent run, which is what every screen did before the workspace gained a run switcher (Slice 15)."""
    return get_project_graph(project_id, run_id)
