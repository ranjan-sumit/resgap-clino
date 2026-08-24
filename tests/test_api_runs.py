"""
Tests for apps/api (Clinova Phase 5, Epic 5.1). `derive_run_status` is
tested as pure unit tests (hand-built dicts, no DB). The route-level
tests use FastAPI's TestClient against the REAL API + real Postgres --
matching this project's established discipline of not mocking the
database layer.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.run_status import derive_run_status, trace_status_chip

client = TestClient(app)


class DeriveRunStatusTests(unittest.TestCase):
    def test_gate_blocked_takes_priority_over_everything(self):
        results = {"gate_blocked": True, "gate_block_reasons": ["extraction completeness too low"]}
        manifest = {"warnings": [], "quality_gate_results": {"corpus": "PASS", "graph": "CLEAN"}}
        chip = derive_run_status(results, manifest)
        self.assertEqual(chip.code, "GATE_BLOCKED")
        self.assertNotEqual(chip.code, "COMPLETED")
        self.assertIn("extraction completeness too low", chip.reason)

    def test_no_manifest_is_distinct_and_does_not_raise(self):
        chip = derive_run_status({}, None)
        self.assertEqual(chip.code, "NO_MANIFEST")
        self.assertEqual(chip.tone, "unknown")

    def test_warnings_produce_completed_with_warnings(self):
        manifest = {"warnings": ["Graph persistence failed"], "quality_gate_results": {}}
        chip = derive_run_status({}, manifest)
        self.assertEqual(chip.code, "COMPLETED_WITH_WARNINGS")
        self.assertIn("Graph persistence failed", chip.reason)

    def test_degraded_quality_gates_detected(self):
        manifest = {"warnings": [], "quality_gate_results": {"corpus": "FAIL", "graph": "CLEAN"}}
        chip = derive_run_status({}, manifest)
        self.assertEqual(chip.code, "COMPLETED_DEGRADED")

    def test_clean_completion(self):
        manifest = {"warnings": [], "quality_gate_results": {"corpus": "PASS", "graph": "CLEAN"}}
        chip = derive_run_status({}, manifest)
        self.assertEqual(chip.code, "COMPLETED")
        self.assertEqual(chip.tone, "positive")

    def test_never_returns_a_running_or_queued_state(self):
        for results, manifest in [
            ({}, None), ({"gate_blocked": True}, None),
            ({}, {"warnings": [], "quality_gate_results": {}}),
        ]:
            chip = derive_run_status(results, manifest)
            self.assertNotIn(chip.code, ("RUNNING", "QUEUED", "IN_PROGRESS"))


class TraceStatusChipTests(unittest.TestCase):
    def test_known_emoji_map_correctly(self):
        self.assertEqual(trace_status_chip("✅").tone, "positive")
        self.assertEqual(trace_status_chip("⚠️").tone, "caution")
        self.assertEqual(trace_status_chip("❌").tone, "critical")

    def test_unknown_or_missing_emoji_is_honest_unknown(self):
        self.assertEqual(trace_status_chip(None).code, "UNKNOWN")
        self.assertEqual(trace_status_chip("🎉").code, "UNKNOWN")


class RunsRouteTests(unittest.TestCase):
    def test_health_reports_real_db_connection(self):
        r = client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["database"], "ok")

    def test_list_runs_returns_real_data(self):
        r = client.get("/api/runs?limit=50")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreaterEqual(len(body["runs"]), 1)

    def test_unknown_run_returns_404_naming_the_run_id(self):
        r = client.get("/api/runs/this-run-id-does-not-exist")
        self.assertEqual(r.status_code, 404)
        self.assertIn("this-run-id-does-not-exist", r.json()["detail"])

    def test_every_status_chip_in_run_list_has_label_and_reason(self):
        """The machine-checkable form of NFR-8: never a bare status."""
        r = client.get("/api/runs?limit=50")
        for run in r.json()["runs"]:
            chip = run["status"]
            self.assertTrue(chip["label"])
            self.assertTrue(chip["reason"])
            for g in run["quality_gates"]:
                self.assertTrue(g["label"])
                self.assertTrue(g["reason"])

    def test_every_unrecorded_measure_has_a_basis(self):
        r = client.get("/api/runs?limit=50")
        self.assertEqual(r.status_code, 200)
        # Version fields carry the same recorded+reason contract as Measures.
        for run in r.json()["runs"]:
            for v in run["versions"]:
                if not v["recorded"]:
                    self.assertTrue(v["note"], f"unrecorded version field {v['key']} has no note")


if __name__ == "__main__":
    unittest.main()
