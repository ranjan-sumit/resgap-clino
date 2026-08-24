"""
Corpus screen (Clinova Phase 5, Epic 5.2). Shows the project's basis run's
papers plus the real, persisted corpus_quality_metrics aggregate -- per-paper
completeness breakdowns are NOT persisted anywhere (app.py computes them as a
local variable, never saves them to `results`), so this honestly cannot show
a per-paper completeness table -- only the real aggregate that IS saved.
"""
from apps.api.models.common import RunRef, StatusChip
from apps.api.models.corpus import CorpusView, ReferenceFunnelStage
from apps.api.models.runs import PaperRef
from apps.api.services.measures import corpus_confidence
from apps.api.services.project_runs import get_basis_run
from apps.api.services.runs_service import _GATE_ICON, _GATE_TONE

# Fixed display order -- pipeline/corpus_quality.py's own dict literal order,
# restated explicitly because a value round-tripped through Postgres JSONB
# does not preserve Python dict insertion order (a real JSONB characteristic,
# not a bug) -- the funnel stages would otherwise render in an arbitrary,
# reshuffled order every time.
_FUNNEL_STAGE_LABELS = [
    ("detected", "Detected"), ("parsed", "Parsed"), ("resolved", "Resolved"),
    ("unresolved", "Unresolved"), ("quarantined", "Quarantined"),
    ("duplicates_merged_in_run", "Duplicates Merged"), ("fallback_parsed", "Fallback Parsed"),
]


def _reference_funnel(cqm: dict | None) -> list[ReferenceFunnelStage]:
    funnel = (cqm or {}).get("reference_funnel") or {}
    return [
        ReferenceFunnelStage(key=key, label=label, count=funnel.get(key, 0))
        for key, label in _FUNNEL_STAGE_LABELS if key in funnel
    ]


def get_project_corpus(project_id: str) -> CorpusView:
    basis_row, results = get_basis_run(project_id)
    if basis_row is None:
        return CorpusView(
            project_id=project_id, basis_run=None, basis_note="No runs exist for this project yet.",
            papers=[], corpus_confidence=corpus_confidence({}), quality_gate=None,
            quality_gate_reasons=[], reference_funnel=[], doi_resolution_rate=None,
            abstract_availability=None,
            empty_reason="No runs in this project yet. Runs created in the Streamlit "
                          "workspace appear here automatically.",
        )

    basis_run = RunRef(run_id=basis_row["id"], name=basis_row["name"], created_at=str(basis_row["created_at"]))
    basis_note = f"Corpus reflects run \"{basis_row['name']}\" ({basis_row['id'][:8]}) — the most recent run in this project."

    papers = [
        PaperRef(filename=p.get("filename", ""), title=(p.get("wiki") or {}).get("title"),
                  char_count=p.get("char_count", 0))
        for p in results.get("papers") or []
    ]

    cqm = results.get("corpus_quality_metrics")
    quality_gate = None
    if cqm and cqm.get("quality_gate"):
        value = cqm["quality_gate"]
        quality_gate = StatusChip(
            code=f"CORPUS_{value}", label=f"Quality gate: {value.title()}",
            tone=_GATE_TONE.get(value, "unknown"), icon=_GATE_ICON.get(value, "help-circle"),
            reason="; ".join(cqm.get("quality_gate_reasons") or []) or f"Corpus quality gate: {value}.",
        )

    return CorpusView(
        project_id=project_id, basis_run=basis_run, basis_note=basis_note, papers=papers,
        corpus_confidence=corpus_confidence(results), quality_gate=quality_gate,
        quality_gate_reasons=(cqm or {}).get("quality_gate_reasons") or [],
        reference_funnel=_reference_funnel(cqm),
        doi_resolution_rate=(cqm or {}).get("doi_resolution_rate"),
        abstract_availability=(cqm or {}).get("abstract_availability"),
    )
