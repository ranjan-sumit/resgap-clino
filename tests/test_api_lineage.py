"""Tests for apps/api's Lineage endpoints (Clinova Phase 5, Epic 5.1).
Against the real API + real Postgres."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)

_RUN_WITH_BACKFILLED_ARTIFACT = "b18ae1c95838"


class LineageRouteTests(unittest.TestCase):
    def test_technical_lineage_never_crashes_on_a_run_with_no_spine(self):
        r = client.get(f"/api/runs/{_RUN_WITH_BACKFILLED_ARTIFACT}/lineage/technical")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsNone(body["root"])  # honest -- no full spine was ever recorded for this run

    def test_scientific_lineage_excludes_gaps_without_identity_and_reports_count(self):
        r = client.get(f"/api/runs/{_RUN_WITH_BACKFILLED_ARTIFACT}/lineage/scientific")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreater(body["n_gaps_without_identity"], 0)
        self.assertIsNotNone(body["identity_note"])
        # No gap in the returned list should be missing a real gap_id.
        for g in body["gaps"]:
            self.assertIsNotNone(g["gap_id"])

    def test_unknown_run_returns_404(self):
        r = client.get("/api/runs/does-not-exist/lineage/scientific")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
