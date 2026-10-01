"""
Evidence screen (Clinova Phase 5, Epic 5.2). Reads results["evidence_objects"]
directly -- a dict keyed by paper filename -> list of Evidence Object dicts
(packages/research_schemas/evidence_object.py's to_dict() shape), the same
real structure evidence_confidence() already reads for the Dashboard tile.
"""
from apps.api.models.common import RunRef
from apps.api.models.evidence import EvidenceItemView, EvidenceView
from apps.api.services.copy_text import no_runs_in_project
from apps.api.services.measures import evidence_confidence
from apps.api.services.project_runs import get_basis


def get_project_evidence(project_id: str, run_id: str | None = None) -> EvidenceView:
    basis = get_basis(project_id, run_id)
    if basis is None:
        return EvidenceView(
            basis_run=None, basis_note="No runs exist for this project yet.", items=[],
            by_type_counts={}, confidence=evidence_confidence({}),
            empty_reason=no_runs_in_project(),
        )

    basis_row, results = basis.row, basis.results

    run = RunRef(run_id=basis_row["id"], name=basis_row["name"], created_at=str(basis_row["created_at"]))
    basis_note = basis.note("Evidence")

    evidence_objects = results.get("evidence_objects") or {}
    items: list[EvidenceItemView] = []
    by_type_counts: dict[str, int] = {}
    for filename, objs in evidence_objects.items():
        for e in objs:
            provenance = e.get("provenance") or {}
            items.append(EvidenceItemView(
                evidence_id=e.get("evidence_id", ""), evidence_type=e.get("evidence_type", "Unknown"),
                paper_filename=e.get("paper_id") or filename, text=e.get("text", ""),
                page=provenance.get("page"), section=provenance.get("section"),
                confidence=e.get("confidence", "low"),
            ))
            t = e.get("evidence_type", "Unknown")
            by_type_counts[t] = by_type_counts.get(t, 0) + 1

    empty_reason = None
    if not items:
        empty_reason = "No evidence objects were extracted for this run."

    return EvidenceView(
        basis_run=run, basis_note=basis_note, items=items, by_type_counts=by_type_counts,
        confidence=evidence_confidence(results), empty_reason=empty_reason,
    )
