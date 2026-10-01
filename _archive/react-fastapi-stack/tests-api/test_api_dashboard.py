"""Tests for apps/api's Project Dashboard endpoint (Clinova Phase 5,
Epic 5.1). Against the real API + real Postgres."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


class DashboardRouteTests(unittest.TestCase):
    def test_real_project_has_a_basis_run_and_never_fabricates_a_sum(self):
        r = client.get("/api/projects")
        self.assertEqual(r.status_code, 200)
        projects = r.json()
        self.assertGreaterEqual(len(projects), 1)

        project_id = projects[0]["project_id"]
        d = client.get(f"/api/projects/{project_id}/dashboard").json()
        self.assertIsNotNone(d["basis_run"])
        # basis_note intentionally shows a short (8-char) run id prefix
        # for readability, matching this app's existing run-id-display
        # convention elsewhere -- not the full id.
        self.assertIn(d["basis_run"]["run_id"][:8], d["basis_note"])

    def test_unknown_project_returns_honest_empty_dashboard(self):
        d = client.get("/api/projects/does-not-exist-as-a-project/dashboard").json()
        self.assertIsNone(d["basis_run"])
        self.assertIsNotNone(d["empty_reason"])
        self.assertEqual(d["counts"], [])

    def test_research_confidence_tile_is_never_fabricated(self):
        projects = client.get("/api/projects").json()
        d = client.get(f"/api/projects/{projects[0]['project_id']}/dashboard").json()
        research = next(c for c in d["confidence"] if c["key"] == "research_confidence")
        self.assertFalse(research["recorded"])
        self.assertIsNone(research["value"])
        self.assertTrue(research["basis"])

    def test_insufficient_evidence_gaps_excluded_from_opportunities(self):
        projects = client.get("/api/projects").json()
        d = client.get(f"/api/projects/{projects[0]['project_id']}/dashboard").json()
        for gap in d["top_opportunities"]:
            self.assertNotEqual(gap["challenge"]["code"], "INSUFFICIENT_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
