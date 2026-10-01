"""
Regression tests for pipeline/multi_run.py merge_council_runs: runs that
errored out contribute no findings and are excluded from the confidence
frequency denominator, so 2 agreeing successes out of 3 attempts is a
Consensus, not a Likely.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.multi_run import merge_council_runs


def _success_run(idx, claim):
    return {
        "run_index": idx,
        "final_decision": {
            "novel_finding": {"claim": claim, "title": "T", "confidence": "high"},
            "clinical_insights": ["fund the confirmatory trial"],
        },
        "agents": [],
    }


def _failed_run(idx):
    return {
        "run_index": idx,
        "final_decision": {},
        "agents": [],
        "error": "api unreachable",
    }


class FailedRunsExcludedFromDenominatorTests(unittest.TestCase):
    def test_two_agreeing_successes_plus_one_failed_run_is_consensus(self):
        runs = [
            _success_run(1, "Drug X cuts recurrence risk by 30%"),
            _failed_run(2),
            _success_run(3, "Drug X reduces recurrence risk by 30 percent"),
        ]
        merged = merge_council_runs(runs)

        self.assertEqual(len(merged["novel_finding_groups"]), 1)
        group = merged["novel_finding_groups"][0]
        self.assertEqual(group["count"], 2)
        # Denominator is successful runs (2), not total attempts (3):
        # 2/2 = Consensus; the old 2/3 = "Likely".
        self.assertEqual(group["confidence"], "Consensus")
        self.assertEqual(group["frequency"], "2/2 runs")
        self.assertEqual(merged["coverage_stats"]["consensus_findings"], 1)

    def test_failed_run_insights_do_not_appear(self):
        runs = [
            {"run_index": 1, "final_decision": {"clinical_insights": ["fund the trial"]},
             "agents": []},
            _failed_run(2),
            {"run_index": 3, "final_decision": {}, "agents": []},
        ]
        merged = merge_council_runs(runs)
        self.assertEqual(len(merged["clinical_insight_groups"]), 1)
        self.assertEqual(
            merged["clinical_insight_groups"][0]["frequency"], "1/2 runs"
        )

    def test_all_runs_failed_does_not_crash(self):
        merged = merge_council_runs([_failed_run(1), _failed_run(2)])
        self.assertEqual(merged["novel_finding_groups"], [])
        self.assertEqual(merged["final_decision"]["novel_finding"], {})


if __name__ == "__main__":
    unittest.main()
