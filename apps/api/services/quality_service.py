"""
Data Quality screen (Clinova Phase 5, Epic 5.8).

This screen was deferred twice on the belief that "app.py computes per-paper
completeness as a local variable and never persists it, so there is nothing
to show." Half of that was right and half was wrong: the per-paper FIELD grid
genuinely was thrown away (now fixed -- pipeline/run_pipeline.py persists
`paper_quality_scores`, so runs from this point forward have it), but three
substantial, already-persisted quality datasets were being written on every
run and surfaced nowhere:

  * results["ref_resolution_diagnostics"] -- ADR-007's five-status reference
    trust model with real per-status counts and a duplicate count.
  * results["ref_diagnostics"]["papers"] -- per-paper reference extraction:
    raw entries found, how many the LLM structured, how many DOIs resolved.
  * results["corpus_quality_metrics"] -- present on 2 of the 5 existing runs.

The Corpus screen shows the gate and the funnel as a summary; this screen is
where the funnel's own contradictions are explained rather than smoothed over.
"""
from apps.api.models.common import Measure, RunRef, StatusChip
from apps.api.models.corpus import ReferenceFunnelStage
from apps.api.models.quality import (
    FieldStatus, PaperCompleteness, PaperReferenceDiagnostic, QualityView, TrustStatusCount,
)
from apps.api.services.copy_text import no_runs_in_project
from apps.api.services.corpus_service import _reference_funnel
from apps.api.services.project_runs import get_basis
from apps.api.services.runs_service import _GATE_ICON, _GATE_TONE

# ADR-007's five statuses, in trust order. Each carries what it MEANS --
# "QUARANTINED: 1" is meaningless to a reader who does not already know the
# resolution model, and a screen that shows the number without the definition
# is showing a bare value.
_TRUST_STATUSES = [
    ("VERIFIED", "Verified", "positive", "shield-check",
     "Resolved against an external identifier (DOI, PMID, OpenAlex or Semantic Scholar) — highest trust."),
    ("ACCEPTED", "Accepted", "positive", "check-circle",
     "Matched on normalised title + author + year rather than an identifier — trusted, but by a weaker key."),
    ("QUARANTINED", "Quarantined", "caution", "alert-triangle",
     "Resolved to a candidate the matcher was not confident enough to accept; held back from the trusted corpus."),
    ("UNRESOLVED", "Unresolved", "neutral", "search-x",
     "No external match found at all. Not an error — older and non-indexed references genuinely have none."),
    ("REJECTED", "Rejected", "critical", "octagon-x",
     "Actively refuted by the matcher."),
]

_FIELD_LABELS = {
    "title": "Title", "authors": "Authors", "doi": "DOI", "abstract": "Abstract",
    "introduction": "Introduction", "methodology": "Methodology",
    "dataset_population": "Dataset / Population", "models_interventions": "Models / Interventions",
    "results": "Results", "metrics": "Metrics", "limitations": "Limitations",
    "conclusion": "Conclusion", "future_work": "Future Work", "references": "References",
    "tables": "Tables", "figures": "Figures",
}

_EMPTY_KWARGS = dict(
    quality_gate=None, quality_gate_reasons=[], measures=[], reference_funnel=[],
    trust_statuses=[], per_paper_references=[], per_paper_completeness=[],
)


def _measure(key: str, label: str, value: float | None, basis: str, source: str) -> Measure:
    """A rate Measure. `recorded=False` with a real basis when the value is
    absent -- never a 0.0 standing in for "the engine did not run", which
    would read as a genuine 0% on a screen whose whole subject is honesty
    about extraction quality."""
    if value is None:
        return Measure(key=key, label=label, display="Not recorded", level="Unknown",
                        basis=basis, source=source, recorded=False)
    level = "High" if value >= 0.75 else "Medium" if value >= 0.5 else "Low"
    return Measure(key=key, label=label, value=value, display=f"{value:.0%}", level=level,
                    basis=basis, source=source, recorded=True)


