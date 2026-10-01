from fastapi import APIRouter, Query

from apps.api.models.lineage import ScientificLineage, TechnicalLineage
from apps.api.services.lineage_service import get_scientific_lineage_view, get_technical_lineage_view

router = APIRouter(tags=["lineage"])


@router.get("/runs/{run_id}/lineage/technical", response_model=TechnicalLineage)
def technical_lineage(run_id: str) -> TechnicalLineage:
    return get_technical_lineage_view(run_id)


@router.get("/runs/{run_id}/lineage/scientific", response_model=ScientificLineage)
def scientific_lineage(run_id: str, gap_id: str | None = Query(None)) -> ScientificLineage:
    return get_scientific_lineage_view(run_id, gap_id=gap_id)
