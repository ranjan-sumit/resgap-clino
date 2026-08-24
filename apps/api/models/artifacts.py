from typing import Literal

from pydantic import BaseModel

from apps.api.models.common import StatusChip

ArtifactStatus = Literal["EXPERIMENTAL", "CANDIDATE", "CHAMPION", "ARCHIVED"]


class ArtifactView(BaseModel):
    artifact_id: str
    artifact_type: str
    artifact_version: str
    status: StatusChip
    project_id: str
    run_id: str | None
    parent_artifact: str | None
    created_at: str
    next_legal_statuses: list[ArtifactStatus]


class ArtifactListResponse(BaseModel):
    artifacts: list[ArtifactView]
    empty_reason: str | None = None
