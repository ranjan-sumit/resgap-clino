"""Real, benchmark-derived metric computations for Epic 4.3's Champion/
Challenger harness (07-evaluation-architecture.md §1/§3). Only the metrics
this pass actually has fixture coverage for are implemented here --
extraction completeness, reference precision/recall, retrieval recall,
gap precision, contradiction recall, and evidence coverage are explicitly
deferred (see the plan's Scope section); computing them without real
benchmark ground truth would mean fabricating numbers, which this
codebase's established convention (honest None over fabricated data)
rules out.
"""
import glob
import importlib.util
import json
import os
import sys

from pipeline.canonical_resolver import filter_and_dedupe_references
from pipeline.repeatability_score import compute_repeatability_score

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
