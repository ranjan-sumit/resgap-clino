"""
Shapes utils/database.py's raw run dicts into the Phase 5 API's response
models (Clinova Phase 5, Epic 5.1). All business/presentation logic lives
here, never in routers/runs.py.
"""
from apps.api.errors import NotFoundError
from apps.api.models.common import CountStat, Measure, StatusChip, VersionField
from apps.api.services.title_match import normalise_title as _normalise_title
from apps.api.models.runs import (
    LinkedRef,
    GapSummary, PaperRef, ProposalSummary, RunDetail, RunManifestView,
    RunSummary, TokenUsageView, TraceStep,
)
from apps.api.services.measures import build_confidence_measures
from apps.api.services.run_status import derive_run_status, trace_status_chip
from utils.database import get_run_manifest, get_run_row, load_run, list_runs

try:
    from pipeline.gap_challenger import SEARCH_COVERAGE_THRESHOLD
except ImportError:  # pragma: no cover
    SEARCH_COVERAGE_THRESHOLD = 0.6

_VERSION_SPECS = [
    ("input_corpus_version", "Corpus Version"),
    ("pipeline_version", "Pipeline Version"),
    ("model_bundle_version", "Model Version"),
    ("prompt_bundle_version", "Prompt Version"),
    ("graph_version", "Graph Version"),
]
# Structurally never written by app.py's manifest call (confirmed by
# reading app.py:1516-1650 directly) -- an honest, specific reason each,
# not a bare "Not recorded".
_VERSION_NOTES = {
    "input_corpus_version": "This pipeline does not version its input corpus yet -- no corpus "
                             "artifact version is written at run time.",
    "pipeline_version": "No pipeline version constant is recorded by app.py's manifest write.",
    "prompt_bundle_version": "Prompts are not bundled/versioned yet (pipeline/agent_config.py "
                              "defines agent roles, not a versioned prompt bundle).",
}

_GATE_TONE = {"PASS": "positive", "DEGRADED": "caution", "FAIL": "critical",
              "CLEAN": "positive", "FALLBACK": "critical"}
_GATE_ICON = {"PASS": "check-circle", "DEGRADED": "alert-triangle", "FAIL": "octagon-x",
              "CLEAN": "check-circle", "FALLBACK": "octagon-x"}

_VALIDATION_CHIPS = {
    "open": StatusChip(code="OPEN", label="Open", tone="positive", icon="check-circle",
                        reason="Validated as an open gap against Semantic Scholar/arXiv search."),
    "partial": StatusChip(code="PARTIAL", label="Partially addressed", tone="caution", icon="alert-triangle",
                           reason="Some existing work partially addresses this gap."),
    "solved": StatusChip(code="SOLVED", label="Already solved", tone="neutral", icon="circle-dashed",
                          reason="Existing work already addresses this gap."),
    "pending": StatusChip(code="PENDING", label="Pending validation", tone="unknown", icon="help-circle",
                           reason="Validation has not completed for this gap."),
}
_UNKNOWN_VALIDATION_CHIP = StatusChip(code="UNKNOWN", label="Unknown", tone="unknown", icon="help-circle",
                                       reason="No validation status was recorded for this gap.")

