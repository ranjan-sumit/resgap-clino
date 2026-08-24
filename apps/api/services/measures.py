"""
Builds the 5 confidence Measures used on both the Project Dashboard and
Run Detail (Clinova Phase 5, Epic 5.1). Every value here traces to a
real, already-computed pipeline output (corpus_quality_metrics,
graph_quality, evidence_objects, gap challenger statuses) -- never a
derived composite that isn't already computed somewhere in the pipeline.
"""
from apps.api.models.common import Measure, StatusChip

try:
    from pipeline.gap_challenger import SEARCH_COVERAGE_THRESHOLD
except ImportError:  # pragma: no cover - defensive only, module always present in practice
    SEARCH_COVERAGE_THRESHOLD = 0.6


def _level(value: float | None) -> str:
    if value is None:
        return "Unknown"
    if value >= 0.75:
        return "High"
    if value >= 0.5:
        return "Medium"
    return "Low"


def _gate_chip(gate: str | None, reasons: list[str] | None) -> StatusChip | None:
    if gate is None:
        return None
    tone_by_gate = {"PASS": "positive", "DEGRADED": "caution", "FAIL": "critical"}
    icon_by_gate = {"PASS": "check-circle", "DEGRADED": "alert-triangle", "FAIL": "octagon-x"}
    return StatusChip(
        code=gate, label=gate.title(), tone=tone_by_gate.get(gate, "unknown"),
        icon=icon_by_gate.get(gate, "help-circle"),
        reason="; ".join(reasons or []) or f"Quality gate: {gate}.",
    )


def corpus_confidence(results: dict) -> Measure:
    m = results.get("corpus_quality_metrics")
    if not m:
        return Measure(
            key="corpus_confidence", label="Corpus Confidence", display="Not recorded",
            level="Unknown", recorded=False,
            basis="The Corpus Quality Engine was not enabled for this run.",
            source="pipeline/corpus_quality.py::compute_corpus_quality",
        )
    value = m.get("achievable_completeness")
    basis = (f"Achievable extraction completeness across {m.get('n_papers', 0)} papers; "
             f"DOI resolution {m.get('doi_resolution_rate', 0):.0%}; "
             f"abstract availability {m.get('abstract_availability', 0):.0%}.")
    if value is None:
        # A real, older run's corpus_quality_metrics predates the
        # achievable_completeness field (see corpus_quality.py's own
        # comment on this fallback) -- honest, not a bug in this run.
        basis += " (This run predates the achievable-completeness field; only the other figures above are real for it.)"
    return Measure(
        key="corpus_confidence", label="Corpus Confidence", value=value,
        display=f"{value:.0%}" if value is not None else "Not recorded",
        level=_level(value), recorded=value is not None,
        basis=basis,
        source="pipeline/corpus_quality.py::compute_corpus_quality",
        status=_gate_chip(m.get("quality_gate"), m.get("quality_gate_reasons")),
    )


def graph_confidence(results: dict) -> Measure:
    g = results.get("graph_quality")
    if not g:
        return Measure(
            key="graph_confidence", label="Graph Confidence", display="Not recorded",
            level="Unknown", recorded=False,
            basis="No knowledge graph was built for this run (quality gate blocked gap analysis).",
            source="pipeline/graph_quality.py::score_graph_quality",
        )
    value = g.get("quality_score")
    build_status = g.get("build_status")
    tone_by_status = {"CLEAN": "positive", "DEGRADED": "caution", "FALLBACK": "critical"}
    icon_by_status = {"CLEAN": "check-circle", "DEGRADED": "alert-triangle", "FALLBACK": "octagon-x"}
    chip = StatusChip(
        code=build_status or "UNKNOWN", label=(build_status or "Unknown").title(),
        tone=tone_by_status.get(build_status, "unknown"),
        icon=icon_by_status.get(build_status, "help-circle"),
        reason=f"Graph build status: {build_status}.",
    ) if build_status else None
    return Measure(
        key="graph_confidence", label="Graph Confidence", value=value,
        display=f"{value:.0%}" if value is not None else "Not recorded",
        level=_level(value), recorded=value is not None,
        basis=(f"{g.get('entity_count', 0)} entities, {g.get('relationship_count', 0)} relationships; "
               f"extraction coverage {g.get('extraction_coverage', 0):.0%}, "
               f"evidence coverage {g.get('evidence_coverage', 0):.0%}, "
               f"duplicate rate {g.get('duplicate_rate', 0):.0%}."),
        source="pipeline/graph_quality.py::score_graph_quality",
        status=chip,
    )


def evidence_confidence(results: dict) -> Measure:
    evidence_objects = results.get("evidence_objects") or {}
    all_evidence = [e for objs in evidence_objects.values() for e in objs]
    n_total = len(all_evidence)
    if n_total == 0:
        return Measure(
            key="evidence_confidence", label="Evidence Confidence", display="Not recorded",
            level="Unknown", recorded=False,
            basis="No evidence objects were extracted for this run.",
            source="pipeline/evidence_extractor.py",
        )
    n_high = sum(1 for e in all_evidence if e.get("confidence") == "high")
    n_medium = sum(1 for e in all_evidence if e.get("confidence") == "medium")
    value = round((n_high + n_medium) / n_total, 3)
    n_papers = len(evidence_objects)
    return Measure(
        key="evidence_confidence", label="Evidence Confidence", value=value,
        display=f"{value:.0%}", level=_level(value), recorded=True,
        basis=(f"{n_high} high and {n_medium} medium confidence evidence objects "
               f"out of {n_total} extracted across {n_papers} papers."),
        source="pipeline/evidence_extractor.py",
    )


def search_coverage_confidence(results: dict) -> Measure:
    gaps = results.get("gaps") or []
    challenged = [g for g in gaps if g.get("challenger_status") is not None]
    if not challenged:
        return Measure(
            key="search_coverage_confidence", label="Search Coverage Confidence", display="Not recorded",
            level="Unknown", recorded=False,
            basis="The Gap Challenger stage was not enabled for this run, so search coverage was never measured.",
            source="pipeline/gap_challenger.py",
        )
    n_insufficient = sum(1 for g in challenged if g.get("challenger_status") == "INSUFFICIENT_EVIDENCE")
    n_resolved = len(challenged) - n_insufficient
    value = round(n_resolved / len(challenged), 3)
    return Measure(
        key="search_coverage_confidence", label="Search Coverage Confidence", value=value,
        display=f"{value:.0%}", level=_level(value), recorded=True,
        basis=(f"{n_resolved} of {len(challenged)} gaps reached a terminal status; "
               f"{n_insufficient} fell below the {SEARCH_COVERAGE_THRESHOLD:.0%} search-coverage threshold."),
        source="pipeline/gap_challenger.py",
    )


def research_confidence(_results: dict) -> Measure:
    """No composite "research confidence" score is computed anywhere in
    this codebase. Ships honestly empty rather than inventing an
    average-of-the-other-four -- the same discipline this project has
    applied all session (token_usage=None rather than 0, a parser
    version of None rather than a guess)."""
    return Measure(
        key="research_confidence", label="Research Confidence", display="Not recorded",
        level="Unknown", recorded=False,
        basis=("No composite research-confidence score is computed by this pipeline. "
               "This tile will become real when an aggregate scoring rule is defined "
               "(07-evaluation-architecture.md)."),
        source="none",
    )


def build_confidence_measures(results: dict) -> list[Measure]:
    return [
        corpus_confidence(results),
        graph_confidence(results),
        evidence_confidence(results),
        search_coverage_confidence(results),
        research_confidence(results),
    ]
