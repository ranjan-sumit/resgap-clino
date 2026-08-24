from fastapi import APIRouter

from apps.api.models.evidence import EvidenceView
from apps.api.services.evidence_service import get_project_evidence

router = APIRouter(tags=["evidence"])


@router.get("/projects/{project_id}/evidence", response_model=EvidenceView)
def project_evidence(project_id: str) -> EvidenceView:
    return get_project_evidence(project_id)
