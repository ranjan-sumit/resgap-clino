from fastapi import APIRouter

from apps.api.models.evidence import EvidenceView
from apps.api.services.evidence_service import get_project_evidence

router = APIRouter(tags=["evidence"])


@router.get("/projects/{project_id}/evidence", response_model=EvidenceView)
def project_evidence(project_id: str, run_id: str | None = None) -> EvidenceView:
    """Optional run_id pins every workspace tab to the same run. Omitted = the most recent run, which is what every screen did before the workspace gained a run switcher (Slice 15)."""
    return get_project_evidence(project_id, run_id)
