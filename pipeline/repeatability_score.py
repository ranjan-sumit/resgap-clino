"""
Repeatability Score (Clinova Phase 3, Epic 3.6, 04-ai-research-
architecture.md §6.1) -- measures how stable this pipeline's gap output
is across repeated runs against the SAME corpus/context, not whether any
one run is "correct." Explicitly not a claim of full determinism (LLM
calls are inherently non-deterministic even at low temperature) -- the
product's own honest framing per §6.1: "this pipeline version is 92%
repeatable on the benchmark," never "this pipeline is deterministic."

Four metrics, each computed pairwise across every pair of runs in the
given set and then averaged:
  - Gap overlap: Jaccard similarity of the generated-gap title sets.
  - Ranking correlation: Spearman correlation of gap ranking, computed
    only over gaps common to both runs (see _spearman_of_common_gaps()'s
    docstring for the honest limitation this implies).
  - Confidence drift: mean absolute difference in confidence (mapped to
    0/0.5/1) for gaps common to both runs.
  - Claim stability: fraction of one run's gap titles that reappear
    verbatim in the other -- a stricter, asymmetric-then-averaged
    lexical measure, distinct from Jaccard's set-overlap framing.

Honest limitation, stated once here rather than scattered in comments:
the architecture doc's exact phrasing is "ranking correlation of
opportunity-score rankings" -- no `opportunity_score` field exists
anywhere in this pipeline yet (it's a Phase 5 UX-spec concept, not
implemented). Generation order is used as the ranking proxy instead;
this is named honestly in the returned report, not silently substituted.
"""
import re
from itertools import combinations

from scipy.stats import spearmanr

REPEATABILITY_SCORE_VERSION = 1

_CONFIDENCE_TO_NUM = {"low": 0.0, "medium": 0.5, "high": 1.0}


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _gap_overlap(gaps_a: list, gaps_b: list) -> float:
    """Jaccard similarity of normalized gap-title sets. 1.0 if both
    empty (nothing to disagree about); 0.0 if exactly one is empty."""
    titles_a = {_normalize_title(g.get("title", "")) for g in gaps_a if g.get("title")}
    titles_b = {_normalize_title(g.get("title", "")) for g in gaps_b if g.get("title")}
    if not titles_a and not titles_b:
        return 1.0
    union = titles_a | titles_b
    if not union:
        return 1.0
    return len(titles_a & titles_b) / len(union)


def _claim_stability(gaps_a: list, gaps_b: list) -> float:
    """Fraction of gap titles shared between the two runs, symmetric
    (averaged both directions) -- distinct from Jaccard: this is closer
    to "how much of what each run said survives in the other," not "how
    much of the combined set is agreed on." The two metrics coincide only
    when |A| == |B|."""
    titles_a = [_normalize_title(g.get("title", "")) for g in gaps_a if g.get("title")]
    titles_b = {_normalize_title(g.get("title", "")) for g in gaps_b if g.get("title")}
    titles_b_list = [_normalize_title(g.get("title", "")) for g in gaps_b if g.get("title")]
    titles_a_set = set(titles_a)
    if not titles_a and not titles_b_list:
        return 1.0
    frac_a_in_b = (sum(1 for t in titles_a if t in titles_b) / len(titles_a)) if titles_a else 0.0
    frac_b_in_a = (sum(1 for t in titles_b_list if t in titles_a_set) / len(titles_b_list)) if titles_b_list else 0.0
    return (frac_a_in_b + frac_b_in_a) / 2


def _matched_pairs(gaps_a: list, gaps_b: list) -> list[tuple[dict, dict]]:
    """Gaps present (by normalized title) in both runs, paired up --
    the substrate for ranking correlation and confidence drift, both of
    which are only meaningful for gaps that actually recurred."""
    by_title_b = {}
    for g in gaps_b:
        by_title_b.setdefault(_normalize_title(g.get("title", "")), g)
    pairs = []
    for g in gaps_a:
        key = _normalize_title(g.get("title", ""))
        if key and key in by_title_b:
            pairs.append((g, by_title_b[key]))
    return pairs


