"""
Corpus Quality Engine (Clinova Phase 1, Epic 1.2): scores each paper's
extraction completeness against the 05-data-architecture.md §4 scientific
field checklist, aggregates the corpus-level reference-resolution funnel
(§7), and enforces a PASS/DEGRADED/FAIL quality gate before gap analysis
is allowed to proceed (PRD FR-2/FR-3).

Honest by construction: a field with no extraction path anywhere in the
pipeline today (authors, abstract, introduction, metrics, conclusion --
neither pipeline/wiki_compiler.py's schema nor pipeline/
extraction_reconciler.py's current scope produce these) is scored
`not_extracted`, distinct from a field that was attempted and came back
empty (`empty`) or genuinely found (`present`). Collapsing "no extraction
path exists" into the same signal as "extraction found nothing" would
itself be exactly the kind of silent information loss this engine exists
to detect (Problem A).
"""
from datetime import datetime, timezone

# The 16-field scientific checklist, 05-data-architecture.md §4.
FIELD_CHECKLIST = [
    "title", "authors", "doi", "abstract", "introduction", "methodology",
    "dataset_population", "models_interventions", "results", "metrics",
    "limitations", "conclusion", "future_work", "references", "tables", "figures",
]

# Fields with genuinely no extraction path anywhere in the pipeline today --
# always "not_extracted", not paper-specific. Revisit as Phase 2's Evidence
# Objects (05-data-architecture.md §8) add real extraction for these.
_NOT_YET_EXTRACTED_ANYWHERE = ("authors", "abstract", "introduction", "metrics", "conclusion")

# Design fix, 2026-08-21: the quality gate must not penalize a paper for
# fields NOTHING in the pipeline can extract yet -- with 5 of 16 fields in
# _NOT_YET_EXTRACTED_ANYWHERE, no paper could ever score above 11/16=68.75%
# under the raw formula, no matter how completely it was actually
# extracted. Real corpus runs this session scored 44-56% raw, which reads
# as "badly extracted" when the true picture is "extracted everything
# currently extractable, pipeline just doesn't reach 5 fields yet." The
# gate now evaluates against the ACHIEVABLE ceiling (present_count /
# achievable_field_count); score_paper_completeness() still reports the
# raw completeness_score (present_count / 16) unchanged, for honest
# transparency about the pipeline's overall real coverage -- this fix
# changes what the GATE judges a paper against, not what is reported.
ACHIEVABLE_FIELD_COUNT = len(FIELD_CHECKLIST) - len(_NOT_YET_EXTRACTED_ANYWHERE)

# Tuning parameters -- initial values, calibrated against the Clinova
# Benchmark during Phase 1 per 05-data-architecture.md §7's own note that
# concrete thresholds are a Phase 1 tuning exercise, not fixed in planning.
# Now applied to achievable_completeness_score, not raw completeness_score.
QUALITY_GATE_FAIL_THRESHOLD = 0.35
QUALITY_GATE_PASS_THRESHOLD = 0.60
DOI_RESOLUTION_LOW_THRESHOLD = 0.30


class QualityGateBlockedError(Exception):
    """Raised by enforce_quality_gate() when the corpus quality gate is
    FAIL and no override was given -- gap-analysis stages must not run
    against a FAIL-gated corpus silently (PRD FR-3)."""
    def __init__(self, message: str, reasons: list[str], metrics: dict):
        super().__init__(message)
        self.reasons = reasons
        self.metrics = metrics


def _list_field_status(value) -> dict:
    if value is None:
        return {"status": "not_extracted", "confidence": "low"}
    if isinstance(value, (list, str)) and len(value) == 0:
        return {"status": "empty", "confidence": "low"}
    return {"status": "present", "confidence": "medium", "source": "wiki_compiler (LLM)"}


