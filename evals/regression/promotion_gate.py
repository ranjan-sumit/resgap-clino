"""The promotion decision: implements 07-evaluation-architecture.md §3's
exact 3-clause rule for promoting a CANDIDATE pipeline artifact to
CHAMPION. A CANDIDATE is eligible only if (1) False Novelty Rate is no
worse than the current CHAMPION's, (2) no other metric regresses beyond
its tolerance band, and (3) Corpus Contamination is no worse than the
current CHAMPION's. Clauses 1 and 3 are hard gates -- a candidate cannot
buy its way past a hard-gate failure with unrelated gains elsewhere.

Concrete tolerance-band values are explicitly left unset by the
architecture doc ("a Phase 4 tuning exercise... the rule's shape... is
the binding architectural decision") -- the defaults below are a real,
documented judgment call, not a lookup:
  - 0% tolerance on the two named hard gates (matches the rule's literal
    "no worse than" wording).
  - 5% relative tolerance on other quality-style metrics (precision,
    recall, coverage) -- tight enough to catch a real regression, loose
    enough not to fail on noise given today's tiny (n=1-2 case) benchmark
    size.
  - 15% relative tolerance on cost/perf metrics (latency, token usage),
    since the doc explicitly deprioritizes them ("never traded against
    False Novelty Rate") -- they get more slack, never override the hard
    gates.
"""
from utils.database import (
    InvalidArtifactTransitionError,
    get_run_manifest,
    list_artifacts,
    promote_artifact,
)

PROMOTION_GATE_VERSION = 1

HARD_GATE_METRICS = {"false_novelty_rate", "corpus_contamination_rate"}

DEFAULT_TOLERANCE_BANDS = {"_hard_gate": 0.0, "_quality": 0.05, "_cost": 0.15}

METRIC_DIRECTION = {
    "extraction_completeness": "higher",
    "reference_resolution_precision": "higher",
    "reference_recall": "higher",
    "corpus_contamination_rate": "lower",
    "retrieval_recall": "higher",
    "gap_precision": "higher",
    "false_novelty_rate": "lower",
    "contradiction_recall": "higher",
    "evidence_coverage": "higher",
    "consistency_score": "higher",
    "latency_seconds": "lower",
    "token_usage_total": "lower",
}

METRIC_BAND_CLASS = {
    "false_novelty_rate": "_hard_gate",
    "corpus_contamination_rate": "_hard_gate",
    "latency_seconds": "_cost",
    "token_usage_total": "_cost",
}
# Everything else in METRIC_DIRECTION defaults to "_quality".


def _band_class(metric: str) -> str:
    return METRIC_BAND_CLASS.get(metric, "_quality")


def _regressed(champion_value: float, candidate_value: float, direction: str, tolerance: float) -> bool:
    """True if candidate_value is worse than champion_value by more than
    `tolerance` (a relative fraction, e.g. 0.05 = 5%). tolerance=0.0 means
    "no worse than" literally -- any regression at all fails."""
    if direction == "higher":
        threshold = champion_value * (1 - tolerance)
        return candidate_value < threshold
    threshold = champion_value * (1 + tolerance)
    return candidate_value > threshold


def evaluate_promotion(champion_metrics: dict, candidate_metrics: dict,
                        tolerance_bands: dict = None) -> dict:
    """Pure decision function, no I/O. Compares candidate_metrics against
    champion_metrics per §3's 3-clause rule, metric by metric.

    - A metric present on neither side is skipped (nothing to compare,
      non-blocking).
    - A metric present on champion but missing (None) on candidate is
      recorded as a warning, not a failure -- an uninstrumented candidate
      metric cannot be silently treated as a pass, but this harness also
      can't fabricate a comparison it has no data for. A human reviewing
      `warnings` decides whether that's acceptable for this promotion.
    - A metric present on candidate but missing on champion (the
      bootstrap case, or champion simply never measured it) has nothing
      to regress against -- treated as an automatic pass for that metric.

    Returns {eligible, hard_gate_failures, soft_regressions, warnings,
    metric_results, promotion_gate_version}.
    """
    bands = {**DEFAULT_TOLERANCE_BANDS, **(tolerance_bands or {})}
    hard_gate_failures, soft_regressions, warnings, metric_results = [], [], [], []

    all_metrics = set(champion_metrics) | set(candidate_metrics)
    all_metrics &= set(METRIC_DIRECTION)  # ignore any unrecognized keys

    for metric in sorted(all_metrics):
        champion_value = champion_metrics.get(metric)
        candidate_value = candidate_metrics.get(metric)
        direction = METRIC_DIRECTION[metric]
        band_class = _band_class(metric)
        tolerance = bands[band_class]

        if champion_value is None and candidate_value is None:
            continue

        if champion_value is None:
            metric_results.append({
                "metric": metric, "champion": None, "candidate": candidate_value,
                "direction": direction, "delta_pct": None, "tolerance": tolerance,
                "verdict": "no_champion_baseline",
            })
            continue

        if candidate_value is None:
            warnings.append(f"{metric}: candidate has no value to compare against champion={champion_value}")
            metric_results.append({
                "metric": metric, "champion": champion_value, "candidate": None,
                "direction": direction, "delta_pct": None, "tolerance": tolerance,
                "verdict": "candidate_not_measured",
            })
            continue

        delta_pct = (
            (candidate_value - champion_value) / champion_value if champion_value else None
        )
        regressed = _regressed(champion_value, candidate_value, direction, tolerance)
        verdict = "regressed" if regressed else "ok"
        metric_results.append({
            "metric": metric, "champion": champion_value, "candidate": candidate_value,
            "direction": direction, "delta_pct": round(delta_pct, 4) if delta_pct is not None else None,
            "tolerance": tolerance, "verdict": verdict,
        })

        if regressed:
            if metric in HARD_GATE_METRICS:
                hard_gate_failures.append(metric)
            else:
                soft_regressions.append(metric)

    eligible = not hard_gate_failures and not soft_regressions

    return {
        "eligible": eligible,
        "hard_gate_failures": hard_gate_failures,
        "soft_regressions": soft_regressions,
        "warnings": warnings,
        "metric_results": metric_results,
        "promotion_gate_version": PROMOTION_GATE_VERSION,
    }


