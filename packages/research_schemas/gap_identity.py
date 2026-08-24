"""
Stable gap identity (Clinova Phase 4, Epic 4.4's Scientific Lineage
plumbing). Before this, no gap dict anywhere in the codebase carried a
stable id (confirmed by a full-repo grep) -- this is the source of truth
for gap_id, imported everywhere a gap is created, same "one schema,
imported everywhere" principle evidence_object.py already states.

gap_id is deliberately content-addressed over only (source, pattern_id,
title, description) -- NOT confidence or validation_status, both of
which are mutated in place AFTER a gap is created
(pipeline/graph_quality.py::apply_graph_quality_to_gaps() rewrites
confidence; pipeline/academic_search.py::validate_gaps() rewrites
validation_status/existing_papers/validation_reasoning). Hashing over a
field that changes mid-run would make gap_id go stale exactly when it's
needed most -- to keep tracing a gap across its own lifecycle. This
matches academic_search.py's own existing gap_hash convention
(title+description only, AD-3).
"""
import hashlib

GAP_IDENTITY_VERSION = 1


def compute_gap_id(source: str, pattern_id: str | None, title: str, description: str) -> str:
    return hashlib.sha256(
        f"{source or ''}:{pattern_id or ''}:{title or ''}:{description or ''}".encode("utf-8")
    ).hexdigest()


def attach_gap_identity(gap: dict, *, evidence_basis: str = "positive_evidence") -> dict:
    """Idempotent: sets gap_id/gap_identity_version/evidence_basis and
    defaults the three motivating_*_ids lists, only when not already
    present -- safe to call more than once on the same gap dict (e.g. if
    a caller re-processes a gap) without recomputing a different id.

    evidence_basis is intrinsic to how the gap was produced (set by the
    producer, never inferred later): "positive_evidence" for gaps derived
    from real Evidence Objects or LLM-cited evidence, "absence_of_evidence"
    for gaps that fire precisely because something is MISSING (e.g. an
    orphan concept, an untested combination, a limitation with no
    keyword match). Conflating the two would make Evidence Coverage
    wrongly penalize a correctly-working absence-based signal for having
    no evidence to cite."""
    if "gap_id" not in gap or not gap["gap_id"]:
        gap["gap_id"] = compute_gap_id(
            gap.get("source"), gap.get("pattern_id"), gap.get("title"), gap.get("description"),
        )
    gap.setdefault("gap_identity_version", GAP_IDENTITY_VERSION)
    gap.setdefault("evidence_basis", evidence_basis)
    gap.setdefault("motivating_evidence_ids", [])
    gap.setdefault("motivating_relationship_ids", [])
    gap.setdefault("motivating_entity_ids", [])
    return gap
