"""
Project Dashboard aggregation (Clinova Phase 5, Epic 5.1). Every number
names which run it came from -- never a fabricated cross-run sum (runs
in the same project can overlap in content, so summing would double-count).
"""
from apps.api.models.common import RunRef
from apps.api.models.dashboard import (
    ActivityEvent, GapOpportunity, LinkedRef, ProjectDashboard, ProjectSummary, RunDelta,
    WorkspaceHeader,
)
from apps.api.services.copy_text import no_runs_in_project
from apps.api.services.measures import build_confidence_measures
from apps.api.services.project_runs import get_basis, list_project_runs
from apps.api.services.title_match import normalise_title as _normalise
from apps.api.services.runs_service import (
    _CHALLENGE_CHIPS, _NOT_CHALLENGED_CHIP, _UNKNOWN_VALIDATION_CHIP, _VALIDATION_CHIPS,
    build_counts, build_run_summary,
)
from utils.database import (
    get_run_manifests_bulk, list_artifacts, list_runs, load_run, load_run_gate_fields_bulk,
)

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


def _gap_cross_links(
    g: dict,
    papers_by_title: dict[str, str],
    proposals_by_gap: dict[str, list[str]],
) -> tuple[list[LinkedRef], list[LinkedRef]]:
    supporting = []
    for title in g.get("supporting_papers") or []:
        filename = papers_by_title.get(_normalise(title))
        supporting.append(LinkedRef(
            label=title,
            # A supporting paper is often a *reference*, not one of the
            # uploaded PDFs -- real, but with no Paper Detail screen to open.
            # Rendered as plain text rather than a link that would 404.
            href=f"/corpus/papers/{filename}" if filename else None,
        ))
    proposals = [
        LinkedRef(label=title, href="/workspace?tab=proposals")
        for title in proposals_by_gap.get(_normalise(g.get("title", "")), [])
    ]
    return supporting, proposals


def _gap_opportunity(
    g: dict,
    run_id: str,
    papers_by_title: dict[str, str] | None = None,
    proposals_by_gap: dict[str, list[str]] | None = None,
) -> GapOpportunity:
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
        **dict(zip(
            ("supporting_papers", "proposals"),
            _gap_cross_links(g, papers_by_title or {}, proposals_by_gap or {}),
        )),
    )


def _build_delta(all_runs: list[dict]) -> RunDelta | None:
    """None when there is nothing to compare against -- a single-run project
    has no 'since last run', and inventing a delta against an empty
    placeholder would be a fabricated number."""
    if len(all_runs) < 2:
        return None
    current, previous = all_runs[0], all_runs[1]
    try:
        from pipeline.run_compare import compare_runs
        cmp = compare_runs(previous["id"], current["id"])
    except Exception:
        # A run that predates a schema change can fail to compare. That's a
        # missing panel, never a broken dashboard.
        return None

    gaps = cmp.get("gaps") or {}
    papers = cmp.get("papers") or {}
    graph = cmp.get("graph") or {}
    proposals = cmp.get("proposals") or {}
    evidence = cmp.get("evidence") or {}

    gaps_added = [str(g) for g in (gaps.get("added") or [])]
    gaps_removed = [str(g) for g in (gaps.get("removed") or [])]
    papers_added = [str(p) for p in (papers.get("added") or [])]
    papers_removed = [str(p) for p in (papers.get("removed") or [])]
    entities_added = len(graph.get("entities_added") or [])
    entities_removed = len(graph.get("entities_removed") or [])
    evidence_delta = int(evidence.get("delta") or 0)
    proposals_added = int(proposals.get("added_count") or 0)
    proposals_removed = int(proposals.get("removed_count") or 0)

    return RunDelta(
        previous_run=RunRef(run_id=previous["id"], name=previous["name"],
                            created_at=str(previous["created_at"])),
        current_run=RunRef(run_id=current["id"], name=current["name"],
                           created_at=str(current["created_at"])),
        gaps_added=gaps_added, gaps_removed=gaps_removed,
        papers_added=papers_added, papers_removed=papers_removed,
        entities_added_count=entities_added, entities_removed_count=entities_removed,
        evidence_delta=evidence_delta,
        proposals_added_count=proposals_added, proposals_removed_count=proposals_removed,
        compare_href=f"/runs/compare?baseline={previous['id']}&candidate={current['id']}",
        unchanged=not any([
            gaps_added, gaps_removed, papers_added, papers_removed,
            entities_added, entities_removed, evidence_delta,
            proposals_added, proposals_removed,
        ]),
    )