def _ranking_correlation(gaps_a: list, gaps_b: list) -> float | None:
    """Spearman correlation of generation-order rank, restricted to gaps
    common to both runs (see module docstring on the opportunity_score
    substitution). Returns None (not 0.0 -- a real "undefined", not a
    real "no correlation") when fewer than 2 gaps are common, since
    Spearman needs at least 2 points and a `None` here must not be
    silently averaged in as if it meant "no correlation found"."""
    pairs = _matched_pairs(gaps_a, gaps_b)
    if len(pairs) < 2:
        return None
    # Positional pairing via identity, not list.index(): with equality-based
    # index() two identical gaps would resolve to the same first-match
    # position and get the same rank, distorting the correlation.
    pos_a = {id(g): i for i, g in enumerate(gaps_a)}
    pos_b = {id(g): i for i, g in enumerate(gaps_b)}
    rank_a = [pos_a[id(g)] for g, _ in pairs]
    rank_b = [pos_b[id(g)] for _, g in pairs]
    if len(set(rank_a)) < 2 or len(set(rank_b)) < 2:
        return None
    corr, _ = spearmanr(rank_a, rank_b)
    return None if corr != corr else float(corr)  # corr != corr catches NaN


def _confidence_drift(gaps_a: list, gaps_b: list) -> float | None:
    """Mean absolute difference in confidence (low/medium/high -> 0/.5/1)
    for gaps common to both runs. None (not 0.0) when there are no
    common gaps -- "no drift measured" is not the same claim as "zero
    drift confirmed."""
    pairs = _matched_pairs(gaps_a, gaps_b)
    if not pairs:
        return None
    diffs = []
    for ga, gb in pairs:
        ca = _CONFIDENCE_TO_NUM.get(ga.get("confidence"))
        cb = _CONFIDENCE_TO_NUM.get(gb.get("confidence"))
        if ca is not None and cb is not None:
            diffs.append(abs(ca - cb))
    if not diffs:
        return None
    return sum(diffs) / len(diffs)


def _is_likely_duplicate_run(gaps_a: list, gaps_b: list) -> bool:
    """True if the two gap lists are identical in content AND order --
    title, confidence, and sequence all matching exactly.

    Real-data finding (2026-08-22): app.py's Computational Lab feature
    (the "Run Computational Lab" button) saves a NEW run via
    `save_run(lab_run_name, st.session_state.results, comp_results)` --
    passing the ORIGINAL, unchanged pipeline results (gaps included)
    alongside new simulation output, not a fresh pipeline re-run. Two
    runs related this way will score a perfect 1.0 on every metric here,
    but that is not evidence of genuine pipeline repeatability -- it is
    the same generation saved twice under two run_ids. A gap_overlap==1.0
    check alone isn't quite strict enough (two independently-generated
    runs could coincidentally converge on the same SET of titles in a
    different order); requiring exact order too is a stronger, more
    specific signal of "this is the same saved list," not a coincidence.
    """
    if len(gaps_a) != len(gaps_b) or not gaps_a:
        return False
    sig_a = [(_normalize_title(g.get("title", "")), g.get("confidence")) for g in gaps_a]
    sig_b = [(_normalize_title(g.get("title", "")), g.get("confidence")) for g in gaps_b]
    return sig_a == sig_b


