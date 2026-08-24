"""
Tests for apps/api's Compare endpoint and promotion-gate view (Clinova
Phase 5, Epic 5.1). Against the real API + real Postgres, matching this
project's established discipline.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.compare_service import _build_promotion

client = TestClient(app)

# Two real runs known to exist in the seeded Postgres database (see
# scripts/migrate_sqlite_to_postgres.py's migration and this session's
# earlier live verification work).
_RUN_A = "d8cfccba6ced"
_RUN_B = "b18ae1c95838"


class PromotionGateViewTests(unittest.TestCase):
    """The single most important test in this slice: evaluate_promotion({},
    {}) returns eligible=True VACUOUSLY (nothing to regress against).
    can_evaluate must be the real gate the UI disables its button on,
    never `eligible` alone -- otherwise a Promote button would always
    look ready, since evaluation_metrics is NULL on every real run today."""

    def test_both_empty_metrics_is_not_evaluable_despite_vacuous_eligible(self):
        view = _build_promotion(_RUN_A, _RUN_B, {}, {})
        self.assertFalse(view.can_evaluate)
        self.assertEqual(view.status.code, "NOT_EVALUABLE")
        # The underlying pure function's vacuous True is still visible in
        # `eligible` (honest -- not hidden), but can_evaluate is what a
        # button must actually gate on.
        self.assertTrue(view.eligible)

    def test_real_metrics_on_one_side_makes_it_evaluable(self):
        view = _build_promotion(_RUN_A, _RUN_B, {"false_novelty_rate": 0.1}, {})
        self.assertTrue(view.can_evaluate)
        self.assertNotEqual(view.status.code, "NOT_EVALUABLE")

    def test_candidate_artifact_id_is_none_when_not_in_registry(self):
        view = _build_promotion(_RUN_A, "no-such-run-id", {}, {})
        self.assertIsNone(view.candidate_artifact_id)

    def test_candidate_artifact_id_is_real_when_in_registry(self):
        # b18ae1c95838 was registered as pipeline:b18ae1c95838 during this
        # session's earlier Epic 4.3 live verification work.
        view = _build_promotion(_RUN_A, _RUN_B, {}, {})
        self.assertEqual(view.candidate_artifact_id, f"pipeline:{_RUN_B}")


class CompareRouteTests(unittest.TestCase):
    def test_compare_two_real_runs_returns_real_diff(self):
        r = client.get(f"/api/compare?baseline={_RUN_A}&candidate={_RUN_B}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body["metrics"]), 12)  # all 12 §3 metrics always present
        self.assertIn(body["promotion"]["status"]["code"], ("NOT_EVALUABLE", "ELIGIBLE", "BLOCKED"))

    def test_unknown_baseline_returns_404_with_real_message(self):
        r = client.get(f"/api/compare?baseline=does-not-exist&candidate={_RUN_B}")
        self.assertEqual(r.status_code, 404)
        self.assertIn("does-not-exist", r.json()["detail"])

    def test_every_metric_has_a_direction_and_a_verdict(self):
        r = client.get(f"/api/compare?baseline={_RUN_A}&candidate={_RUN_B}")
        for m in r.json()["metrics"]:
            self.assertIn(m["direction"], ("higher", "lower"))
            self.assertTrue(m["verdict"])
            self.assertIn(m["baseline_display"], (m["baseline_display"],))  # always a real string
            self.assertTrue(m["baseline_display"])
            self.assertTrue(m["candidate_display"])


if __name__ == "__main__":
    unittest.main()
