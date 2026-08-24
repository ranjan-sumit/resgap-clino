from fastapi import APIRouter

from apps.api.models.graph import GraphView
from apps.api.services.graph_service import get_project_graph

router = APIRouter(tags=["graph"])


@router.get("/projects/{project_id}/graph", response_model=GraphView)
def project_graph(project_id: str) -> GraphView:
    return get_project_graph(project_id)
