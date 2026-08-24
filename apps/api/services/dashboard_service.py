"""
Project Dashboard aggregation (Clinova Phase 5, Epic 5.1). Every number
names which run it came from -- never a fabricated cross-run sum (runs
in the same project can overlap in content, so summing would double-count).
"""
from apps.api.models.common import RunRef
from apps.api.models.dashboard import ActivityEvent, GapOpportunity, ProjectDashboard, ProjectSummary
from apps.api.services.measures import build_confidence_measures
from apps.api.services.runs_service import (
    _CHALLENGE_CHIPS, _NOT_CHALLENGED_CHIP, _UNKNOWN_VALIDATION_CHIP, _VALIDATION_CHIPS,
    build_counts, build_run_summary,
)
from utils.database import list_artifacts, list_runs, load_run

# Same "what counts as a reported gap" rule evals/regression/metrics.py's
# compute_gap_precision() uses (_REPORTED_AS_GAP_STATUSES) -- the
# dashboard and the evaluation harness must agree on the definition.
_REPORTED_AS_GAP_STATUSES = {"OPEN", "PARTIALLY_OPEN", "CONTESTED"}


def list_projects() -> list[ProjectSummary]:
    runs = list_runs(limit=200)
    counts: dict[str, int] = {}
    for r in runs:
        project_id = r.get("domain") or "default"
        counts[project_id] = counts.get(project_id, 0) + 1
    return [ProjectSummary(project_id=pid, label=pid, n_runs=n) for pid, n in sorted(counts.items())]


def _gap_opportunity(g: dict, run_id: str) -> GapOpportunity:
    confidence_str = g.get("confidence")
    level = confidence_str.title() if confidence_str in ("high", "medium", "low") else "Unknown"
    from apps.api.models.common import Measure
    confidence = Measure(
        key="gap_confidence", label="Confidence", value=None,
        display=level if confidence_str else "Not recorded", level=level,
        recorded=confidence_str is not None,
        basis=f"LLM/pattern-assigned confidence level: {confidence_str or 'not recorded'}.",
        source="gap.confidence",
    )
    return GapOpportunity(
        gap_id=g.get("gap_id"), title=g.get("title", ""), source=g.get("source"),
        evidence_basis=g.get("evidence_basis"),
        validation=_VALIDATION_CHIPS.get(g.get("validation_status"), _UNKNOWN_VALIDATION_CHIP),
        challenge=_CHALLENGE_CHIPS.get(g.get("challenger_status"), _NOT_CHALLENGED_CHIP),
        confidence=confidence, run_id=run_id,
    )


def get_project_dashboard(project_id: str) -> ProjectDashboard:
    all_runs = [r for r in list_runs(limit=200) if (r.get("domain") or "default") == project_id]

    if not all_runs:
        return ProjectDashboard(
            project_id=project_id, project_label=project_id, basis_run=None,
            basis_note="No runs exist for this project yet.",
            counts=[], confidence=[], recent_runs=[], top_opportunities=[],
            n_excluded_insufficient_evidence=0, activity=[],
            empty_reason="No runs in this project yet. Runs created in the Streamlit "
                          "workspace appear here automatically.",
        )

    basis_row = all_runs[0]  # list_runs() orders by created_at DESC
    loaded = load_run(basis_row["id"]) or {}
    results = loaded.get("results", {}) or {}

    basis_run = RunRef(run_id=basis_row["id"], name=basis_row["name"], created_at=str(basis_row["created_at"]))
    basis_note = f"Counts reflect run \"{basis_row['name']}\" ({basis_row['id'][:8]}) — the most recent run in this project."

    all_gaps = [(g, basis_row["id"]) for g in results.get("gaps") or []]
    reportable = [(g, rid) for g, rid in all_gaps if g.get("challenger_status") in _REPORTED_AS_GAP_STATUSES]
    n_excluded = sum(1 for g, _ in all_gaps if g.get("challenger_status") == "INSUFFICIENT_EVIDENCE")

    def _sort_key(item):
        g, _ = item
        status_rank = 0 if g.get("challenger_status") in ("OPEN", "PARTIALLY_OPEN") else 1
        confidence_rank = {"high": 0, "medium": 1, "low": 2}.get(g.get("confidence"), 3)
        return (status_rank, confidence_rank, -len(g.get("evidence_basis") or ""))

    top = sorted(reportable, key=_sort_key)[:10]
    top_opportunities = [_gap_opportunity(g, rid) for g, rid in top]

    recent_runs = [build_run_summary(r) for r in all_runs[:5]]

    activity: list[ActivityEvent] = []
    for r in all_runs[:10]:
        activity.append(ActivityEvent(
            timestamp=str(r["created_at"]), kind="run", title=r["name"],
            detail=f"{r.get('n_papers', 0)} papers, {r.get('n_gaps', 0)} gaps, {r.get('n_proposals', 0)} proposals",
            href=f"/runs/{r['id']}",
        ))
    for a in list_artifacts(artifact_type="pipeline", project_id=project_id)[:10]:
        activity.append(ActivityEvent(
            timestamp=str(a.get("created_at", "")), kind="artifact",
            title=f"Artifact {a['artifact_id']}", detail=f"Status: {a.get('status', 'unknown')}",
            href=f"/runs/{a.get('run_id', '')}" if a.get("run_id") else "/runs",
        ))
    activity.sort(key=lambda e: e.timestamp, reverse=True)

    return ProjectDashboard(
        project_id=project_id, project_label=project_id, basis_run=basis_run, basis_note=basis_note,
        counts=build_counts(results), confidence=build_confidence_measures(results),
        recent_runs=recent_runs, top_opportunities=top_opportunities,
        n_excluded_insufficient_evidence=n_excluded, activity=activity[:15], empty_reason=None,
    )