def _current_champion_metrics(artifact_type: str, project_id: str) -> tuple[str | None, dict]:
    """Looks up the current CHAMPION of (artifact_type, project_id) and
    its evaluation_metrics from the Run Manifest, if any. Returns
    (champion_artifact_id, metrics_dict) -- metrics_dict is {} (not None)
    when there is no champion, so evaluate_promotion() correctly treats
    every metric as "no champion baseline" (auto-pass, bootstrap case)."""
    champions = list_artifacts(artifact_type=artifact_type, project_id=project_id, status="CHAMPION")
    if not champions:
        return None, {}
    champion = champions[0]
    run_id = champion.get("run_id")
    if not run_id:
        return champion["artifact_id"], {}
    manifest = get_run_manifest(run_id)
    if not manifest or not manifest.get("evaluation_metrics"):
        return champion["artifact_id"], {}
    return champion["artifact_id"], manifest["evaluation_metrics"]


def evaluate_and_promote(candidate_artifact_id: str, artifact_type: str, project_id: str,
                          candidate_metrics: dict, champion_metrics: dict = None) -> dict:
    """I/O wrapper around evaluate_promotion(). Looks up the current
    CHAMPION of (artifact_type, project_id) via list_artifacts() if
    champion_metrics isn't supplied directly. Bootstrap case (no existing
    champion): the candidate is auto-eligible, since a hard "no worse
    than" rule is vacuously true against nothing.

    On eligible=True: archives the previous champion, then promotes the
    candidate -- both through the existing promote_artifact() state
    machine, so an illegal-transition bug still raises
    InvalidArtifactTransitionError rather than silently corrupting state.
    On eligible=False: the candidate artifact is left untouched at its
    current status (never force-demoted); the full report is returned for
    the caller to surface/log.

    Returns evaluate_promotion()'s report plus {promoted: bool,
    champion_artifact_id, archived_previous_champion: bool}.
    """
    if champion_metrics is None:
        champion_artifact_id, champion_metrics = _current_champion_metrics(artifact_type, project_id)
    else:
        champion_artifact_id, _ = _current_champion_metrics(artifact_type, project_id)

    report = evaluate_promotion(champion_metrics, candidate_metrics)
    report["promoted"] = False
    report["champion_artifact_id"] = champion_artifact_id
    report["archived_previous_champion"] = False

    if not report["eligible"]:
        return report

    if champion_artifact_id and champion_artifact_id != candidate_artifact_id:
        try:
            promote_artifact(champion_artifact_id, "ARCHIVED")
            report["archived_previous_champion"] = True
        except InvalidArtifactTransitionError:
            pass  # already archived or otherwise not eligible for that transition; not fatal to the new promotion

    promote_artifact(candidate_artifact_id, "CHAMPION")
    report["promoted"] = True
    return report


def mark_candidate_if_evaluated(artifact_id: str, metrics: dict) -> dict:
    """The EXPERIMENTAL -> CANDIDATE gate:
    06-versioning-lineage-architecture.md §2's "CANDIDATE -- passed the
    evaluation harness." Interpreted as a deliberately low, mechanical
    bar -- did the harness actually run and produce at least one real
    metric value -- distinct from and easier than the CHAMPION gate's
    threshold comparison in evaluate_and_promote().

    Returns {promoted: bool, reason: str}. Does not raise on an already-
    non-EXPERIMENTAL artifact; that's surfaced via `reason` instead, since
    calling this twice (e.g. a re-run harness) should be a no-op, not an
    error.
    """
    has_real_metric = any(v is not None for v in metrics.values())
    if not has_real_metric:
        return {"promoted": False, "reason": "harness produced no real metric values"}
    try:
        promote_artifact(artifact_id, "CANDIDATE")
        return {"promoted": True, "reason": "harness produced at least one real metric value"}
    except InvalidArtifactTransitionError as exc:
        return {"promoted": False, "reason": str(exc)}
