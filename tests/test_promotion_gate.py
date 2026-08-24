"""Epic 4.3: pure-function + mocked-I/O coverage for
evals/regression/promotion_gate.py. No live API/Postgres dependency --
matches tests/test_run_compare.py's existing mocking style for the I/O
wrapper functions."""
from unittest.mock import patch

import pytest

from evals.regression.promotion_gate import (
    evaluate_and_promote,
    evaluate_promotion,
    mark_candidate_if_evaluated,
)


class TestEvaluatePromotionPureLogic:
    def test_identical_metrics_are_eligible(self):
        metrics = {"false_novelty_rate": 0.1, "corpus_contamination_rate": 0.2}
        report = evaluate_promotion(metrics, dict(metrics))
        assert report["eligible"] is True
        assert report["hard_gate_failures"] == []
        assert report["soft_regressions"] == []

    def test_hard_gate_regression_blocks_even_with_soft_improvement(self):
        champion = {"false_novelty_rate": 0.1, "gap_precision": 0.5}
        candidate = {"false_novelty_rate": 0.3, "gap_precision": 0.9}  # FNR much worse, precision much better
        report = evaluate_promotion(champion, candidate)
        assert report["eligible"] is False
        assert "false_novelty_rate" in report["hard_gate_failures"]

    def test_hard_gate_has_zero_tolerance(self):
        champion = {"false_novelty_rate": 0.10}
        candidate = {"false_novelty_rate": 0.1001}  # a hair worse
        report = evaluate_promotion(champion, candidate)
        assert report["eligible"] is False
        assert "false_novelty_rate" in report["hard_gate_failures"]

    def test_quality_metric_within_5pct_tolerance_passes(self):
        champion = {"gap_precision": 0.80}
        candidate = {"gap_precision": 0.77}  # -3.75%, within 5% band
        report = evaluate_promotion(champion, candidate)
        assert report["eligible"] is True
        assert report["soft_regressions"] == []

    def test_quality_metric_beyond_5pct_tolerance_fails_softly(self):
        champion = {"gap_precision": 0.80}
        candidate = {"gap_precision": 0.70}  # -12.5%, beyond 5% band
        report = evaluate_promotion(champion, candidate)
        assert report["eligible"] is False
        assert "gap_precision" in report["soft_regressions"]
        assert report["hard_gate_failures"] == []

    def test_cost_metric_has_wider_15pct_tolerance(self):
        champion = {"latency_seconds": 100.0}
        candidate = {"latency_seconds": 110.0}  # +10%, within 15% cost band
        report = evaluate_promotion(champion, candidate)
        assert report["eligible"] is True

    def test_cost_metric_beyond_15pct_fails(self):
        champion = {"latency_seconds": 100.0}
        candidate = {"latency_seconds": 120.0}  # +20%, beyond 15% band
        report = evaluate_promotion(champion, candidate)
        assert report["eligible"] is False
        assert "latency_seconds" in report["soft_regressions"]

    def test_metric_missing_on_both_sides_is_skipped_not_blocking(self):
        report = evaluate_promotion({}, {})
        assert report["eligible"] is True
        assert report["metric_results"] == []

    def test_metric_present_on_champion_missing_on_candidate_is_warning_not_failure(self):
        champion = {"reference_recall": 0.9}
        candidate = {}
        report = evaluate_promotion(champion, candidate)
        assert report["eligible"] is True  # a warning, not a blocking failure
        assert len(report["warnings"]) == 1
        assert "reference_recall" in report["warnings"][0]

    def test_metric_present_on_candidate_missing_on_champion_is_no_baseline(self):
        report = evaluate_promotion({}, {"gap_precision": 0.5})
        assert report["eligible"] is True
        assert report["metric_results"][0]["verdict"] == "no_champion_baseline"

    def test_unrecognized_metric_keys_are_ignored(self):
        report = evaluate_promotion({"not_a_real_metric": 1}, {"not_a_real_metric": 999})
        assert report["metric_results"] == []
        assert report["eligible"] is True

    def test_lower_is_better_direction_for_contamination(self):
        champion = {"corpus_contamination_rate": 0.5}
        candidate = {"corpus_contamination_rate": 0.5}  # tie -- must pass (hard gate, "no worse than")
        report = evaluate_promotion(champion, candidate)
        assert report["eligible"] is True


class TestEvaluateAndPromoteIO:
    @patch("evals.regression.promotion_gate.promote_artifact")
    @patch("evals.regression.promotion_gate.list_artifacts", return_value=[])
    def test_bootstrap_no_existing_champion_is_auto_eligible_and_promotes(self, mock_list, mock_promote):
        report = evaluate_and_promote(
            candidate_artifact_id="pipeline:run123", artifact_type="pipeline",
            project_id="default", candidate_metrics={"false_novelty_rate": 0.2},
        )
        assert report["eligible"] is True
        assert report["promoted"] is True
        assert report["archived_previous_champion"] is False
        mock_promote.assert_called_once_with("pipeline:run123", "CHAMPION")

    @patch("evals.regression.promotion_gate.get_run_manifest", return_value={
        "evaluation_metrics": {"false_novelty_rate": 0.1}})
    @patch("evals.regression.promotion_gate.promote_artifact")
    @patch("evals.regression.promotion_gate.list_artifacts",
           return_value=[{"artifact_id": "pipeline:old_champ", "run_id": "old_run"}])
    def test_eligible_candidate_archives_old_champion_and_promotes_new(
        self, mock_list, mock_promote, mock_manifest
    ):
        report = evaluate_and_promote(
            candidate_artifact_id="pipeline:new_run", artifact_type="pipeline",
            project_id="default", candidate_metrics={"false_novelty_rate": 0.1},
        )
        assert report["eligible"] is True
        assert report["promoted"] is True
        assert report["archived_previous_champion"] is True
        assert mock_promote.call_args_list[0].args == ("pipeline:old_champ", "ARCHIVED")
        assert mock_promote.call_args_list[1].args == ("pipeline:new_run", "CHAMPION")

    @patch("evals.regression.promotion_gate.get_run_manifest", return_value={
        "evaluation_metrics": {"false_novelty_rate": 0.05}})
    @patch("evals.regression.promotion_gate.promote_artifact")
    @patch("evals.regression.promotion_gate.list_artifacts",
           return_value=[{"artifact_id": "pipeline:old_champ", "run_id": "old_run"}])
    def test_ineligible_candidate_is_never_promoted(self, mock_list, mock_promote, mock_manifest):
        report = evaluate_and_promote(
            candidate_artifact_id="pipeline:new_run", artifact_type="pipeline",
            project_id="default", candidate_metrics={"false_novelty_rate": 0.5},  # much worse
        )
        assert report["eligible"] is False
        assert report["promoted"] is False
        mock_promote.assert_not_called()


class TestMarkCandidateIfEvaluated:
    @patch("evals.regression.promotion_gate.promote_artifact")
    def test_promotes_when_at_least_one_real_metric_exists(self, mock_promote):
        result = mark_candidate_if_evaluated("pipeline:run1", {"false_novelty_rate": 0.1, "gap_precision": None})
        assert result["promoted"] is True
        mock_promote.assert_called_once_with("pipeline:run1", "CANDIDATE")

    @patch("evals.regression.promotion_gate.promote_artifact")
    def test_does_not_promote_when_all_metrics_are_none(self, mock_promote):
        result = mark_candidate_if_evaluated("pipeline:run1", {"false_novelty_rate": None})
        assert result["promoted"] is False
        mock_promote.assert_not_called()
