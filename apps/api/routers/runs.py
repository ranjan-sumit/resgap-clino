from fastapi import APIRouter, Query

from apps.api.errors import NotFoundError
from apps.api.models.runs import RunDetail, RunListResponse, TraceStep
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
