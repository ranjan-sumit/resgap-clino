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

_ACCEPTABLE_STATUSES = {
    "closed_leaning": {"LIKELY_CLOSED", "CLOSED"},
    "open_leaning": {"OPEN", "PARTIALLY_OPEN"},
}


def run_case(case_path: str, client) -> dict:
    with open(case_path, encoding="utf-8") as f:
        case = json.load(f)

    result = run_challenge(case["gap"], client)
    status = result.get("challenger_status")
    coverage = result.get("challenge_funnel", {}).get("search_coverage_score")

    expected_class = case["ground_truth_status_class"]
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

    results = []
    for case_path in case_files:
        print(f"Running {os.path.basename(case_path)}...")
        r = run_case(case_path, client)
        results.append(r)
        print(f"  case_id={r['case_id']}")
        print(f"  expected_class={r['expected_class']} actual_status={r['actual_status']} "
              f"coverage={r['search_coverage_score']}")
        print(f"  verdict: {r['verdict']}")
        print()

    n_pass = sum(1 for r in results if r["verdict"] == "PASS")
    print(f"Summary: {n_pass}/{len(results)} cases PASS")

    out_path = os.path.join(case_dir, "last_run_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Full results written to {out_path}")


if __name__ == "__main__":
    main()
