"""
Live, run-by-hand entry point for Epic 4.3's Champion/Challenger harness --
mirrors evals/benchmarks/v2/run_gap_challenger_benchmark.py's existing
convention exactly: real NVIDIA + Semantic Scholar API calls, real
Postgres reads/writes, no mocks, not part of the mocked `tests/` pytest
suite.

Usage:
    python evals/regression/run_champion_challenger.py \
        [--champion-model openai/gpt-oss-20b] [--candidate-model openai/gpt-oss-120b] \
        [--project-id default] [--promote]

The "pipeline version" this compares is, concretely, a model_bundle_version
swap (utils/model_providers.py) -- the readiest real two-config comparison
on this machine today, matching pipeline/run_compare.py's own documented
framing of what a champion/challenger comparison means in this repo right
now.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from utils.azure_client import AzureOpenAIClient, MASTER_MODEL, FALLBACK_MODEL
from utils.database import record_artifact, record_run_manifest

from evals.regression.benchmark_registry import register_benchmark_version
from evals.regression.metrics import (
    compute_contradiction_recall,
    compute_corpus_contamination_rate,
    compute_evidence_coverage,
    compute_extraction_completeness,
    compute_false_novelty_rate,
    compute_gap_precision,
    compute_latency,
    compute_reference_resolution_full_chain,
)
from evals.regression.promotion_gate import evaluate_promotion


def _run_side(label: str, model: str, api_key: str, ss_api_key: str, run_id: str = None) -> dict:
    print(f"\n=== {label}: {model} ===")
    client = AzureOpenAIClient(api_key=api_key, model=model)

    fnr = compute_false_novelty_rate(client, ss_api_key=ss_api_key)
    print(f"  False Novelty Rate: {fnr['false_novelty_rate']} "
          f"({fnr['n_misses']}/{fnr['n_cases_evaluated']} cases, "
          f"{fnr['n_inconclusive']} inconclusive"
          f"{' -- LOW N' if fnr['low_n_warning'] else ''})")

    contamination = compute_corpus_contamination_rate()
    print(f"  Corpus Contamination Rate: {contamination['corpus_contamination_rate']} "
          f"({contamination['n_retained_contaminated']}/{contamination['n_cases_evaluated']} cases)")

    gap_precision = compute_gap_precision(client, ss_api_key=ss_api_key)
    print(f"  Gap Precision: {gap_precision['gap_precision']} "
          f"({gap_precision['n_reported_and_genuine']}/{gap_precision['n_reported']} reported"
          f"{' -- LOW N' if gap_precision['low_n_warning'] else ''})")

    contradiction = compute_contradiction_recall(client, ss_api_key=ss_api_key)
    print(f"  Contradiction Recall: {contradiction['contradiction_recall']} "
          f"(retrieval_recall={contradiction['retrieval_recall']}, "
          f"{contradiction['n_pairs_retrieved']}/{contradiction['n_pairs_total']} pairs retrieved)")

    # Fixture-based, zero LLM calls -- identical for both sides regardless
    # of model (not yet a discriminating comparison, same honest framing
    # as corpus contamination), reported anyway since the promotion gate
    # still needs a real value on each side to compare.
    extraction = compute_extraction_completeness()
    print(f"  Extraction Completeness: {extraction['extraction_completeness']}")
    ref_resolution = compute_reference_resolution_full_chain()
    print(f"  Reference Resolution Precision/Recall: "
          f"{ref_resolution['reference_resolution_precision']}/{ref_resolution['reference_recall']}")

    metrics = {
        "false_novelty_rate": fnr["false_novelty_rate"],
        "corpus_contamination_rate": contamination["corpus_contamination_rate"],
        "gap_precision": gap_precision["gap_precision"],
        "contradiction_recall": contradiction["contradiction_recall"],
        "retrieval_recall": contradiction["retrieval_recall"],
        "extraction_completeness": extraction["extraction_completeness"],
        "reference_resolution_precision": ref_resolution["reference_resolution_precision"],
        "reference_recall": ref_resolution["reference_recall"],
    }

    # Run-scoped metrics (genuinely differ per side): only computed when a
    # real saved run_id is supplied for this side.
    if run_id:
        latency = compute_latency([run_id])
        metrics["latency_seconds"] = latency["latency_seconds"]
        print(f"  Latency: {latency['latency_seconds']} seconds (run {run_id[:8]})")
        try:
            coverage = compute_evidence_coverage(run_id)
            metrics["evidence_coverage"] = coverage["evidence_coverage"]
            print(f"  Evidence Coverage: {coverage['evidence_coverage']} "
                  f"({coverage['n_covered']}/{coverage['n_positive_evidence_gaps']} gaps, "
                  f"{coverage['n_absence_based']} absence-based excluded)")
        except ValueError as e:
            print(f"  Evidence Coverage: skipped -- {e}")

    return {
        "model": model,
        "run_id": run_id,
        "metrics": metrics,
        "fnr_detail": fnr,
        "contamination_detail": contamination,
        "gap_precision_detail": gap_precision,
        "contradiction_detail": contradiction,
        "extraction_detail": extraction,
        "reference_resolution_detail": ref_resolution,
    }


def main():
    parser = argparse.ArgumentParser(description="Epic 4.3 Champion/Challenger harness")
    parser.add_argument("--champion-model", default=MASTER_MODEL)
    parser.add_argument("--candidate-model", default=FALLBACK_MODEL)
    parser.add_argument("--champion-run-id", default=None,
                         help="A real saved run_id to compute run-scoped metrics "
                              "(latency, evidence coverage) for the champion side.")
    parser.add_argument("--candidate-run-id", default=None,
                         help="Same, for the candidate side.")
    parser.add_argument("--project-id", default="default")
    parser.add_argument("--promote", action="store_true",
                         help="If eligible, actually call promote_artifact() -- "
                              "otherwise this is a dry run report only.")
    args = parser.parse_args()

    api_key = os.environ["NVIDIA_API_KEY"]
    ss_api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    print(f"Semantic Scholar API key: {'present' if ss_api_key else 'NOT SET (unauthenticated, low rate limit)'}")

    v1_id = register_benchmark_version("v1")
    v2_id = register_benchmark_version("v2")
    print(f"\nRegistered benchmark artifacts: {v1_id}, {v2_id}")

    champion_result = _run_side("CHAMPION", args.champion_model, api_key, ss_api_key, run_id=args.champion_run_id)
    candidate_result = _run_side("CANDIDATE", args.candidate_model, api_key, ss_api_key, run_id=args.candidate_run_id)

    champion_metrics = champion_result["metrics"]
    candidate_metrics = candidate_result["metrics"]

    report = evaluate_promotion(champion_metrics, candidate_metrics)

    print("\n=== Promotion verdict ===")
    for row in report["metric_results"]:
        print(f"  {row['metric']}: champion={row['champion']} candidate={row['candidate']} "
              f"delta_pct={row['delta_pct']} tolerance={row['tolerance']} verdict={row['verdict']}")
    print(f"\n  eligible={report['eligible']}")
    if report["hard_gate_failures"]:
        print(f"  hard_gate_failures={report['hard_gate_failures']}")
    if report["soft_regressions"]:
        print(f"  soft_regressions={report['soft_regressions']}")
    if report["warnings"]:
        print(f"  warnings={report['warnings']}")

    # Write a synthetic run_id for the candidate side's evaluation_metrics --
    # a real per-run write (not the promotion write, which needs a real
    # artifact_id from an actual saved pipeline run, see the plan's
    # live-verification step 4 for that separate, manual check).
    synthetic_run_id = f"champion_challenger_probe:{args.candidate_model}"
    record_run_manifest(
        run_id=synthetic_run_id,
        project_id=args.project_id,
        model_bundle_version=f"nvidia:{args.candidate_model}",
        evaluation_metrics=candidate_metrics,
    )
    print(f"\nWrote candidate evaluation_metrics to run_manifests (run_id={synthetic_run_id}).")

    out_path = os.path.join(os.path.dirname(__file__), "last_run_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {"champion": champion_result, "candidate": candidate_result, "promotion": report},
            f, indent=2, default=str,
        )
    print(f"Full report written to {out_path}")

    if args.promote:
        if not report["eligible"]:
            print("\n--promote given but candidate is not eligible; not promoting.")
        else:
            print("\n--promote given and candidate is eligible, but no real candidate "
                  "artifact_id was supplied to this probe run -- use "
                  "evaluate_and_promote() directly against a real saved pipeline "
                  "run's `pipeline:{run_id}` artifact_id to actually promote it.")


if __name__ == "__main__":
    main()
