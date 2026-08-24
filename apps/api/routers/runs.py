from typing import Literal

from fastapi import APIRouter, Query

from apps.api.errors import NotFoundError
from apps.api.models.artifacts import ArtifactView
from apps.api.models.runs import RunDetail, RunListResponse, TraceStep
from apps.api.services.artifacts_service import promote_run_pipeline_artifact
from apps.api.services.run_status import trace_status_chip
from apps.api.services.runs_service import build_run_detail, list_run_summaries
from utils.database import load_run

router = APIRouter(tags=["runs"])


@router.get("/runs", response_model=RunListResponse)
def list_runs_endpoint(limit: int = Query(50, ge=1, le=200)) -> RunListResponse:
    summaries = list_run_summaries(limit=limit)
    empty_reason = "No runs have been saved yet." if not summaries else None
    return RunListResponse(runs=summaries, empty_reason=empty_reason)


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str) -> RunDetail:
    return build_run_detail(run_id)


@router.get("/runs/{run_id}/manifest")
def get_run_manifest_endpoint(run_id: str):
    detail = build_run_detail(run_id)
    if detail.manifest is None:
        return {"recorded": False, "reason": "No run manifest was recorded for this run."}
    return detail.manifest


@router.get("/runs/{run_id}/trace", response_model=list[TraceStep])
def get_run_trace(run_id: str) -> list[TraceStep]:
    loaded = load_run(run_id)
    if not loaded:
        raise NotFoundError(f"Run '{run_id}' was not found.")
    results = loaded.get("results", {}) or {}
    trace = results.get("pipeline_trace") or []
    return [
        TraceStep(index=i, stage=t.get("stage", ""), inputs=t.get("inputs", ""),
                  outputs=t.get("outputs", ""), status=trace_status_chip(t.get("status")))
        for i, t in enumerate(trace)
    ]


@router.post("/runs/{run_id}/promote", response_model=ArtifactView)
def promote_run(
    run_id: str,
    to_status: Literal["CANDIDATE", "CHAMPION", "ARCHIVED"] = Query(...),
) -> ArtifactView:
    """Promotes this run's own 'pipeline'-type artifact to `to_status`.
    Real write path: rejects an illegal lifecycle transition (400) and a
    run with no registered pipeline artifact (404) rather than silently
    no-op'ing -- see Compare's PromotionGateView.can_evaluate for the
    read-side gate a UI button should check before calling this."""
    return promote_run_pipeline_artifact(run_id, to_status)
