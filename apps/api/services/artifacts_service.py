"""
Versions screen (Clinova Phase 5, Epic 5.4): the Research Artifact Registry
(research_artifacts table, FR-22), across every artifact_type -- not scoped
to one project or run, since the registry itself is the whole point (an
artifact can outlive the run that created it).
"""
from apps.api.models.artifacts import ArtifactListResponse, ArtifactView
from apps.api.services.lineage_service import _ARTIFACT_STATUS_CHIPS, _UNKNOWN_ARTIFACT_STATUS
from utils.database import _ARTIFACT_LEGAL_TRANSITIONS, list_artifacts, promote_artifact


def _artifact_view(a: dict) -> ArtifactView:
    status = a.get("status", "EXPERIMENTAL")
    return ArtifactView(
        artifact_id=a["artifact_id"], artifact_type=a["artifact_type"],
        artifact_version=a.get("artifact_version", ""),
        status=_ARTIFACT_STATUS_CHIPS.get(status, _UNKNOWN_ARTIFACT_STATUS),
        project_id=a.get("project_id", ""), run_id=a.get("run_id"),
        parent_artifact=a.get("parent_artifact"), created_at=str(a.get("created_at", "")),
        next_legal_statuses=sorted(_ARTIFACT_LEGAL_TRANSITIONS.get(status, set())),
    )


def list_all_artifacts() -> ArtifactListResponse:
    rows = list_artifacts()
    artifacts = [_artifact_view(a) for a in rows]
    empty_reason = None
    if not artifacts:
        empty_reason = "No artifacts have been registered yet. Every completed run records one " \
                        "'pipeline'-type artifact (Epic 4.1) once a real run has finished."
    return ArtifactListResponse(artifacts=artifacts, empty_reason=empty_reason)


def promote_run_pipeline_artifact(run_id: str, to_status: str) -> ArtifactView:
    """Promotes the run's own 'pipeline'-type artifact -- the same
    `f"pipeline:{run_id}"` id compare_service.py's candidate_artifact_id
    already resolves. promote_artifact() itself raises ValueError (-> 404,
    already handled) if no such artifact is registered, and
    InvalidArtifactTransitionError (-> 400) on an illegal transition --
    never silently applied."""
    updated = promote_artifact(f"pipeline:{run_id}", to_status)
    return _artifact_view(updated)
