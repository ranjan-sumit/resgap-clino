"""
Shapes pipeline/run_compare.py::compare_runs() and
evals/regression/promotion_gate.py::evaluate_promotion() into the
Compare screen's response model (Clinova Phase 5, Epic 5.1).
"""
from apps.api.models.common import RunRef, StatusChip
from apps.api.models.compare import (
    ConfidenceChange, DiffSection, EvidenceDiff, GapDiff, GraphDiff,
    ManifestFieldDiff, MetricComparison, PromotionGateView, RunComparison,
)
from evals.regression.promotion_gate import METRIC_DIRECTION, evaluate_promotion
from pipeline.run_compare import compare_runs
from utils.database import get_run_manifest, get_run_row, list_artifacts

_METRIC_LABELS = {
    "false_novelty_rate": "False Novelty Rate",
    "corpus_contamination_rate": "Corpus Contamination Rate",
    "gap_precision": "Gap Precision",
    "contradiction_recall": "Contradiction Recall",
    "retrieval_recall": "Retrieval Recall",
    "extraction_completeness": "Extraction Completeness",
    "reference_resolution_precision": "Reference Resolution Precision",
    "reference_recall": "Reference Recall",
    "evidence_coverage": "Evidence Coverage",
    "consistency_score": "Consistency (Repeatability)",
    "latency_seconds": "Latency",
    "token_usage_total": "Token Usage",
}
_RAW_NUMBER_METRICS = {"latency_seconds", "token_usage_total"}


def _display(key: str, value: float | None) -> str:
    if value is None:
        return "Not measured"
    if key == "latency_seconds":
        return f"{value:.1f}s"
    if key == "token_usage_total":
        return f"{int(value):,}"
    return f"{value:.0%}"


def _better(baseline: float | None, candidate: float | None, direction: str) -> str:
    if baseline is None or candidate is None:
        return "unknown"
    if baseline == candidate:
        return "equal"
    if direction == "higher":
        return "candidate" if candidate > baseline else "baseline"
    return "candidate" if candidate < baseline else "baseline"


def _run_ref(run_id: str) -> RunRef:
    row = get_run_row(run_id)
    if not row:
        return RunRef(run_id=run_id, name=run_id, created_at="")
    return RunRef(run_id=run_id, name=row["name"], created_at=str(row["created_at"]))


def _build_metrics(champion_metrics: dict, candidate_metrics: dict) -> list[MetricComparison]:
    """Runs the SAME pure evaluate_promotion() the promotion gate uses,
    over every one of the 12 named §3 metrics -- so the Compare screen's
    metric table and the actual promotion decision are computed from one
    call, never two divergent implementations."""
    report = evaluate_promotion(champion_metrics, candidate_metrics)
    rows_by_key = {r["metric"]: r for r in report["metric_results"]}
    metrics = []
    for key in sorted(METRIC_DIRECTION):
        row = rows_by_key.get(key)
        baseline = champion_metrics.get(key)
        candidate = candidate_metrics.get(key)
        direction = METRIC_DIRECTION[key]
        metrics.append(MetricComparison(
            key=key, label=_METRIC_LABELS.get(key, key.replace("_", " ").title()),
            baseline=baseline, candidate=candidate,
            baseline_display=_display(key, baseline), candidate_display=_display(key, candidate),
            delta_pct=row.get("delta_pct") if row and key not in _RAW_NUMBER_METRICS else None,
            direction=direction, better=_better(baseline, candidate, direction),
            verdict=row["verdict"] if row else "not_measured",
            tolerance=row.get("tolerance") if row else None,
        ))
    return metrics


def _manifest_diff(manifest: dict) -> list[ManifestFieldDiff]:
    specs = [
        ("model_bundle_version", "Model Bundle"),
        ("pipeline_version", "Pipeline Version"),
        ("quality_gate_results", "Quality Gate Results"),
        ("run_duration_seconds", "Duration"),
    ]
    diffs = []
    for key, label in specs:
        b = manifest.get(f"{key}_a")
        c = manifest.get(f"{key}_b")
        diffs.append(ManifestFieldDiff(
            key=key, label=label, baseline=str(b) if b is not None else None,
            candidate=str(c) if c is not None else None, changed=(b != c),
        ))
    return diffs


def _explain_confidence_change(change: dict, manifest_diff: list[ManifestFieldDiff]) -> str:
    """Never invents a cause it can't observe -- names only real,
    recorded differences between the two runs' manifests, and falls back
    to an honest 'no observable cause' sentence otherwise."""
    causes = []
    model_field = next((d for d in manifest_diff if d.key == "model_bundle_version"), None)
    if model_field and model_field.changed:
        causes.append(f"the candidate run used a different model bundle "
                       f"({model_field.baseline or 'unknown'} → {model_field.candidate or 'unknown'})")
    if not causes:
        return ("No manifest-level difference was recorded between these runs "
                "that explains this change.")
    return (f"Confidence changed from {change.get('confidence_a')} to {change.get('confidence_b')}. "
            f"The candidate run's manifest differs: {'; '.join(causes)}.")