def compute_repeatability_score(gap_sets: list[list[dict]], run_ids: list[str] = None,
                                 include_duplicate_runs: bool = False) -> dict:
    """Main entry point. `gap_sets` is a list of N runs' `gaps` lists
    (the same shape app.py's results["gaps"] already has) from repeated
    runs against the SAME corpus/context -- comparing runs from different
    corpora would produce a meaningless score, so this function trusts
    the caller to have already selected genuinely repeated runs (it
    cannot verify "same corpus" from the gap lists alone) -- it CAN,
    however, detect the specific real case of two runs sharing the exact
    same generation (see `_is_likely_duplicate_run()`), and does so
    automatically: such pairs are excluded from the averaged metrics by
    default (`include_duplicate_runs=False`) since they are not
    independent samples and would silently inflate the score, but they
    are still listed in `pairs` with `likely_duplicate_run: true` so
    nothing is hidden, only excluded from the headline numbers. Pass
    `include_duplicate_runs=True` to fall back to the raw, unfiltered
    averages (e.g. for debugging this detection itself).

    Returns a report with per-pair and averaged values for all four
    metrics, `n_runs`, `n_pairs`, `n_duplicate_pairs_excluded`, and an
    explicit `ranking_proxy_note` documenting the opportunity_score
    substitution -- never silently reported as if it were the literal
    metric the architecture doc names.
    """
    n = len(gap_sets)
    if n < 2:
        raise ValueError("compute_repeatability_score needs at least 2 runs to compare -- "
                          f"got {n}. A single run has nothing to measure repeatability against.")

    ids = run_ids or [f"run_{i}" for i in range(n)]
    pairs_report = []
    overlaps, stabilities, corrs, drifts = [], [], [], []
    n_duplicates = 0

    for i, j in combinations(range(n), 2):
        ga, gb = gap_sets[i], gap_sets[j]
        overlap = _gap_overlap(ga, gb)
        stability = _claim_stability(ga, gb)
        corr = _ranking_correlation(ga, gb)
        drift = _confidence_drift(ga, gb)
        is_duplicate = _is_likely_duplicate_run(ga, gb)
        if is_duplicate:
            n_duplicates += 1

        if include_duplicate_runs or not is_duplicate:
            overlaps.append(overlap)
            stabilities.append(stability)
            if corr is not None:
                corrs.append(corr)
            if drift is not None:
                drifts.append(drift)

        pairs_report.append({
            "run_a": ids[i], "run_b": ids[j],
            "gap_overlap": round(overlap, 3),
            "claim_stability": round(stability, 3),
            "ranking_correlation": round(corr, 3) if corr is not None else None,
            "confidence_drift": round(drift, 3) if drift is not None else None,
            "n_common_gaps": len(_matched_pairs(ga, gb)),
            "likely_duplicate_run": is_duplicate,
        })

    def _avg(values):
        return round(sum(values) / len(values), 3) if values else None

    return {
        "repeatability_score_version": REPEATABILITY_SCORE_VERSION,
        "n_runs": n,
        "n_pairs": len(pairs_report),
        "n_duplicate_pairs_excluded": 0 if include_duplicate_runs else n_duplicates,
        "gap_overlap_mean": _avg(overlaps),
        "claim_stability_mean": _avg(stabilities),
        "ranking_correlation_mean": _avg(corrs),
        "confidence_drift_mean": _avg(drifts),
        "ranking_correlation_undefined_pairs": len(pairs_report) - n_duplicates - len(corrs) if not include_duplicate_runs else len(pairs_report) - len(corrs),
        "confidence_drift_undefined_pairs": len(pairs_report) - n_duplicates - len(drifts) if not include_duplicate_runs else len(pairs_report) - len(drifts),
        "ranking_proxy_note": (
            "ranking_correlation uses each run's gap generation order as a proxy "
            "for the architecture doc's 'opportunity-score ranking' -- no "
            "opportunity_score field exists in the pipeline yet (Phase 5 UX-spec "
            "concept only), so this is an honest substitute, not the literal metric."
        ),
        "duplicate_run_note": (
            "Pairs flagged likely_duplicate_run=true (identical gap titles, "
            "confidences, AND order) are excluded from the *_mean values above -- "
            "app.py's Computational Lab feature saves the original pipeline "
            "results unchanged alongside new simulation output, so two run_ids "
            "can legitimately share one identical generation; that is not a "
            "measurement of repeatability. Pass include_duplicate_runs=True to "
            "include them anyway."
        ) if n_duplicates else None,
        "pairs": pairs_report,
    }