_CHALLENGE_CHIPS = {
    "OPEN": StatusChip(code="OPEN", label="Open", tone="positive", icon="check-circle",
                        reason="The Gap Challenger found no existing work addressing this gap."),
    "PARTIALLY_OPEN": StatusChip(code="PARTIALLY_OPEN", label="Partially open", tone="caution",
                                  icon="alert-triangle",
                                  reason="One adjacent relevant result found, without contradiction."),
    "CONTESTED": StatusChip(code="CONTESTED", label="Contested", tone="caution", icon="alert-triangle",
                             reason="Relevant results found, but they contradict each other or the gap's premise."),
    "LIKELY_CLOSED": StatusChip(code="LIKELY_CLOSED", label="Likely closed", tone="neutral", icon="circle-dashed",
                                 reason="Two or more converging high-confidence results address this gap."),
    "CLOSED": StatusChip(code="CLOSED", label="Closed", tone="neutral", icon="circle-dashed",
                          reason="Three or more converging high-confidence results address this gap."),
    # Its own tone AND its own unique icon (never shared with OPEN) -- the
    # literal implementation of 02-ux-specification.md §6's binding rule
    # that INSUFFICIENT_EVIDENCE must read as distinct from OPEN.
    "INSUFFICIENT_EVIDENCE": StatusChip(
        code="INSUFFICIENT_EVIDENCE", label="Insufficient evidence", tone="unknown", icon="search-x",
        reason=(f"Search coverage fell below the {SEARCH_COVERAGE_THRESHOLD:.0%} threshold, so this "
                "gap's novelty could not be assessed. This is not a finding that the gap is open."),
    ),
}
_NOT_CHALLENGED_CHIP = StatusChip(code="NOT_CHALLENGED", label="Not challenged", tone="neutral",
                                   icon="help-circle", reason="The Gap Challenger stage was not enabled for this run.")


def _version_fields(manifest: dict | None) -> list[VersionField]:
    fields = []
    for key, label in _VERSION_SPECS:
        value = manifest.get(key) if manifest else None
        fields.append(VersionField(
            key=key, label=label, value=value, recorded=value is not None,
            note=None if value is not None else _VERSION_NOTES.get(key, "Not recorded for this run."),
        ))
    return fields


def _gate_chip(gate_key: str, label: str, value: str | None) -> StatusChip:
    if value is None:
        disabled_reason = ("The Corpus Quality Engine was disabled for this run."
                            if gate_key == "corpus" else "Graph scoring was disabled for this run.")
        return StatusChip(code=f"{gate_key.upper()}_NOT_EVALUATED", label=f"{label}: Not evaluated",
                           tone="neutral", icon="circle-dashed", reason=disabled_reason)
    return StatusChip(
        code=f"{gate_key.upper()}_{value}", label=f"{label}: {value.title()}",
        tone=_GATE_TONE.get(value, "unknown"), icon=_GATE_ICON.get(value, "help-circle"),
        reason=f"{label} quality gate: {value}.",
    )


def _quality_gate_chips(manifest: dict | None) -> list[StatusChip]:
    qgr = (manifest or {}).get("quality_gate_results") or {}
    return [
        _gate_chip("corpus", "Corpus", qgr.get("corpus")),
        _gate_chip("graph", "Graph", qgr.get("graph")),
    ]


def _token_usage_view(manifest: dict | None) -> TokenUsageView:
    usage = (manifest or {}).get("token_usage")
    if not usage:
        return TokenUsageView(
            recorded=False,
            note="Token usage was not captured for this run. Usage capture requires a provider "
                 "that supports stream_options (utils/token_meter.py).",
        )
    return TokenUsageView(
        recorded=True, total=usage.get("total"), n_calls_recorded=usage.get("n_calls_recorded"),
        by_stage=usage.get("by_stage"), by_agent=usage.get("by_agent"), by_model=usage.get("by_model"),
    )