def score_paper_completeness(reconciled: dict, wiki_page: dict,
                              ref_count: int = 0, has_figures: bool = False) -> dict:
    """Score one paper's extraction completeness against FIELD_CHECKLIST.

    `reconciled` is pipeline.extraction_reconciler.reconcile_paper()'s
    output; `wiki_page` is one entry of wiki["pages"] from
    pipeline.wiki_compiler.build_wiki()."""
    fields = {}

    for name in _NOT_YET_EXTRACTED_ANYWHERE:
        fields[name] = {"status": "not_extracted", "confidence": "low",
                         "reason": "no extraction path exists yet for this field"}

    # title -- wiki_compiler falls back to the raw filename on LLM failure;
    # that fallback must not be counted as a genuine title extraction.
    title = wiki_page.get("title")
    filename = wiki_page.get("source_file") or wiki_page.get("filename")
    if not title or (filename and title == filename):
        fields["title"] = {"status": "not_extracted", "confidence": "low"}
    else:
        fields["title"] = {"status": "present", "confidence": "medium", "source": "wiki_compiler (LLM)"}

    # doi -- deterministic, from Story 1.1.3's reconciler
    doi_field = (reconciled or {}).get("fields", {}).get("doi", {})
    doi_value = doi_field.get("value")
    fields["doi"] = {
        "status": "present" if doi_value else "empty",
        "confidence": doi_field.get("confidence", "low"),
        "source": doi_field.get("source", "none"),
    }

    fields["methodology"] = _list_field_status(wiki_page.get("methods"))
    fields["dataset_population"] = _list_field_status(wiki_page.get("datasets"))
    fields["results"] = _list_field_status(wiki_page.get("key_findings"))
    fields["limitations"] = _list_field_status(wiki_page.get("limitations"))
    fields["future_work"] = _list_field_status(wiki_page.get("future_work"))

    # models_interventions -- overlaps wiki.methods/contributions but has
    # no distinct field in the current wiki schema. Honest signal, distinct
    # from the always-missing set: a future wiki schema change could close
    # this without needing a new extraction path entirely.
    fields["models_interventions"] = {
        "status": "not_extracted", "confidence": "low",
        "reason": "overlaps wiki.methods/contributions but has no distinct field",
    }

    fields["references"] = {
        "status": "present" if ref_count > 0 else "empty",
        "confidence": "medium" if ref_count > 0 else "low",
    }

    tables_field = (reconciled or {}).get("fields", {}).get("tables", {})
    tables_value = tables_field.get("value") or []
    fields["tables"] = {
        "status": "present" if tables_value else "empty",
        "confidence": tables_field.get("confidence", "low"),
        "source": tables_field.get("source", "none"),
    }

    fields["figures"] = {
        "status": "present" if has_figures else "empty",
        "confidence": "medium" if has_figures else "low",
    }

    present_count = sum(1 for f in fields.values() if f["status"] == "present")
    completeness_score = present_count / len(FIELD_CHECKLIST)
    achievable_score = present_count / ACHIEVABLE_FIELD_COUNT if ACHIEVABLE_FIELD_COUNT else 0.0

    return {
        "fields": fields,
        "present_count": present_count,
        "total_fields": len(FIELD_CHECKLIST),
        "achievable_field_count": ACHIEVABLE_FIELD_COUNT,
        "completeness_score": round(completeness_score, 3),
        "achievable_completeness_score": round(min(achievable_score, 1.0), 3),
    }


def _evaluate_quality_gate(achievable_completeness: float, doi_resolution_rate: float) -> dict:
    """Gates on achievable_completeness (present_count / ACHIEVABLE_FIELD_COUNT)
    -- what fraction of the fields the pipeline is CAPABLE of extracting
    today were actually found -- not raw completeness (present_count / 16),
    which would unfairly penalize every paper for 5 fields nothing extracts
    yet regardless of how well-extracted the paper actually was."""
    reasons = []
    if achievable_completeness < QUALITY_GATE_FAIL_THRESHOLD:
        reasons.append(
            f"achievable extraction completeness {achievable_completeness:.0%} is below the "
            f"FAIL threshold ({QUALITY_GATE_FAIL_THRESHOLD:.0%})"
        )
        return {"status": "FAIL", "reasons": reasons}
    if achievable_completeness < QUALITY_GATE_PASS_THRESHOLD:
        reasons.append(
            f"achievable extraction completeness {achievable_completeness:.0%} is below the "
            f"PASS threshold ({QUALITY_GATE_PASS_THRESHOLD:.0%})"
        )
    if doi_resolution_rate < DOI_RESOLUTION_LOW_THRESHOLD:
        reasons.append(f"DOI resolution rate {doi_resolution_rate:.0%} is low")
    return {"status": "PASS" if not reasons else "DEGRADED", "reasons": reasons}