def _funnel_note(funnel: list[ReferenceFunnelStage]) -> str | None:
    """Explains the funnel when it visibly widens instead of narrowing.

    On real runs this reads Detected 114 -> Parsed 0 -> Resolved 72, which
    looks impossible and, drawn as a plain funnel chart, would look like a
    bug in this screen. It is neither: `parsed` counts only entries the LLM
    structured, while the 65 `fallback_parsed` entries the regex parser
    recovered bypass that counter entirely and still go on to resolve. The
    contradiction is real and belongs on screen with its explanation, not
    hidden by quietly reordering the stages.
    """
    by_key = {stage.key: stage.count for stage in funnel}
    parsed, resolved = by_key.get("parsed"), by_key.get("resolved")
    fallback = by_key.get("fallback_parsed", 0)
    if parsed is None or resolved is None or resolved <= parsed:
        return None
    return (
        f"Resolved ({resolved}) exceeds Parsed ({parsed}) because \"Parsed\" counts only the "
        f"references the LLM structured. The {fallback} recovered by the regex fallback parser "
        "are never added to that counter, but they do go on to resolve — so the two stages "
        "count different populations and this funnel is not a strict narrowing."
    )


def _trust_statuses(diag: dict | None) -> tuple[list[TrustStatusCount], str | None, int | None]:
    counts = (diag or {}).get("status_counts")
    if not counts:
        return [], None, None
    rows = [
        TrustStatusCount(
            status=StatusChip(code=code, label=label, tone=tone, icon=icon, reason=meaning),
            count=counts.get(code, 0), recorded=code in counts,
        )
        for code, label, tone, icon, meaning in _TRUST_STATUSES
    ]
    missing = [r.status.label for r in rows if not r.recorded]
    note = None
    if missing:
        note = (
            f"{', '.join(missing)} has no count for this run: the resolver only records a status "
            "it actually assigned, so this is \"never produced\", not \"produced zero times\"."
        )
    return rows, note, (diag or {}).get("duplicates_removed")


def _per_paper_references(diag: dict | None) -> list[PaperReferenceDiagnostic]:
    rows = []
    for p in (diag or {}).get("papers") or []:
        structured = p.get("structured_entries", 0)
        raw = p.get("raw_entries", 0)
        note = None
        if raw and not structured:
            note = ("The LLM structured none of this paper's references; every entry here came "
                    "from the regex fallback parser.")
        rows.append(PaperReferenceDiagnostic(
            filename=p.get("filename", "(unnamed)"), raw_entries=raw,
            structured_entries=structured, combined_entries=p.get("combined_entries", 0),
            dois=p.get("dois", 0), note=note,
        ))
    return rows


def _per_paper_completeness(scores: list[dict] | None) -> list[PaperCompleteness]:
    rows = []
    for s in scores or []:
        fields = [
            FieldStatus(
                field=name, label=_FIELD_LABELS.get(name, name), status=f.get("status", "unknown"),
                confidence=f.get("confidence", "low"), source=f.get("source"), reason=f.get("reason"),
            )
            for name, f in (s.get("fields") or {}).items()
        ]
        # FIELD_CHECKLIST order, not dict order: these round-trip through
        # Postgres JSONB, which does not preserve Python insertion order.
        order = {name: i for i, name in enumerate(_FIELD_LABELS)}
        fields.sort(key=lambda f: order.get(f.field, len(order)))
        rows.append(PaperCompleteness(
            filename=s.get("filename", "(unnamed)"),
            present_count=s.get("present_count", 0),
            total_fields=s.get("total_fields", len(_FIELD_LABELS)),
            achievable_field_count=s.get("achievable_field_count", 0),
            completeness_score=s.get("completeness_score", 0.0),
            achievable_completeness_score=s.get(
                "achievable_completeness_score", s.get("completeness_score", 0.0)),
            fields=fields,
        ))
    return rows


