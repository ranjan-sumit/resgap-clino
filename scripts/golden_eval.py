"""Quality check against a saved run: fails (exit 1) when a metric is worse than the thresholds.

    python scripts/golden_eval.py --run <run_id>          # a run in the local database
    python scripts/golden_eval.py --file results.json     # a results JSON ({"results": {...}} or bare)

Thresholds live in evals/golden_thresholds.json: a minimum for rates where more is better, a
maximum where less is better. A metric that could not be measured (None) is reported, not failed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

THRESHOLDS = ROOT / "evals" / "golden_thresholds.json"


def evaluate(quality: dict, thresholds: dict) -> list[str]:
    """Returns the list of failures (empty when the run passes)."""
    failures = []
    for metric, floor in thresholds.get("min", {}).items():
        value = quality.get(metric)
        if value is not None and value < floor:
            failures.append(f"{metric} = {value} is below the minimum {floor}")
    for metric, ceiling in thresholds.get("max", {}).items():
        value = quality.get(metric)
        if value is not None and value > ceiling:
            failures.append(f"{metric} = {value} is above the maximum {ceiling}")
    return failures


def quality_of(results: dict) -> dict:
    from pipeline.run_quality import compute_run_quality
    return results.get("run_quality") or compute_run_quality(results)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run")
    ap.add_argument("--file")
    ap.add_argument("--thresholds", default=str(THRESHOLDS))
    args = ap.parse_args(argv)
    if bool(args.run) == bool(args.file):
        ap.error("give exactly one of --run or --file")
    if args.run:
        import utils.database as db
        results = db.load_run(args.run, sections=False).get("results")
        if not results:
            print(f"run {args.run} not found")
            return 2
    else:
        raw = json.loads(Path(args.file).read_text(encoding="utf-8"))
        results = raw.get("results", raw)
    quality = quality_of(results)
    thresholds = json.loads(Path(args.thresholds).read_text(encoding="utf-8"))
    for k, v in quality.items():
        print(f"  {k}: {v}")
    failures = evaluate(quality, thresholds)
    for f in failures:
        print("FAIL:", f)
    print("PASS" if not failures else f"{len(failures)} metric(s) regressed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