def compute_corpus_quality(paper_scores: list[dict], ref_diagnostics: dict,
                            ref_papers: list[dict] | None = None) -> dict:
    """Corpus Quality Engine (05-data-architecture.md §7): aggregates
    per-paper completeness scores and the reference-resolution funnel into
    one structured result, computed before gap analysis is allowed to
    proceed.

    `ref_papers` is the actual resolved reference record list (pipeline.
    reference_extractor.extract_and_enrich_references()'s return value) --
    required to compute a real DOI resolution rate. `ref_diagnostics`'s own
    `doi_entries` field counts something different (raw DOI-pattern matches
    found via regex that weren't already captured by LLM structuring, added
    on top of `structured_entries` during combined-list construction --
    see pipeline/reference_extractor.py's extract_and_enrich_references)
    and is NOT a subset of `structured_entries`; dividing the two produced
    a rate greater than 1.0 when first validated against real data
    (Data-17072026/, 2026-08-21) -- caught before this shipped."""
    n_papers = len(paper_scores)
    avg_completeness = (
        sum(p["completeness_score"] for p in paper_scores) / n_papers if n_papers else 0.0
    )
    # Gate on the achievable ceiling, not raw completeness -- see the
    # ACHIEVABLE_FIELD_COUNT note above. Falls back to raw completeness for
    # any paper_scores entry computed before this fix shipped (missing the
    # new key), so old cached/replayed scores don't crash.
    avg_achievable = (
        sum(p.get("achievable_completeness_score", p["completeness_score"]) for p in paper_scores) / n_papers
        if n_papers else 0.0
    )

    d = ref_diagnostics or {}
    raw_entries = d.get("raw_entries", 0)
    structured_entries = d.get("structured_entries", 0)
    fallback_entries = d.get("fallback_entries", 0)
    enriched = d.get("enriched", 0)
    title_only = d.get("title_only", 0)
    duplicates_skipped = d.get("duplicates_skipped", 0)
    resolved = enriched + title_only

    reference_funnel = {
        "detected": raw_entries,
        "parsed": structured_entries,
        "resolved": resolved,
        "unresolved": max(structured_entries - resolved, 0),
        # "quarantined" doesn't exist as a real status yet -- Epic 1.3's
        # resolution status model introduces VERIFIED/ACCEPTED/QUARANTINED/
        # UNRESOLVED/REJECTED. 0 here is honest (nothing is being screened
        # for that status yet), not a claim the corpus is fully trustworthy.
        "quarantined": 0,
        "duplicates_merged_in_run": duplicates_skipped,
        "fallback_parsed": fallback_entries,
    }

    refs = ref_papers or []
    doi_resolution_rate = (
        round(sum(1 for r in refs if r.get("doi")) / len(refs), 3) if refs else 0.0
    )
    abstract_availability = round(enriched / resolved, 3) if resolved else 0.0

    gate = _evaluate_quality_gate(avg_achievable, doi_resolution_rate)

    return {
        "extraction_completeness": round(avg_completeness, 3),
        "achievable_completeness": round(avg_achievable, 3),
        "reference_funnel": reference_funnel,
        "doi_resolution_rate": doi_resolution_rate,
        "abstract_availability": abstract_availability,
        "n_papers": n_papers,
        "quality_gate": gate["status"],
        "quality_gate_reasons": gate["reasons"],
    }


def enforce_quality_gate(metrics: dict, override: bool = False,
                          override_reason: str = "", override_by: str = "unknown") -> dict:
    """Blocks downstream gap-analysis stages by default when the quality
    gate is FAIL (Story 1.2.3). An explicit override is allowed but is
    logged (who/when/why is recorded on the returned metrics) rather than
    silently bypassing the gate -- and DEGRADED provenance is preserved
    either way for any generated report to surface."""
    gate = metrics.get("quality_gate")

    if gate == "FAIL" and not override:
        reasons = metrics.get("quality_gate_reasons", [])
        raise QualityGateBlockedError(
            f"Corpus quality gate is FAIL: {'; '.join(reasons)}. "
            "Pass override=True with an override_reason to proceed anyway.",
            reasons=reasons,
            metrics=metrics,
        )

    result = dict(metrics)
    if gate == "FAIL" and override:
        result["gate_override"] = {
            "applied": True,
            "reason": override_reason or "(no reason given)",
            "by": override_by,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    return result