def get_project_quality(project_id: str, run_id: str | None = None) -> QualityView:
    basis = get_basis(project_id, run_id)
    if basis is None:
        return QualityView(
            project_id=project_id, basis_run=None,
            basis_note="No runs exist for this project yet.",
            empty_reason=no_runs_in_project(), **_EMPTY_KWARGS,
        )

    basis_row, results = basis.row, basis.results

    basis_run = RunRef(run_id=basis_row["id"], name=basis_row["name"],
                        created_at=str(basis_row["created_at"]))
    basis_note = (f"Quality figures for run \"{basis_row['name']}\" ({basis_row['id'][:8]}) — "
                   "the most recent run in this project.")

    cqm = results.get("corpus_quality_metrics") or {}
    quality_gate = None
    if cqm.get("quality_gate"):
        value = cqm["quality_gate"]
        quality_gate = StatusChip(
            code=f"CORPUS_{value}", label=f"Quality gate: {value.title()}",
            tone=_GATE_TONE.get(value, "unknown"), icon=_GATE_ICON.get(value, "help-circle"),
            reason="; ".join(cqm.get("quality_gate_reasons") or []) or f"Corpus quality gate: {value}.",
        )

    engine_off = ("The Corpus Quality Engine was not enabled for this run, so nothing measured this.")
    n_papers = cqm.get("n_papers", 0)
    measures = [
        _measure("extraction_completeness", "Extraction Completeness",
                  cqm.get("extraction_completeness"),
                  f"Share of all 16 checklist fields found, averaged over {n_papers} papers. "
                  "5 of the 16 have no extraction path anywhere in the pipeline yet, so this "
                  "figure has a hard ceiling of 69% by construction." if cqm else engine_off,
                  "pipeline/corpus_quality.py::compute_corpus_quality"),
        _measure("achievable_completeness", "Achievable Completeness",
                  cqm.get("achievable_completeness"),
                  "Share of the 11 fields the pipeline can actually extract today. This is what "
                  "the quality gate judges — completeness against all 16 would penalise every "
                  "paper for fields nothing can extract."
                  if cqm else engine_off,
                  "pipeline/corpus_quality.py::ACHIEVABLE_FIELD_COUNT"),
        _measure("doi_resolution_rate", "DOI Resolution Rate", cqm.get("doi_resolution_rate"),
                  "Share of resolved reference records carrying a DOI." if cqm else engine_off,
                  "pipeline/corpus_quality.py::compute_corpus_quality"),
        _measure("abstract_availability", "Abstract Availability", cqm.get("abstract_availability"),
                  "Share of resolved references an abstract could be fetched for — the ceiling on "
                  "how much of the reference corpus is usable as evidence rather than as a title."
                  if cqm else engine_off,
                  "pipeline/corpus_quality.py::compute_corpus_quality"),
    ]

    funnel = _reference_funnel(cqm)
    trust_statuses, trust_note, duplicates = _trust_statuses(
        results.get("ref_resolution_diagnostics"))

    scores = results.get("paper_quality_scores")
    completeness_absent_reason = None
    if not scores:
        completeness_absent_reason = (
            "This run has no per-paper field breakdown. Until Phase 5 Slice 14 the pipeline "
            "computed these scores, used them for the corpus average, and then discarded them "
            "without saving. Runs created from this version onward record them; existing runs "
            "cannot be backfilled, because the breakdown depends on parsed PDF content that is "
            "not retained."
            if cqm else
            "The Corpus Quality Engine was not enabled for this run, so no per-paper field "
            "completeness was scored. Enable it on the New Run screen to record this."
        )

    return QualityView(
        project_id=project_id, basis_run=basis_run, basis_note=basis_note,
        quality_gate=quality_gate,
        quality_gate_reasons=cqm.get("quality_gate_reasons") or [],
        measures=measures, reference_funnel=funnel, funnel_note=_funnel_note(funnel),
        trust_statuses=trust_statuses, trust_note=trust_note, duplicates_removed=duplicates,
        per_paper_references=_per_paper_references(results.get("ref_diagnostics")),
        per_paper_completeness=_per_paper_completeness(scores),
        completeness_absent_reason=completeness_absent_reason,
    )
