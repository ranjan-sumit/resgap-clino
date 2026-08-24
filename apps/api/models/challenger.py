from pydantic import BaseModel

from apps.api.models.common import RunRef, StatusChip


class JudgedCandidateView(BaseModel):
    title: str
    relevant: bool
    relevance_type: str | None
    contradicts_gap: bool
    confidence: str | None


class ChallengeFunnelView(BaseModel):
    query_families: list[str]
    providers_queried: list[str]
    provider_success: dict[str, bool]
    candidate_count: int
    post_dedup_count: int
    post_metadata_filter_count: int
    post_rerank_count: int
    rerank_used: bool
    search_coverage_score: float | None
    relevant_count: int
    contradiction_count: int
    converging_count: int
    judged_candidates: list[JudgedCandidateView]


class GapChallengeView(BaseModel):
    gap_id: str | None
    title: str
    challenger_state: str | None
    status: StatusChip
    reason: str | None
    funnel: ChallengeFunnelView | None


class ChallengerView(BaseModel):
    run: RunRef | None
    basis_note: str
    gaps: list[GapChallengeView]
    empty_reason: str | None = None
