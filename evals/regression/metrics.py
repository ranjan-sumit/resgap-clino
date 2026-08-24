"""Real, benchmark-derived metric computations for Epic 4.3's Champion/
Challenger harness (07-evaluation-architecture.md §1/§3). All 12 named
metrics are now computed: the 2 hard gates (False Novelty Rate, Corpus
Contamination Rate) plus Consistency from the first slice; Latency,
Extraction Completeness, Reference Resolution Precision/Recall, and
Evidence Coverage from Bucket A; Gap Precision, Contradiction Recall, and
Retrieval Recall from Bucket C's 3 new real, cited v2 cases. Still
deferred: full 10-case-type benchmark coverage and v1/v2/v3 fixture
unification -- separate, standalone work per the epic's own scope note.
"""
import glob
import importlib.util
import json
import os
import sys

from pipeline.canonical_resolver import filter_and_dedupe_references, merge_canonical_references
from pipeline.corpus_quality import score_paper_completeness
from pipeline.repeatability_score import compute_repeatability_score
from utils.database import get_run_manifest, load_run

from evals.regression.case_registry import CASE_TYPE_INDEX, cases_feeding

_V2_DIR = os.path.join(os.path.dirname(__file__), "..", "benchmarks", "v2")
_V1_DIR = os.path.join(os.path.dirname(__file__), "..", "benchmarks", "v1")

_LOW_N_THRESHOLD = 5
# Below this many evaluated cases, a computed rate is real but not yet
# statistically meaningful -- flagged, not hidden, per
# 07-evaluation-architecture.md §3's own anticipation of this ("Concrete
# tolerance-band values are a Phase 4 tuning exercise (calibrated once the
# benchmark has enough real cases to be statistically meaningful)").