def _gap_summary(g: dict, papers_by_title: dict | None = None, proposals_by_gap: dict | None = None) -> GapSummary:
    validation_chip = _VALIDATION_CHIPS.get(g.get("validation_status"), _UNKNOWN_VALIDATION_CHIP)
    challenge_chip = _CHALLENGE_CHIPS.get(g.get("challenger_status"), _NOT_CHALLENGED_CHIP)
    confidence_str = g.get("confidence")
    level = confidence_str.title() if confidence_str in ("high", "medium", "low") else "Unknown"
    confidence = Measure(
        key="gap_confidence", label="Confidence", value=None,
        display=level if confidence_str else "Not recorded", level=level,
        recorded=confidence_str is not None,
        basis=f"LLM/pattern-assigned confidence level: {confidence_str or 'not recorded'}.",
        source="gap.confidence",
    )
    supporting = [
        LinkedRef(
            label=title,
            # A supporting paper is often a *reference*, not one of the
            # uploaded PDFs -- real, but with no Paper Detail screen to open.
            # Those render as plain text rather than a link that would 404.
            href=(f"/corpus/papers/{papers_by_title[_normalise_title(title)]}"
                  if _normalise_title(title) in (papers_by_title or {}) else None),
        )
        for title in g.get("supporting_papers") or []
    ]
    proposals = [
        LinkedRef(label=title, href="/proposals")
        for title in (proposals_by_gap or {}).get(_normalise_title(g.get("title", "")), [])
    ]
    return GapSummary(
        gap_id=g.get("gap_id"), title=g.get("title", ""), source=g.get("source"),
        evidence_basis=g.get("evidence_basis"), validation=validation_chip,
        challenge=challenge_chip, confidence=confidence,
        supporting_papers=supporting, proposals=proposals,
    )


def _paper_ref(p: dict) -> PaperRef:
    wiki = p.get("wiki") or {}
    return PaperRef(filename=p.get("filename", ""), title=wiki.get("title"), char_count=p.get("char_count", 0))


def _proposal_summary(p: dict, gap_titles: set[str] | None = None) -> ProposalSummary:
    raw_gap = (p.get("addresses_gap") or "").strip()
    addresses_gap = None
    if raw_gap:
        known = _normalise_title(raw_gap) in (gap_titles or set())
        addresses_gap = LinkedRef(label=raw_gap, href="/gaps" if known else None)
    return ProposalSummary(
        addresses_gap=addresses_gap,
        title=p.get("title", ""), addresses_gap_id=p.get("addresses_gap_id"),
        addresses_gap_id_resolution=p.get("addresses_gap_id_resolution"),
        problem_statement=p.get("problem_statement"), methodology=p.get("methodology"),
        novelty=p.get("novelty"), builds_on=p.get("builds_on") or [],
        expected_contribution=p.get("expected_contribution"),
        suggested_experiments=p.get("suggested_experiments") or [],
        potential_datasets=p.get("potential_datasets") or [],
        confidence=p.get("confidence"), effort_estimate=p.get("effort_estimate"), risk=p.get("risk"),
    )


def _trace_steps(results: dict) -> list[TraceStep]:
    trace = results.get("pipeline_trace") or []
    return [
        TraceStep(index=i, stage=t.get("stage", ""), inputs=t.get("inputs", ""),
                  outputs=t.get("outputs", ""), status=trace_status_chip(t.get("status")))
        for i, t in enumerate(trace)
    ]


def build_counts(results: dict) -> list[CountStat]:
    papers = results.get("papers") or []
    ref_summary = results.get("ref_summary") or {}
    evidence_objects = results.get("evidence_objects") or {}
    graph_stats = (results.get("graph") or {}).get("stats") or {}
    gaps = results.get("gaps") or []
    proposals = results.get("proposals") or []
    n_evidence = sum(len(v) for v in evidence_objects.values())

    def stat(key, label, value, source):
        return CountStat(key=key, label=label, value=value, display=f"{value:,}", recorded=True, source=source)

    return [
        stat("papers", "Papers", len(papers), "runs.results.papers"),
        stat("references", "References", ref_summary.get("total", 0), "results.ref_summary"),
        stat("evidence", "Evidence Objects", n_evidence, "results.evidence_objects"),
        stat("graph_entities", "Graph Entities", graph_stats.get("entity_count", 0), "results.graph.stats"),
        stat("graph_relationships", "Graph Relationships",
             graph_stats.get("relationship_count", 0), "results.graph.stats"),
        stat("gaps", "Research Gaps", len(gaps), "results.gaps"),
        stat("proposals", "Proposals", len(proposals), "results.proposals"),
    ]


