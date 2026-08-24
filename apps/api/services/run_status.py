"""
Derives a run's status as a real StatusChip (Clinova Phase 5, Epic 5.1).

`runs` has no status column and never had one -- confirmed by reading
utils/database.py's save_run() directly (columns: id, name, created_at,
domain, interest, n_papers, n_gaps, n_proposals, has_comp, results_json).
A run's outcome is reconstructed here from three real recorded signals,
in priority order. This function never returns a RUNNING/QUEUED status:
nothing observable from this API is mid-flight (the pipeline executes
inside the Streamlit process), and inventing one would be a fabricated
state.
"""
from apps.api.models.common import StatusChip


def derive_run_status(results: dict | None, manifest: dict | None) -> StatusChip:
    results = results or {}

    if results.get("gate_blocked"):
        reasons = results.get("gate_block_reasons") or []
        return StatusChip(
            code="GATE_BLOCKED", label="Gate blocked", tone="critical", icon="octagon-x",
            reason="; ".join(reasons) or "The quality gate blocked gap analysis for this run.",
        )

    if manifest is None:
        return StatusChip(
            code="NO_MANIFEST", label="No manifest", tone="unknown", icon="help-circle",
            reason="No run manifest was recorded for this run -- it predates the Phase 4 "
                   "manifest (Epic 4.2) or the manifest write failed after the run itself completed.",
        )

    warnings = manifest.get("warnings") or []
    if warnings:
        return StatusChip(
            code="COMPLETED_WITH_WARNINGS", label="Completed with warnings", tone="caution",
            icon="alert-triangle", reason="; ".join(warnings),
        )

    qgr = manifest.get("quality_gate_results") or {}
    corpus_gate = qgr.get("corpus")
    graph_gate = qgr.get("graph")

    degraded_reasons = []
    if corpus_gate == "FAIL":
        degraded_reasons.append("Corpus gate FAIL")
    if graph_gate == "FALLBACK":
        degraded_reasons.append("graph built via fallback extraction")
    if degraded_reasons:
        return StatusChip(
            code="COMPLETED_DEGRADED", label="Completed — degraded quality", tone="caution",
            icon="alert-triangle", reason="; ".join(degraded_reasons),
        )

    if corpus_gate is None and graph_gate is None:
        reason = ("Completed; no quality gates were evaluated for this run "
                  "(Corpus Quality Engine and graph scoring were both disabled).")
    else:
        parts = []
        if corpus_gate:
            parts.append(f"Corpus gate {corpus_gate}")
        if graph_gate:
            parts.append(f"graph {graph_gate}")
        reason = (", ".join(parts) + "; no warnings recorded.") if parts else "No warnings recorded."

    return StatusChip(code="COMPLETED", label="Completed", tone="positive", icon="check-circle", reason=reason)


_TRACE_STATUS = {
    "✅": StatusChip(code="OK", label="Completed", tone="positive", icon="check-circle",
                          reason="Stage completed."),
    "⚠️": StatusChip(code="WARN", label="Warning", tone="caution", icon="alert-triangle",
                                reason="Stage completed with a warning."),
    "❌": StatusChip(code="FAILED", label="Failed", tone="critical", icon="octagon-x",
                          reason="Stage failed."),
}
_UNKNOWN_TRACE_STATUS = StatusChip(
    code="UNKNOWN", label="Unknown", tone="unknown", icon="help-circle",
    reason="No recognized status marker was recorded for this stage.",
)


def trace_status_chip(emoji: str | None) -> StatusChip:
    """Maps app.py's `_add_trace(..., status="✅")` emoji to a real
    StatusChip. An emoji is not text+color+shape (NFR-8) -- it must never
    reach the client as the status itself."""
    return _TRACE_STATUS.get(emoji or "", _UNKNOWN_TRACE_STATUS)