def _load_v2_run_case():
    """Imports evals/benchmarks/v2/run_gap_challenger_benchmark.py's
    run_case() by path (that directory isn't a package -- no __init__.py,
    matching evals/benchmarks/'s existing "run by hand" scripts convention)
    rather than duplicating its logic."""
    path = os.path.join(_V2_DIR, "run_gap_challenger_benchmark.py")
    spec = importlib.util.spec_from_file_location("_v2_benchmark_runner", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_v2_benchmark_runner", module)
    spec.loader.exec_module(module)
    return module.run_case


def compute_false_novelty_rate(client, ss_api_key: str = "") -> dict:
    """§1: proportion of gaps reported as novel that the benchmark's
    known-closed-gap set proves are already addressed. Runs every v2 case
    whose ground_truth_status_class == 'closed_leaning' through the real
    Gap Challenger (live NVIDIA + Semantic Scholar calls -- no mocks).

    A case is a miss (false novelty) if run_case()'s verdict is a FAIL
    (challenger returned OPEN/PARTIALLY_OPEN when ground truth says
    closed). INSUFFICIENT_EVIDENCE ("INCONCLUSIVE" verdict) is excluded
    from both numerator and denominator -- a search-coverage shortfall
    this run is not a judgment miss, per the case runner's own verdict
    convention.
    """
    run_case = _load_v2_run_case()
    entries = cases_feeding("false_novelty_rate")
    case_results = []
    n_misses = 0
    n_inconclusive = 0

    for _version, _case_id, filename in entries:
        case_path = os.path.join(_V2_DIR, filename)
        result = run_case(case_path, client, ss_api_key=ss_api_key)
        case_results.append(result)
        if result["verdict"].startswith("FAIL"):
            n_misses += 1
        elif result["verdict"].startswith("INCONCLUSIVE"):
            n_inconclusive += 1

    n_evaluated = len(case_results) - n_inconclusive
    rate = (n_misses / n_evaluated) if n_evaluated > 0 else None

    return {
        "false_novelty_rate": rate,
        "n_cases_evaluated": n_evaluated,
        "n_misses": n_misses,
        "n_inconclusive": n_inconclusive,
        "case_results": case_results,
        "low_n_warning": n_evaluated < _LOW_N_THRESHOLD,
    }


_GAP_PRECISION_GROUND_TRUTH = {
    # ground_truth_status_class -> is this gap genuinely novel?
    "open_leaning": True,   # known-open case: a real, currently-unaddressed question
    "fabricated": False,    # a constructed, literature-unsupported claim
}
_REPORTED_AS_GAP_STATUSES = {"OPEN", "PARTIALLY_OPEN", "CONTESTED"}


def compute_gap_precision(client, ss_api_key: str = "") -> dict:
    """§3: fraction of *reported* gaps that are genuinely novel per the
    benchmark's ground truth. Reuses the v2 cases feeding "gap_precision"
    (the known-open case + Bucket C's fabricated-gap case) -- a case
    counts as "reported" if the Gap Challenger's terminal status is one
    the product would actually surface to a researcher as live/actionable
    (OPEN/PARTIALLY_OPEN/CONTESTED); INSUFFICIENT_EVIDENCE is excluded
    (a search-coverage shortfall, not a reported gap). Real live NVIDIA +
    Semantic Scholar calls -- no mocks.
    """
    run_case = _load_v2_run_case()
    entries = cases_feeding("gap_precision")
    case_results = []
    n_reported = 0
    n_reported_and_genuine = 0
    n_inconclusive = 0

    for _version, _case_id, filename in entries:
        case_path = os.path.join(_V2_DIR, filename)
        with open(case_path, encoding="utf-8") as f:
            case = json.load(f)
        result = run_case(case_path, client, ss_api_key=ss_api_key)
        status = result["actual_status"]
        if status == "INSUFFICIENT_EVIDENCE":
            n_inconclusive += 1
            case_results.append({**result, "reported": False, "genuine": None})
            continue
        reported = status in _REPORTED_AS_GAP_STATUSES
        genuine = _GAP_PRECISION_GROUND_TRUTH.get(case["ground_truth_status_class"])
        if reported:
            n_reported += 1
            if genuine:
                n_reported_and_genuine += 1
        case_results.append({**result, "reported": reported, "genuine": genuine})

    precision = (n_reported_and_genuine / n_reported) if n_reported > 0 else None

    return {
        "gap_precision": round(precision, 3) if precision is not None else None,
        "n_cases_evaluated": len(entries) - n_inconclusive,
        "n_reported": n_reported,
        "n_reported_and_genuine": n_reported_and_genuine,
        "n_inconclusive": n_inconclusive,
        "case_results": case_results,
        "low_n_warning": (len(entries) - n_inconclusive) < _LOW_N_THRESHOLD,
    }


def _normalize_title(text) -> str:
    import re
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def compute_contradiction_recall(client, ss_api_key: str = "") -> dict:
    """§3: contradiction_recall (does the Gap Challenger correctly flag
    genuinely-disagreeing real papers) and, as a byproduct,
    retrieval_recall (did the search funnel even surface the known-
    relevant papers in the first place -- a real, separate failure mode
    from judgment, per the B27 lesson: a retrieval miss must never be
    reported as a judgment miss).

    Uses Bucket C's real, DOI-verified contradictory-pair case. Recall is
    computed only over PAIRS THAT WERE ACTUALLY RETRIEVED -- an
    un-retrieved pair is reported separately (n_not_retrieved), not
    silently folded into a lower recall number that would misattribute a
    retrieval failure to the judgment stage.
    """
    run_case = _load_v2_run_case()
    entries = cases_feeding("contradiction_recall")
    case_results = []
    n_pairs_total = 0
    n_pairs_retrieved = 0
    n_pairs_flagged = 0

    for _version, _case_id, filename in entries:
        case_path = os.path.join(_V2_DIR, filename)
        with open(case_path, encoding="utf-8") as f:
            case = json.load(f)
        result = run_case(case_path, client, ss_api_key=ss_api_key)
        funnel = result.get("funnel") or {}
        judged = funnel.get("judged_candidates", []) or []
        judged_titles = {_normalize_title(c.get("title")) for c in judged}

        pair = case.get("known_contradicting_pair", [])
        n_pairs_total += 1
        pair_titles = [_normalize_title(p.get("title")) for p in pair]
        retrieved = all(t in judged_titles for t in pair_titles) if pair_titles else False

        flagged = False
        if retrieved:
            n_pairs_retrieved += 1
            flagged = result["actual_status"] == "CONTESTED" and any(
                c.get("contradicts_gap") for c in judged
            )
            if flagged:
                n_pairs_flagged += 1

        case_results.append({**result, "retrieved": retrieved, "flagged": flagged})

    n_not_retrieved = n_pairs_total - n_pairs_retrieved
    contradiction_recall = (n_pairs_flagged / n_pairs_retrieved) if n_pairs_retrieved > 0 else None
    retrieval_recall = (n_pairs_retrieved / n_pairs_total) if n_pairs_total > 0 else None

    return {
        "contradiction_recall": round(contradiction_recall, 3) if contradiction_recall is not None else None,
        "retrieval_recall": round(retrieval_recall, 3) if retrieval_recall is not None else None,
        "n_pairs_total": n_pairs_total,
        "n_pairs_retrieved": n_pairs_retrieved,
        "n_pairs_flagged": n_pairs_flagged,
        "n_not_retrieved": n_not_retrieved,
        "case_results": case_results,
        "low_n_warning": n_pairs_total < _LOW_N_THRESHOLD,
    }


def compute_corpus_contamination_rate() -> dict:
    """Corpus Contamination: rate of unrelated papers incorrectly
    retained. Runs each contamination-type v1 case's fixture_references
    through pipeline.canonical_resolver.filter_and_dedupe_references()
    (pure, no API calls) and checks whether the known off-topic DOI
    survives into the trusted output.

    Known, honest limitation (documented, not hidden): canonical_resolver
    does not do relevance/off-topic filtering by design (its own
    docstring: "a real, valid DOI still resolves VERIFIED even if the
    paper it points to is off-topic"). This metric will therefore report
    the SAME "contaminated" result for any pipeline/model version compared
    this pass -- it is a real, mechanically-computed metric, just not yet
    a discriminating one. The promotion rule's "no worse than" wording
    means a tie against an equally-bad champion correctly passes rather
    than permanently blocking every promotion on a metric nothing can
    move yet.
    """
    case_entries = cases_feeding("corpus_contamination_rate")
    case_results = []
    n_retained = 0

    for version, case_id, filename in case_entries:
        case_dir = _V1_DIR if version == "v1" else _V2_DIR
        case_path = os.path.join(case_dir, filename)
        with open(case_path, encoding="utf-8") as f:
            case = json.load(f)

        contaminated_doi = CASE_TYPE_INDEX[version][case_id]["contaminated_doi"]
        trusted, diagnostics = filter_and_dedupe_references(case["fixture_references"])
        retained = any(
            str(ref.get("doi", "")).strip().lower() == contaminated_doi.lower()
            for ref in trusted
        )
        if retained:
            n_retained += 1
        case_results.append({
            "case_id": case_id,
            "contaminated_doi": contaminated_doi,
            "retained": retained,
            "diagnostics": diagnostics,
        })

    n_evaluated = len(case_results)
    rate = (n_retained / n_evaluated) if n_evaluated > 0 else None

    return {
        "corpus_contamination_rate": rate,
        "n_cases_evaluated": n_evaluated,
        "n_retained_contaminated": n_retained,
        "case_results": case_results,
        "known_limitation_note": (
            "canonical_resolver.py does not perform relevance/off-topic "
            "filtering by design -- this metric cannot yet discriminate "
            "between pipeline versions and will report the same value for "
            "all of them until a relevance-filtering stage exists."
        ),
    }


def compute_latency(run_ids: list[str]) -> dict:
    """§3's cheapest metric to add: run_manifests.run_duration_seconds is
    already real (non-fabricated) on every run since Epic 4.2 -- pure
    read, no fixtures needed."""
    durations = []
    for rid in run_ids:
        manifest = get_run_manifest(rid)
        if manifest and manifest.get("run_duration_seconds") is not None:
            durations.append(manifest["run_duration_seconds"])
    rate = (sum(durations) / len(durations)) if durations else None
    return {
        "latency_seconds": round(rate, 1) if rate is not None else None,
        "n_runs_evaluated": len(durations),
        "n_runs_missing_duration": len(run_ids) - len(durations),
    }


def compute_extraction_completeness() -> dict:
    """Runs corpus_quality.score_paper_completeness() against the 3 real
    wiki pages in case-zero-gap-silent-fabrication.json's fixture_wiki
    (real captured output from the real 3-paper Data-17072026/ corpus).

    Honest limitation, not hidden: this fixture has no paired
    extraction_reconciler output, so doi/tables score "empty" rather than
    "not_extracted", and ref_count=0 makes "references" score "empty" too.
    These three biases are IDENTICAL for every pipeline/model version
    compared against this same fixture, so the metric stays valid as a
    relative comparator (which is what the promotion gate needs) even
    though its absolute value understates real extraction completeness.
    """
    entries = cases_feeding("extraction_completeness")
    if not entries:
        return {"extraction_completeness": None, "n_papers_evaluated": 0}

    version, case_id, filename = entries[0]
    case_dir = _V1_DIR if version == "v1" else _V2_DIR
    with open(os.path.join(case_dir, filename), encoding="utf-8") as f:
        case = json.load(f)

    pages = case.get("fixture_wiki", {}).get("pages", [])
    scores = [
        score_paper_completeness(reconciled={"fields": {}}, wiki_page=page, ref_count=0, has_figures=False)
        for page in pages
    ]
    achievable_scores = [s["achievable_completeness_score"] for s in scores]
    raw_scores = [s["completeness_score"] for s in scores]
    mean_achievable = sum(achievable_scores) / len(achievable_scores) if achievable_scores else None

    return {
        "extraction_completeness": round(mean_achievable, 3) if mean_achievable is not None else None,
        "n_papers_evaluated": len(pages),
        "per_paper_achievable_scores": achievable_scores,
        "per_paper_raw_scores": raw_scores,
        "metric_caveat": (
            "Fixture has no paired extraction_reconciler output (doi/tables "
            "score 'empty') and ref_count=0 ('references' scores 'empty') -- "
            "these biases are identical for every pipeline version compared "
            "against this fixture, so the metric remains valid as a relative "
            "comparator, not an absolute completeness measurement."
        ),
    }


def _load_duplicate_groups(filename: str) -> list[list[dict]]:
    with open(os.path.join(_V1_DIR, filename), encoding="utf-8") as f:
        case = json.load(f)
    return case.get("fixture_duplicate_groups", [])


def compute_reference_resolution_doi_path() -> dict:
    """Reference resolution precision/recall via case-reference-duplicate-
    doi.json's 3 real duplicate groups (2 DOI-identical records each) --
    real implicit ground truth: every group should collapse to exactly 1
    canonical entry, and no canonical entry should mix records from two
    different groups.

    Precision = fraction of canonical entries whose provider_records all
    come from one ground-truth group (no false cross-group merges).
    Recall = fraction of ground-truth groups that collapsed into exactly
    one canonical entry containing all of that group's records (no missed
    merges).
    """
    entries = cases_feeding("reference_resolution_precision")
    if not entries:
        return {"reference_resolution_precision": None, "reference_recall": None, "n_groups_evaluated": 0}

    _version, _case_id, filename = entries[0]
    groups = _load_duplicate_groups(filename)

    flat = []
    for i, group in enumerate(groups):
        for ref in group:
            r = dict(ref)
            r["_group_index"] = i
            flat.append(r)

    canonical = merge_canonical_references(flat)

    n_single_group_entries = sum(
        1 for c in canonical
        if len({r.get("_group_index") for r in c.get("provider_records", [])}) <= 1
    )
    precision = (n_single_group_entries / len(canonical)) if canonical else None

    n_correctly_collapsed = 0
    for i in range(len(groups)):
        touching = [c for c in canonical if any(r.get("_group_index") == i for r in c.get("provider_records", []))]
        if len(touching) == 1 and len(touching[0].get("provider_records", [])) == len(groups[i]):
            n_correctly_collapsed += 1
    recall = (n_correctly_collapsed / len(groups)) if groups else None

    # Cross-check via the application-facing helper (filter_and_dedupe_
    # references) -- a mismatch between the two independent code paths is
    # itself a reportable finding, not silently ignored.
    trusted, diagnostics = filter_and_dedupe_references(flat)
    expected_trusted = len(groups)
    cross_check_matches = diagnostics["trusted_count"] == expected_trusted

    return {
        "reference_resolution_precision": round(precision, 3) if precision is not None else None,
        "reference_recall": round(recall, 3) if recall is not None else None,
        "n_groups_evaluated": len(groups),
        "n_canonical_entries": len(canonical),
        "low_n_warning": len(groups) < _LOW_N_THRESHOLD,
        "cross_check": {
            "filter_and_dedupe_diagnostics": diagnostics,
            "expected_trusted_count": expected_trusted,
            "matches": cross_check_matches,
        },
    }


_V3_DIR = os.path.join(os.path.dirname(__file__), "..", "benchmarks", "v3")


def compute_reference_resolution_full_chain() -> dict:
    """Extends compute_reference_resolution_doi_path() with
    evals/benchmarks/v3's title_author_year fallback case (a real
    positive-merge group + a real negative-non-merge pair) -- exercises
    the title_author_year code path the DOI-only groups above never
    touch, raising the evaluated group count from 3 to 5 (crossing
    _LOW_N_THRESHOLD).

    Folds both v3 checks into reference_recall (each is a "did the
    resolver do the right thing on this group" pass/fail, same framing
    as the DOI groups' collapse check) -- reference_resolution_precision
    is left as the DOI-only value; the v3 negative-pair check is closer
    to a precision signal than a recall one, but combining precision
    across DOI-identity and title_author_year cases isn't apples-to-
    apples without more cases than exist today, so it's reported
    separately (v3_negative_pair_correct) rather than blended in.
    """
    doi_path = compute_reference_resolution_doi_path()

    v3_entries = [(v, c, f) for v, c, f in cases_feeding("reference_resolution_precision") if v == "v3"]
    if not v3_entries:
        return doi_path

    _version, _case_id, filename = v3_entries[0]
    with open(os.path.join(_V3_DIR, filename), encoding="utf-8") as f:
        case = json.load(f)

    pos = case["positive_group"]
    merged_pos = merge_canonical_references(pos["references"])
    positive_group_correct = len(merged_pos) == pos["expected_canonical_entry_count"]

    neg = case["negative_pair"]
    merged_neg = merge_canonical_references(neg["references"])
    actually_merged = len(merged_neg) < len(neg["references"])
    negative_pair_correct = actually_merged == neg["expected_merge"]

    n_doi_groups = doi_path["n_groups_evaluated"]
    n_doi_correct = (
        round(doi_path["reference_recall"] * n_doi_groups) if doi_path["reference_recall"] is not None else 0
    )
    n_total_groups = n_doi_groups + 2
    n_total_correct = n_doi_correct + int(positive_group_correct) + int(negative_pair_correct)
    combined_recall = (n_total_correct / n_total_groups) if n_total_groups else None

    return {
        **doi_path,
        "reference_recall": round(combined_recall, 3) if combined_recall is not None else doi_path["reference_recall"],
        "n_groups_evaluated": n_total_groups,
        "low_n_warning": n_total_groups < _LOW_N_THRESHOLD,
        "v3_positive_group_correct": positive_group_correct,
        "v3_negative_pair_correct": negative_pair_correct,
    }


def compute_evidence_coverage(run_id: str) -> dict:
    """§3: fraction of gap explanations with a valid, traceable Evidence
    Object reference. Sequenced after Epic 4.4's Scientific Lineage
    plumbing (motivating_evidence_ids/evidence_basis on every gap) --
    needs no new fixture, scoreable against any real run.

    Denominator excludes evidence_basis == "absence_of_evidence" gaps
    (reported separately as n_absence_based): those gaps correctly have
    no evidence to cite by design (e.g. an orphan concept, an untested
    combination) -- counting them against coverage would penalize a
    correctly-working signal for doing its job. Numerator requires each
    motivating_evidence_id to actually resolve against the run's real
    evidence_object id set, not merely be present (a dangling id doesn't
    count as coverage).
    """
    loaded = load_run(run_id)
    if not loaded:
        raise ValueError(f"Run '{run_id}' was not found -- cannot compute evidence coverage.")
    results = loaded.get("results", {}) or {}

    gaps = results.get("gaps", []) or []
    evidence_objects = results.get("evidence_objects", {}) or {}
    real_evidence_ids = {e.get("evidence_id") for objs in evidence_objects.values() for e in objs if e.get("evidence_id")}

    positive_gaps = [g for g in gaps if g.get("evidence_basis") == "positive_evidence"]
    absence_gaps = [g for g in gaps if g.get("evidence_basis") == "absence_of_evidence"]
    ungapped = [g for g in gaps if g.get("evidence_basis") not in ("positive_evidence", "absence_of_evidence")]

    n_covered = 0
    n_dangling_ids = 0
    for g in positive_gaps:
        motivating = g.get("motivating_evidence_ids", []) or []
        valid = [eid for eid in motivating if eid in real_evidence_ids]
        n_dangling_ids += len(motivating) - len(valid)
        if valid:
            n_covered += 1

    coverage = (n_covered / len(positive_gaps)) if positive_gaps else None
    n_all_covered = n_covered + sum(1 for g in absence_gaps if g.get("motivating_entity_ids") or g.get("motivating_relationship_ids"))
    coverage_all = (n_all_covered / len(gaps)) if gaps else None

    return {
        "evidence_coverage": round(coverage, 3) if coverage is not None else None,
        "evidence_coverage_all_gaps": round(coverage_all, 3) if coverage_all is not None else None,
        "n_positive_evidence_gaps": len(positive_gaps),
        "n_absence_based": len(absence_gaps),
        "n_no_evidence_basis_field": len(ungapped),
        "n_covered": n_covered,
        "n_unlinked": len(positive_gaps) - n_covered,
        "n_dangling_ids": n_dangling_ids,
    }


def compute_consistency_score(gap_sets: list[list[dict]], run_ids: list[str] = None) -> dict | None:
    """Thin wrapper around pipeline.repeatability_score.compute_
    repeatability_score(), reused as-is per
    07-evaluation-architecture.md §5's explicit instruction ("one
    evaluation harness serves both purposes, not two separate systems").
    Returns None (not a fabricated score) if fewer than 2 gap sets are
    supplied -- the underlying function requires >=2 runs to compare.
    """
    if len(gap_sets) < 2:
        return None
    report = compute_repeatability_score(gap_sets, run_ids=run_ids)
    return {
        "consistency_score": report["gap_overlap_mean"],
        "repeatability_report": report,
    }