def get_run_comparison(baseline_id: str, candidate_id: str) -> RunComparison:
    raw = compare_runs(baseline_id, candidate_id)  # raises ValueError -> 404, handled in main.py

    m = raw["manifest"]
    # compare_runs()'s own manifest sub-dict doesn't carry evaluation_metrics
    # (only model/pipeline-version, quality-gate, duration) -- read directly.
    baseline_manifest = get_run_manifest(baseline_id)
    candidate_manifest = get_run_manifest(candidate_id)
    champion_metrics = (baseline_manifest or {}).get("evaluation_metrics") or {}
    candidate_metrics = (candidate_manifest or {}).get("evaluation_metrics") or {}
    metrics_note = None
    if not champion_metrics and not candidate_metrics:
        metrics_note = ("Neither run recorded evaluation metrics. The comparison below "
                         "reflects real content differences only.")

    manifest_diff = _manifest_diff(m)

    g = raw["graph"]
    gp = raw["gaps"]
    p = raw["papers"]
    pr = raw["proposals"]
    e = raw["evidence"]

    promotion = _build_promotion(baseline_id, candidate_id, champion_metrics, candidate_metrics)

    return RunComparison(
        baseline=_run_ref(baseline_id), candidate=_run_ref(candidate_id),
        metrics=_build_metrics(champion_metrics, candidate_metrics), metrics_note=metrics_note,
        papers=DiffSection(key="papers", label="Papers", added=p["added"], removed=p["removed"],
                            common_count=p["common_count"],
                            summary=f"{len(p['added'])} new, {len(p['removed'])} removed"),
        evidence=EvidenceDiff(count_baseline=e["count_a"], count_candidate=e["count_b"], delta=e["delta"]),
        graph=GraphDiff(
            entities_added=g["entities_added"], entities_removed=g["entities_removed"],
            entities_common_count=g["entities_common_count"],
            relationships_added=[list(t) for t in g["relationships_added"]],
            relationships_removed=[list(t) for t in g["relationships_removed"]],
            relationships_common_count=g["relationships_common_count"],
        ),
        gaps=GapDiff(
            added=gp["added"], removed=gp["removed"], common_count=gp["common_count"],
            confidence_changes=[
                ConfidenceChange(
                    title=c["title"], confidence_baseline=c["confidence_a"], confidence_candidate=c["confidence_b"],
                    explanation=_explain_confidence_change(c, manifest_diff),
                ) for c in gp["confidence_changes"]
            ],
        ),
        proposals=DiffSection(key="proposals", label="Proposals", common_count=pr["common_count"],
                               summary=f"{pr['added_count']} new, {pr['removed_count']} removed"),
        manifest_diff=manifest_diff, promotion=promotion,
    )


def _build_promotion(baseline_id: str, candidate_id: str,
                      champion_metrics: dict, candidate_metrics: dict) -> PromotionGateView:
    """evaluate_promotion({}, {}) returns eligible=True VACUOUSLY (nothing
    to regress against) -- since evaluation_metrics is NULL on every
    existing run today, wiring `eligible` straight to the Promote button
    would always show it as ready. can_evaluate is the real gate."""
    can_evaluate = bool(champion_metrics) or bool(candidate_metrics)
    report = evaluate_promotion(champion_metrics, candidate_metrics)

    candidate_artifact_id = f"pipeline:{candidate_id}"
    artifacts = list_artifacts(artifact_type="pipeline")
    if not any(a["artifact_id"] == candidate_artifact_id for a in artifacts):
        candidate_artifact_id = None

    blocking_reasons = list(report["hard_gate_failures"]) + list(report["soft_regressions"])

    if not can_evaluate:
        status = StatusChip(
            code="NOT_EVALUABLE", label="Cannot evaluate", tone="unknown", icon="help-circle",
            reason="Neither run recorded evaluation metrics, so the promotion gate has nothing to "
                   "compare. Run the regression harness (evals/regression/run_champion_challenger.py) "
                   "before promoting.",
        )
    elif report["eligible"]:
        status = StatusChip(code="ELIGIBLE", label="Eligible for promotion", tone="positive",
                             icon="check-circle", reason="No hard-gate failures or soft regressions.")
    else:
        status = StatusChip(code="BLOCKED", label="Not eligible", tone="critical", icon="octagon-x",
                             reason="; ".join(blocking_reasons) or "One or more metrics regressed.")

    return PromotionGateView(
        eligible=report["eligible"], can_evaluate=can_evaluate,
        hard_gate_failures=report["hard_gate_failures"], soft_regressions=report["soft_regressions"],
        warnings=report["warnings"], blocking_reasons=blocking_reasons, status=status,
        promotion_gate_version=report.get("promotion_gate_version"),
        candidate_artifact_id=candidate_artifact_id,
    )