def build_run_summary(run_row: dict) -> RunSummary:
    """`run_row` is one entry of list_runs()'s output. Loads the full
    results + manifest per run -- an N+1 query pattern acceptable at the
    real current run count (single digits); utils/database.py could gain
    an additive list_runs_with_manifests() LEFT JOIN if/when this
    matters at scale (not needed for this slice)."""
    run_id = run_row["id"]
    loaded = load_run(run_id)
    results = (loaded or {}).get("results", {}) or {}
    manifest = get_run_manifest(run_id)

    return RunSummary(
        run_id=run_id, name=run_row["name"], created_at=str(run_row["created_at"]),
        project_id=run_row.get("domain") or "default",
        n_papers=run_row.get("n_papers", 0), n_gaps=run_row.get("n_gaps", 0),
        n_proposals=run_row.get("n_proposals", 0),
        status=derive_run_status(results, manifest),
        versions=_version_fields(manifest),
        duration_seconds=(manifest or {}).get("run_duration_seconds"),
        token_usage_total=((manifest or {}).get("token_usage") or {}).get("total"),
        quality_gates=_quality_gate_chips(manifest),
    )


def list_run_summaries(limit: int = 50) -> list[RunSummary]:
    return [build_run_summary(r) for r in list_runs(limit=limit)]


def build_manifest_view(run_id: str, project_id: str, manifest: dict | None) -> RunManifestView | None:
    if manifest is None:
        return None
    return RunManifestView(
        run_id=run_id, project_id=project_id, versions=_version_fields(manifest),
        quality_gates=_quality_gate_chips(manifest), token_usage=_token_usage_view(manifest),
        output_artifacts=manifest.get("output_artifacts") or [],
        search_providers=manifest.get("search_providers") or [],
        academic_search_date=manifest.get("academic_search_date"),
        parser_versions=manifest.get("parser_versions") or {},
        run_duration_seconds=manifest.get("run_duration_seconds"),
        warnings=manifest.get("warnings") or [],
        created_at=manifest.get("created_at"),
    )


def _gap_titles(results: dict) -> set[str]:
    return {_normalise_title(g.get("title", "")) for g in results.get("gaps") or [] if g.get("title")}


def _papers_by_title(results: dict) -> dict[str, str]:
    return {
        _normalise_title((p.get("wiki") or {}).get("title") or p.get("filename", "")): p.get("filename", "")
        for p in results.get("papers") or []
    }


def _proposals_by_gap(results: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for proposal in results.get("proposals") or []:
        key = _normalise_title(proposal.get("addresses_gap", ""))
        if key:
            out.setdefault(key, []).append(proposal.get("title", ""))
    return out


def build_run_detail(run_id: str) -> RunDetail:
    loaded = load_run(run_id)
    if not loaded:
        raise NotFoundError(f"Run '{run_id}' was not found.")
    run_row = get_run_row(run_id)
    if not run_row:
        # loaded a real results blob but the row disappeared between the
        # two reads -- a genuine (if unlikely) race, not swallowed.
        raise NotFoundError(f"Run '{run_id}' was not found.")
    results = loaded.get("results", {}) or {}
    manifest = get_run_manifest(run_id)
    project_id = run_row.get("domain") or "default"

    return RunDetail(
        run_id=run_id, name=run_row["name"],
        created_at=str(run_row["created_at"]), project_id=project_id,
        status=derive_run_status(results, manifest),
        counts=build_counts(results), confidence=build_confidence_measures(results),
        versions=_version_fields(manifest), manifest=build_manifest_view(run_id, project_id, manifest),
        trace=_trace_steps(results),
        papers=[_paper_ref(p) for p in results.get("papers") or []],
        gaps=[
            _gap_summary(g, _papers_by_title(results), _proposals_by_gap(results))
            for g in results.get("gaps") or []
        ],
        proposals=[
            _proposal_summary(p, _gap_titles(results))
            for p in results.get("proposals") or []
        ],
        warnings=(manifest or {}).get("warnings") or [],
        gate_blocked=bool(results.get("gate_blocked")),
        gate_block_reasons=results.get("gate_block_reasons") or [],
    )
