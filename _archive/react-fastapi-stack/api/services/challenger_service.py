"""
Gap Challenger screen (Clinova Phase 5, Epic 5.3). Reads each gap's own
challenge_funnel dict, saved verbatim by pipeline/gap_challenger.py::
run_challenge() -- app.py merges it directly onto the gap dict under
`results.gaps[i]`, never a separate table.
"""
from apps.api.models.challenger import ChallengeFunnelView, ChallengerView, GapChallengeView, JudgedCandidateView
from apps.api.models.common import RunRef
from apps.api.services.copy_text import no_runs_in_project
from apps.api.services.project_runs import get_basis
from apps.api.services.runs_service import _CHALLENGE_CHIPS, _NOT_CHALLENGED_CHIP


def _funnel_view(f: dict | None) -> ChallengeFunnelView | None:
    if not f:
        return None
    return ChallengeFunnelView(
        query_families=f.get("query_families") or [],
        providers_queried=f.get("providers_queried") or [],
        provider_success=f.get("provider_success") or {},
        candidate_count=f.get("candidate_count", 0),
        post_dedup_count=f.get("post_dedup_count", 0),
        post_metadata_filter_count=f.get("post_metadata_filter_count", 0),
        post_rerank_count=f.get("post_rerank_count", 0),
        rerank_used=bool(f.get("rerank_used")),
        search_coverage_score=f.get("search_coverage_score"),
        relevant_count=f.get("relevant_count", 0),
        contradiction_count=f.get("contradiction_count", 0),
        converging_count=f.get("converging_count", 0),
        judged_candidates=[
            JudgedCandidateView(
                title=c.get("title", ""), relevant=bool(c.get("relevant")),
                relevance_type=c.get("relevance_type"), contradicts_gap=bool(c.get("contradicts_gap")),
                confidence=c.get("confidence"),
            )
            for c in f.get("judged_candidates") or []
        ],
    )


def get_project_challenger(project_id: str, run_id: str | None = None) -> ChallengerView:
    basis = get_basis(project_id, run_id)
    if basis is None:
        return ChallengerView(
            basis_run=None, basis_note="No runs exist for this project yet.", gaps=[],
            empty_reason=no_runs_in_project(),
        )

    basis_row, results = basis.row, basis.results

    run = RunRef(run_id=basis_row["id"], name=basis_row["name"], created_at=str(basis_row["created_at"]))
    basis_note = basis.note("Gap Challenger")

    gaps = results.get("gaps") or []
    views = [
        GapChallengeView(
            gap_id=g.get("gap_id"), title=g.get("title", ""),
            challenger_state=g.get("challenger_state"),
            status=_CHALLENGE_CHIPS.get(g.get("challenger_status"), _NOT_CHALLENGED_CHIP),
            reason=g.get("challenger_reason"),
            funnel=_funnel_view(g.get("challenge_funnel")),
        )
        for g in gaps
    ]

    empty_reason = "No gaps were extracted for this run." if not gaps else None
    return ChallengerView(basis_run=run, basis_note=basis_note, gaps=views, empty_reason=empty_reason)
