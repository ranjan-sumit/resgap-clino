"""Are the judges actually discriminating, and does a rerun give the same answer?

Two failure modes this module makes visible:

  * Flat scoring: a reviewer that gives every proposal 4/4/4/4 (or a critic that scores every gap the
    same) is not ranking anything. `score_spread` measures the spread of each score and
    `calibration_report` turns it into plain warnings.
  * Run-to-run drift: two runs on the same papers should mostly find the same gaps. Titles are never
    word-for-word identical, so `semantic_gap_overlap` matches gaps by what they say (word overlap of
    title and description, one-to-one) and reports the share of gaps the two runs agree on.
"""
from __future__ import annotations

import re
import statistics

MATCH_THRESHOLD = 0.4           # word-overlap (Jaccard) at which two gaps count as the same gap
MIN_FOR_SPREAD = 3              # fewer judged items than this cannot show a spread
CRITIC_SCORES = ("novelty", "importance", "feasibility")
REVIEWER_SCORES = ("specificity", "novelty", "feasibility", "impact")

_STOP = frozenset("with from this that have will been their which would could should about these those into over "
                  "using based study studies between across within through among other more than also such".split())


def _words(gap: dict) -> set:
    text = f"{gap.get('title', '')} {gap.get('description', '')}".lower()
    return {w for w in re.findall(r"[a-z0-9]{4,}", text) if w not in _STOP}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def semantic_gap_overlap(gaps_a: list, gaps_b: list, threshold: float = MATCH_THRESHOLD) -> dict:
    """Greedy one-to-one matching of gaps by content. `overlap` is matched / (|A| + |B| - matched), i.e. the
    share of all distinct gaps that both runs found. Two empty runs agree trivially (1.0); one empty does not."""
    wa, wb = [_words(g) for g in gaps_a], [_words(g) for g in gaps_b]
    pairs = sorted(((_jaccard(a, b), i, j) for i, a in enumerate(wa) for j, b in enumerate(wb)), reverse=True)
    used_a, used_b, matches = set(), set(), []
    for score, i, j in pairs:
        if score < threshold:
            break
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        matches.append({"a": gaps_a[i].get("title", ""), "b": gaps_b[j].get("title", ""), "similarity": round(score, 2)})
    matched = len(matches)
    union = len(gaps_a) + len(gaps_b) - matched
    return {"overlap": round(matched / union, 3) if union else 1.0, "matched": matched,
            "only_in_a": len(gaps_a) - matched, "only_in_b": len(gaps_b) - matched, "matches": matches}


def same_paper_set(results_a: dict, results_b: dict) -> bool:
    """True when two runs analysed the same papers (by filename)."""
    names = lambda r: {p.get("filename") for p in r.get("papers") or []}     # noqa: E731
    return bool(names(results_a)) and names(results_a) == names(results_b)


def score_spread(values: list) -> dict:
    nums = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not nums:
        return {"n": 0, "distinct": 0, "min": None, "max": None, "stdev": None, "flat": False}
    distinct = len(set(nums))
    return {"n": len(nums), "distinct": distinct, "min": min(nums), "max": max(nums),
            "stdev": round(statistics.pstdev(nums), 3), "flat": len(nums) >= MIN_FOR_SPREAD and distinct == 1}


def _spread_of(items: list, keys: tuple, source) -> dict:
    return {k: score_spread([source(it).get(k) for it in items if source(it)]) for k in keys}


def calibration_report(gaps: list, proposals: list) -> dict:
    """Spread of the critic's scores over the final gaps and the reviewer's over the proposals, with a
    plain-language warning for each judge that gave every item the same score."""
    critic = _spread_of(gaps, CRITIC_SCORES, lambda g: g.get("scores") or {})
    reviewer = _spread_of(proposals, REVIEWER_SCORES, lambda p: (p.get("review") or {}).get("scores") or {})
    warnings = []
    flat_c = [k for k, s in critic.items() if s["flat"]]
    if len(flat_c) == len(CRITIC_SCORES):
        warnings.append(f"The gap critic gave all {critic['novelty']['n']} gaps identical scores, so its ranking "
                        "carries no information.")
    elif flat_c:
        warnings.append(f"The gap critic scored every gap the same on {', '.join(flat_c)}.")
    flat_r = [k for k, s in reviewer.items() if s["flat"]]
    if len(flat_r) == len(REVIEWER_SCORES):
        warnings.append(f"The proposal reviewer gave all {reviewer['impact']['n']} proposals identical scores "
                        "(for example 4/4/4/4), so it is not discriminating between them.")
    elif flat_r:
        warnings.append(f"The proposal reviewer scored every proposal the same on {', '.join(flat_r)}.")
    return {"critic": critic, "reviewer": reviewer, "warnings": warnings}


def self_preference_note(config) -> str | None:
    """A model judging its own writing tends to approve it. Returns a warning when the gap critic and
    proposal reviewer (the council chair's model) are the very model that wrote the gaps and proposals."""
    from utils.model_router import ROLE_ANALYSIS, ROLE_COUNCIL_CHAIR
    writer, judge = config.spec_for(ROLE_ANALYSIS), config.spec_for(ROLE_COUNCIL_CHAIR)
    if writer == judge:
        return (f"The gap critic and proposal reviewer use the same model that writes the gaps and proposals "
                f"({judge.model}), which tends to approve its own work. Give the Council chair a different model "
                "in Settings → Models.")
    return None


def compare_with_previous(current: dict, previous: dict, previous_id: str | None = None) -> dict | None:
    """Overlap of this run's gaps with an earlier run on the same papers, or None if they are not comparable."""
    if not same_paper_set(current, previous):
        return None
    out = semantic_gap_overlap(current.get("gaps") or [], previous.get("gaps") or [])
    out.update({"vs_run": previous_id, "n_current": len(current.get("gaps") or []),
                "n_previous": len(previous.get("gaps") or [])})
    return out
