from fastapi import APIRouter, Query
from fastapi.responses import Response

from apps.api.services.reports_service import get_run_report

router = APIRouter(tags=["reports"])


@router.get("/runs/{run_id}/report")
def run_report(run_id: str, format: str = Query("html")) -> Response:
    content, filename, media_type = get_run_report(run_id, format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