def get_project_dashboard(project_id: str, run_id: str | None = None) -> ProjectDashboard:
    all_runs = list_project_runs(project_id)

    basis = get_basis(project_id, run_id)
    if basis is None:
        return ProjectDashboard(
            project_id=project_id, project_label=project_id, basis_run=None,
            basis_note="No runs exist for this project yet.",
            counts=[], confidence=[], recent_runs=[], top_opportunities=[],
            n_excluded_insufficient_evidence=0, activity=[],
            empty_reason=no_runs_in_project(),
        )

    basis_row, results = basis.row, basis.results

    basis_run = RunRef(run_id=basis_row["id"], name=basis_row["name"], created_at=str(basis_row["created_at"]))
    # Singular subject: note() renders "{subject} reflects ...", so a plural
    # here produced "Counts reflects run ...".
    basis_note = basis.note("This dashboard")

    all_gaps = [(g, basis_row["id"]) for g in results.get("gaps") or []]
    reportable = [(g, rid) for g, rid in all_gaps if g.get("challenger_status") in _REPORTED_AS_GAP_STATUSES]
    n_excluded = sum(1 for g, _ in all_gaps if g.get("challenger_status") == "INSUFFICIENT_EVIDENCE")

    def _sort_key(item):
        g, _ = item
        status_rank = 0 if g.get("challenger_status") in ("OPEN", "PARTIALLY_OPEN") else 1
        confidence_rank = {"high": 0, "medium": 1, "low": 2}.get(g.get("confidence"), 3)
        return (status_rank, confidence_rank, -len(g.get("evidence_basis") or ""))

    # Title -> filename / gap-title -> proposal-titles lookups, built once
    # per request so cross-link resolution stays O(1) per gap.
    papers_by_title = {
        _normalise((p.get("wiki") or {}).get("title") or p.get("filename", "")): p.get("filename", "")
        for p in results.get("papers") or []
    }
    proposals_by_gap: dict[str, list[str]] = {}
    for proposal in results.get("proposals") or []:
        key = _normalise(proposal.get("addresses_gap", ""))
        if key:
            proposals_by_gap.setdefault(key, []).append(proposal.get("title", ""))

    top = sorted(reportable, key=_sort_key)[:10]
    top_opportunities = [
        _gap_opportunity(g, rid, papers_by_title, proposals_by_gap) for g, rid in top
    ]

    # Bulk, not one build_run_summary() per run: the per-run path opened two
    # database connections each (~1.5s), so this list of five status chips
    # alone cost ~9s of the dashboard's ~15s render.
    recent_rows = all_runs[:5]
    recent_ids = [r["id"] for r in recent_rows]
    recent_gates = load_run_gate_fields_bulk(recent_ids)
    recent_manifests = get_run_manifests_bulk(recent_ids)
    recent_runs = [
        build_run_summary(
            r,
            results=recent_gates.get(r["id"], {}),
            manifest=recent_manifests.get(r["id"]),
            prefetched=True,
        )
        for r in recent_rows
    ]

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
        n_excluded_insufficient_evidence=n_excluded, activity=activity[:15],
        delta=_build_delta(all_runs), empty_reason=None,
    )


def get_workspace_header(project_id: str, run_id: str | None = None) -> WorkspaceHeader:
    """The workspace's header strip only.

    Deliberately NOT get_project_dashboard(): that builds recent_runs (a
    load_run + manifest read per run), top_opportunities, the activity feed
    and a full compare_runs delta, none of which the workspace renders. It
    measured ~14.7s against ~1.5s for this. See WorkspaceHeader's docstring.
    """
    basis = get_basis(project_id, run_id)
    if basis is None:
        return WorkspaceHeader(
            project_id=project_id, project_label=project_id, basis_run=None,
            basis_note="No runs exist for this project yet.",
            counts=[], confidence=[], empty_reason=no_runs_in_project(),
        )

    row, results = basis.row, basis.results
    return WorkspaceHeader(
        project_id=project_id, project_label=project_id,
        basis_run=RunRef(run_id=row["id"], name=row["name"], created_at=str(row["created_at"])),
        basis_note=basis.note("This workspace"),
        counts=build_counts(results),
        confidence=build_confidence_measures(results),
    )
