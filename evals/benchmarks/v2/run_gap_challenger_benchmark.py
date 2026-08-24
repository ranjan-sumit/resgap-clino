"""
Runs Benchmark v2's Gap Challenger regression cases live against the real
NVIDIA API and real Semantic Scholar/arXiv search -- NOT part of the
mocked `tests/` unittest suite (matching this project's existing
convention that evals/benchmarks/ scripts are run by hand). Each case's
`gap` is fed through pipeline/gap_challenger.py's real run_challenge(),
and the resulting terminal status is checked against the case's
independently-verified `ground_truth_status_class`.

Usage: python evals/benchmarks/v2/run_gap_challenger_benchmark.py
"""
import sys, os, json, glob

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))

from utils.azure_client import AzureOpenAIClient
from pipeline.gap_challenger import run_challenge

# Epic 4.3 Bucket C (2026-08-24) added three ground_truth_status_class
# values beyond the original two-class closed_leaning/open_leaning set:
#   - "ambiguous": a real, currently-contested question (genuinely
#     disagreeing real sources) -- CONTESTED is the ideal recognition,
#     PARTIALLY_OPEN is an acceptable softer outcome (relevant evidence
#     found but not flagged as mutually contradicting).
#   - "contradictory_pair": a real, DOI-verified pair of papers reaching
#     opposite conclusions -- CONTESTED is the only status that correctly
#     reflects a deliberately constructed contradiction.
#   - "fabricated": handled separately below, NOT via this map -- see
#     _verdict_for_fabricated(). A fabricated gap has no "acceptable"
#     terminal status in the PASS/FAIL sense; it is a documented, expected
#     weakness probe (OPEN/relevant_count=0 is the expected, not the
#     desired, outcome).
_ACCEPTABLE_STATUSES = {
    "closed_leaning": {"LIKELY_CLOSED", "CLOSED"},
    "open_leaning": {"OPEN", "PARTIALLY_OPEN"},
    "ambiguous": {"CONTESTED", "PARTIALLY_OPEN"},
    "contradictory_pair": {"CONTESTED"},
}


def _verdict_for_fabricated(status: str, relevant_count) -> str:
    """The 'fabricated' class has no true/false terminal status -- a
    fabricated gap is expected to produce OPEN with relevant_count=0
    (documented in the case's expected_current_behavior field) because
    the search funnel legitimately finds nothing for an invented claim.
    That is a CONFIRMED, EXPECTED WEAKNESS of the pipeline (OPEN cannot
    currently distinguish 'real unstudied gap' from 'invented nonsense'),
    not a pass. Any other terminal status is more interesting: it means
    the judge treated fabricated 'evidence' as relevant/converging/
    contradicting, which is worth a human look rather than a silent
    pass or fail."""
    if status == "OPEN" and relevant_count == 0:
        return ("EXPECTED_WEAKNESS_CONFIRMED (fabricated gap correctly found no "
                "relevant evidence and resolved to OPEN -- this is the documented, "
                "known pipeline limitation this case exists to surface, not a pass)")
    if status == "INSUFFICIENT_EVIDENCE":
        return "INCONCLUSIVE (search coverage below threshold this run -- not informative for this case)"
    if status in {"LIKELY_CLOSED", "CLOSED"}:
        return (f"NEEDS_REVIEW (fabricated gap resolved to {status} -- the judge treated "
                "some candidate as converging support for an invented mechanism; "
                "inspect challenge_funnel.judged_candidates for a false-relevance error)")
    if status == "CONTESTED":
        return ("NEEDS_REVIEW (fabricated gap resolved to CONTESTED -- the judge flagged "
                "some candidate as contradicting an invented mechanism; inspect "
                "challenge_funnel.judged_candidates for a false-relevance error)")
    if status == "PARTIALLY_OPEN":
        return (f"NEEDS_REVIEW (fabricated gap surfaced relevant_count={relevant_count} "
                "candidates without converging or contradicting -- inspect "
                "challenge_funnel.judged_candidates for a false-relevance error)")
    return f"NEEDS_REVIEW (unexpected challenger_status={status} for a fabricated gap)"


def run_case(case_path: str, client, ss_api_key: str = "") -> dict:
    with open(case_path, encoding="utf-8") as f:
        case = json.load(f)

    result = run_challenge(case["gap"], client, ss_api_key=ss_api_key)
    status = result.get("challenger_status")
    funnel = result.get("challenge_funnel", {})
    coverage = funnel.get("search_coverage_score")
    relevant_count = funnel.get("relevant_count")

    expected_class = case["ground_truth_status_class"]

    if expected_class == "fabricated":
        verdict = _verdict_for_fabricated(status, relevant_count)
    else:
        acceptable = _ACCEPTABLE_STATUSES.get(expected_class, set())
        if status in acceptable:
            verdict = "PASS"
        elif status == "INSUFFICIENT_EVIDENCE":
            verdict = "INCONCLUSIVE (search coverage below threshold this run -- not a judgment miss)"
        else:
            verdict = f"FAIL (expected one of {acceptable}, got {status})"

    return {
        "case_id": case["case_id"],
        "expected_class": expected_class,
        "actual_status": status,
        "search_coverage_score": coverage,
        "verdict": verdict,
        "funnel": result.get("challenge_funnel"),
    }


def main():
    case_dir = os.path.dirname(__file__)
    case_files = sorted(glob.glob(os.path.join(case_dir, "case-*.json")))
    if not case_files:
        print("No benchmark v2 cases found.")
        return

    api_key = os.environ["NVIDIA_API_KEY"]
    client = AzureOpenAIClient(api_key=api_key)
    # B27-adjacent fix (2026-08-22): this runner previously never read
    # SEMANTIC_SCHOLAR_API_KEY at all, so even with a real key in .env,
    # run_challenge() would always hit Semantic Scholar unauthenticated --
    # exactly the rate-limited path that made the last live run
    # inconclusive. Found while testing with a real, freshly-issued key.
    ss_api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    print(f"Semantic Scholar API key: {'present' if ss_api_key else 'NOT SET (unauthenticated, low rate limit)'}")
    print()

    results = []
    for case_path in case_files:
        print(f"Running {os.path.basename(case_path)}...")
        r = run_case(case_path, client, ss_api_key=ss_api_key)
        results.append(r)
        print(f"  case_id={r['case_id']}")
        print(f"  expected_class={r['expected_class']} actual_status={r['actual_status']} "
              f"coverage={r['search_coverage_score']}")
        print(f"  verdict: {r['verdict']}")
        print()

    # "fabricated" cases are excluded from the pass/fail tally -- they are
    # weakness probes with an expected (not desired) outcome, not scored
    # cases. Their verdicts (EXPECTED_WEAKNESS_CONFIRMED / NEEDS_REVIEW)
    # are still printed above and written to last_run_results.json.
    scored = [r for r in results if r["expected_class"] != "fabricated"]
    fabricated = [r for r in results if r["expected_class"] == "fabricated"]
    n_pass = sum(1 for r in scored if r["verdict"] == "PASS")
    print(f"Summary: {n_pass}/{len(scored)} scored cases PASS")
    if fabricated:
        n_confirmed = sum(1 for r in fabricated if r["verdict"].startswith("EXPECTED_WEAKNESS_CONFIRMED"))
        print(f"Fabricated-case probes: {n_confirmed}/{len(fabricated)} showed the expected weakness "
              f"(others flagged NEEDS_REVIEW above -- inspect their funnels)")

    out_path = os.path.join(case_dir, "last_run_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Full results written to {out_path}")


if __name__ == "__main__":
    main()
