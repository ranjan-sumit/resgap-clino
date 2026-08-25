"""
Tests for the Phase 5 Slice 2 API surface added alongside the visual
redesign (Corpus, Evidence, Knowledge Graph, Gap Challenger, Research
Council, Versions/Artifacts, and the promote write path) -- Clinova Phase
5, Epics 5.2-5.4. Same discipline as test_api_runs.py: FastAPI's
TestClient against the real API + real Postgres, no mocking the DB layer.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.measures import graph_confidence
from utils.database import _get_conn, init_db

client = TestClient(app)

# The one real project this whole session's data lives under -- same
# fixture project every other apps/api test file already assumes.
PROJECT_ID = "Healthcare AI"


class GraphConfidenceTests(unittest.TestCase):
    """Regression test for a real bug found via screenshot review: an older
    run with a populated results["graph"] but no results["graph_quality"]
    (it predates Epic 3.1 scoring) was reporting "No knowledge graph was
    built for this run" -- factually wrong, since the graph genuinely
    exists. Must distinguish "no graph" from "graph exists, unscored"."""

    def test_graph_exists_but_unscored_says_so_honestly(self):
        results = {"graph": {"stats": {"entity_count": 61, "relationship_count": 61}}}
        m = graph_confidence(results)
        self.assertFalse(m.recorded)
        self.assertIn("61 entities", m.basis)
        self.assertNotIn("No knowledge graph was built", m.basis)

    def test_genuinely_no_graph_says_so(self):
        m = graph_confidence({})
        self.assertFalse(m.recorded)
        self.assertIn("No knowledge graph was built", m.basis)

    def test_scored_graph_still_uses_the_real_quality_score(self):
        results = {"graph_quality": {"quality_score": 0.9, "build_status": "CLEAN",
                                       "entity_count": 10, "relationship_count": 8}}
        m = graph_confidence(results)
        self.assertTrue(m.recorded)
        self.assertEqual(m.value, 0.9)


class CorpusRouteTests(unittest.TestCase):
    def test_returns_real_papers_and_ordered_reference_funnel(self):
        r = client.get(f"/api/projects/{PROJECT_ID}/corpus")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreaterEqual(len(body["papers"]), 1)
        # reference_funnel must be an ORDERED list (Postgres JSONB does not
        # preserve dict key order on round-trip -- a real bug this model
        # was specifically designed to avoid reintroducing).
        self.assertIsInstance(body["reference_funnel"], list)
        if body["reference_funnel"]:
            self.assertIn("key", body["reference_funnel"][0])
            self.assertIn("label", body["reference_funnel"][0])

    def test_unknown_project_reports_empty_reason_not_a_500(self):
        r = client.get("/api/projects/does-not-exist/corpus")
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.json()["empty_reason"])


class EvidenceRouteTests(unittest.TestCase):
    def test_returns_real_evidence_items(self):
        r = client.get(f"/api/projects/{PROJECT_ID}/evidence")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreaterEqual(len(body["items"]), 1)
        item = body["items"][0]
        self.assertIn(item["evidence_type"], (
            "ResearchQuestion", "Problem", "StudyDesign", "DatasetPopulation",
            "InterventionModel", "ComparatorBaseline", "Method", "Metric",
            "Result", "Finding", "Limitation", "FutureWork", "Claim",
        ))


class GraphRouteTests(unittest.TestCase):
    def test_returns_real_entities_and_counts(self):
        r = client.get(f"/api/projects/{PROJECT_ID}/graph")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreaterEqual(len(body["entities"]), 1)
        count_keys = {c["key"] for c in body["counts"]}
        self.assertIn("entities", count_keys)
        self.assertIn("relationships", count_keys)


class ChallengerRouteTests(unittest.TestCase):
    def test_every_gap_has_a_status_chip_even_when_not_challenged(self):
        r = client.get(f"/api/projects/{PROJECT_ID}/challenger")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreaterEqual(len(body["gaps"]), 1)
        for g in body["gaps"]:
            self.assertTrue(g["status"]["label"])
            self.assertTrue(g["status"]["reason"])


class CouncilRouteTests(unittest.TestCase):
    def test_finds_the_real_computational_lab_run_not_the_newest_run(self):
        r = client.get(f"/api/projects/{PROJECT_ID}/council")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # The project's newest run overall has no comp_results -- this
        # must resolve to the older run that actually ran the lab, not
        # dashboard_service's basis_run.
        if body["run"] is not None:
            self.assertIn("Computational Lab", body["run"]["name"])
            self.assertGreater(len(body["params_summary"]), 0)

    def test_model_results_are_parsed_into_real_scenario_tables(self):
        """The computational-modelling view this was missing entirely --
        each model's headline_numbers must come back decoded into real
        scenario -> metric tables, not the pipeline's raw encoded keys."""
        r = client.get(f"/api/projects/{PROJECT_ID}/council")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        if not body["models_run"]:
            self.skipTest("no real Computational Lab run with model results in this dataset")
        for model in body["models_run"]:
            self.assertTrue(model["model_used"])
            self.assertTrue(model["metrics_by_scenario"])
            for scenario, metrics in model["metrics_by_scenario"].items():
                self.assertTrue(scenario)
                for metric_label in metrics:
                    # Decoded to a human label, not a raw "base_case_x_mean" key.
                    self.assertNotIn("_", metric_label)
        for driver in body["sensitivity_ranking"]:
            self.assertTrue(driver["parameter"])
            self.assertIsInstance(driver["importance"], (int, float))


class ArtifactsRouteTests(unittest.TestCase):
    def test_lists_real_registered_artifacts(self):
        r = client.get("/api/artifacts")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreaterEqual(len(body["artifacts"]), 1)
        for a in body["artifacts"]:
            self.assertTrue(a["status"]["label"])
            self.assertIsInstance(a["next_legal_statuses"], list)


class PromoteRouteTests(unittest.TestCase):
    """Exercises the real write path against a throwaway artifact, never
    the real pipeline:<run_id> champions other tests/screenshots rely on
    -- promoting one of those to ARCHIVED would be irreversible."""

    TEST_RUN_ID = "pytest_promote_throwaway"
    ARTIFACT_ID = f"pipeline:{TEST_RUN_ID}"

    def setUp(self):
        init_db()
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO research_artifacts
               (artifact_id, artifact_type, artifact_version, project_id, run_id, content_hash, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (artifact_id) DO UPDATE SET status = EXCLUDED.status""",
            (self.ARTIFACT_ID, "pipeline", "1", PROJECT_ID, self.TEST_RUN_ID, "deadbeef", "EXPERIMENTAL"),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM research_artifacts WHERE artifact_id = %s", (self.ARTIFACT_ID,))
        conn.commit()
        conn.close()

    def test_legal_transition_succeeds(self):
        r = client.post(f"/api/runs/{self.TEST_RUN_ID}/promote?to_status=CANDIDATE")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"]["code"], "CANDIDATE")

    def test_illegal_transition_returns_400_not_500(self):
        # EXPERIMENTAL -> CHAMPION skips CANDIDATE -- the lifecycle rule
        # this whole endpoint exists to enforce, not bypass.
        r = client.post(f"/api/runs/{self.TEST_RUN_ID}/promote?to_status=CHAMPION")
        self.assertEqual(r.status_code, 400)
        self.assertIn("EXPERIMENTAL", r.json()["detail"])
        self.assertIn("CHAMPION", r.json()["detail"])

    def test_unknown_run_returns_404(self):
        r = client.post("/api/runs/this-run-does-not-exist/promote?to_status=CANDIDATE")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
