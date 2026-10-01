"""
Tests for the workspace re-converge (Clinova Phase 5, Slice 15).

The React app had spread one coherent workspace across nineteen routes, which
made it measurably worse to use than the Streamlit app it was meant to
replace. These cover the three mechanisms that fixed it -- a run switcher that
pins every tab to one run, slim endpoints for the screens that render on every
page, and bulk database reads -- plus the honesty rules that had to survive
the restructure.
"""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.project_runs import get_basis, list_project_runs
from utils.database import get_run_manifests_bulk, list_runs, load_run_gate_fields_bulk

client = TestClient(app)
PROJECT = "Healthcare AI"


def _two_runs() -> list[dict]:
    runs = list_project_runs(PROJECT)
    if len(runs) < 2:
        raise unittest.SkipTest("needs at least two runs in the project")
    return runs


class RunPinningTests(unittest.TestCase):
    """One run switcher must move every tab at once. Before this, each screen
    independently showed "whatever ran last" and there was no way to look at
    an older run without leaving the screen you were on."""

    def test_run_id_actually_changes_which_run_is_returned(self):
        runs = _two_runs()
        newest, older = runs[0], runs[1]
        for path in ("corpus", "evidence", "graph", "quality", "dashboard", "workspace"):
            with self.subTest(endpoint=path):
                body = client.get(f"/api/projects/{PROJECT}/{path}",
                                   params={"run_id": older["id"]}).json()
                self.assertEqual(body["basis_run"]["run_id"], older["id"], path)
                self.assertNotEqual(body["basis_run"]["run_id"], newest["id"], path)

    def test_omitting_run_id_still_means_most_recent(self):
        newest = _two_runs()[0]
        body = client.get(f"/api/projects/{PROJECT}/corpus").json()
        self.assertEqual(body["basis_run"]["run_id"], newest["id"])

    def test_basis_note_stops_claiming_most_recent_when_it_is_not(self):
        # This sentence was hardcoded in seven services and became false the
        # moment a run switcher existed. It now comes from one place and
        # reflects which run is actually shown.
        runs = _two_runs()
        latest = client.get(f"/api/projects/{PROJECT}/corpus").json()["basis_note"]
        pinned = client.get(f"/api/projects/{PROJECT}/corpus",
                             params={"run_id": runs[1]["id"]}).json()["basis_note"]
        self.assertIn("most recent run", latest)
        self.assertNotIn("most recent run", pinned)
        self.assertIn("earlier run", pinned)

    def test_unknown_run_id_falls_back_rather_than_404s(self):
        # The id arrives from a URL a user can edit or bookmark; a stale
        # bookmark should land on real data.
        newest = _two_runs()[0]
        r = client.get(f"/api/projects/{PROJECT}/corpus", params={"run_id": "not-a-real-run"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["basis_run"]["run_id"], newest["id"])

    def test_get_basis_reports_whether_it_is_the_latest(self):
        runs = _two_runs()
        self.assertTrue(get_basis(PROJECT).is_latest)
        self.assertTrue(get_basis(PROJECT, runs[0]["id"]).is_latest)
        self.assertFalse(get_basis(PROJECT, runs[1]["id"]).is_latest)


class CouncilPinningTests(unittest.TestCase):
    def test_a_pinned_run_without_council_output_names_one_that_has_it(self):
        """A dead end became a next step. "Another run may have" was true but
        useless -- it left the reader to open every run to find out which."""
        runs = list_project_runs(PROJECT)
        without = next((r for r in runs if not r.get("has_comp")), None)
        with_comp = next((r for r in runs if r.get("has_comp")), None)
        if without is None or with_comp is None:
            self.skipTest("needs one run with and one without Computational Lab output")

        body = client.get(f"/api/projects/{PROJECT}/council",
                           params={"run_id": without["id"]}).json()
        self.assertIsNone(body["basis_run"])
        self.assertIn(with_comp["name"], body["empty_reason"])

    def test_an_unresolvable_run_id_does_not_produce_a_false_claim(self):
        """Honouring an unmatched id literally made this service state "No run
        in this project has used the Computational Lab" while a run that had
        was sitting in the list."""
        runs = list_project_runs(PROJECT)
        if not any(r.get("has_comp") for r in runs):
            self.skipTest("no Computational Lab run in this project")
        body = client.get(f"/api/projects/{PROJECT}/council",
                           params={"run_id": "916eb348"}).json()  # a truncated id
        self.assertNotIn("No run in this project has used", body.get("empty_reason") or "")


class FieldNamingTests(unittest.TestCase):
    def test_every_project_scoped_view_names_its_run_the_same_way(self):
        """Four models called this field `run` and four called it `basis_run`,
        so no caller could rely on either. Found by a test that tried to
        assert across all of them; renamed to basis_run everywhere."""
        for path in ("corpus", "quality", "evidence", "graph",
                      "challenger", "council", "dashboard", "workspace"):
            with self.subTest(endpoint=path):
                body = client.get(f"/api/projects/{PROJECT}/{path}").json()
                self.assertIn("basis_run", body, path)
                self.assertNotIn("run", body, f"{path} still uses the old name")


class SlimEndpointTests(unittest.TestCase):
    """Two endpoints render on the app's most-visited paths. Both previously
    reused a heavier model and paid for fields they never displayed."""

    def test_run_options_carries_what_the_switcher_shows_and_no_more(self):
        rows = client.get("/api/run-options", params={"limit": 25}).json()
        self.assertGreater(len(rows), 0)
        self.assertEqual(
            set(rows[0]),
            {"run_id", "name", "created_at", "project_id", "n_papers", "n_gaps"},
        )

    def test_run_options_is_not_shadowed_by_the_run_detail_route(self):
        # /runs/options would be captured by GET /runs/{run_id} -- the same
        # collision that sent /api/runs/jobs to a run-detail 404 in Slice 10.
        self.assertIsInstance(client.get("/api/run-options").json(), list)

    def test_workspace_header_matches_the_dashboard_it_replaced(self):
        header = client.get(f"/api/projects/{PROJECT}/workspace").json()
        dash = client.get(f"/api/projects/{PROJECT}/dashboard").json()
        self.assertEqual(header["basis_run"], dash["basis_run"])
        self.assertEqual(header["counts"], dash["counts"])
        self.assertEqual(header["confidence"], dash["confidence"])

    def test_workspace_header_is_materially_faster_than_the_dashboard(self):
        # The point of the endpoint. Measured ~1.3s vs ~7.5s; asserting a
        # generous ratio so this fails on a regression, not on machine noise.
        t0 = time.perf_counter()
        client.get(f"/api/projects/{PROJECT}/workspace")
        header_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        client.get(f"/api/projects/{PROJECT}/dashboard")
        dash_s = time.perf_counter() - t0

        self.assertLess(header_s, dash_s, f"header {header_s:.2f}s vs dashboard {dash_s:.2f}s")


class BulkReadTests(unittest.TestCase):
    """utils/database._get_conn() opens and closes a connection per call at
    ~0.75s, so the per-run pattern spent seconds in setup alone."""

    def test_bulk_gate_fields_match_the_per_run_read(self):
        from utils.database import load_run
        ids = [r["id"] for r in list_runs(limit=5)]
        bulk = load_run_gate_fields_bulk(ids)
        self.assertEqual(set(bulk), set(ids))
        for run_id in ids:
            results = (load_run(run_id) or {}).get("results", {}) or {}
            self.assertEqual(bulk[run_id]["gate_blocked"], results.get("gate_blocked"))

    def test_bulk_manifests_omit_runs_that_have_none(self):
        # Absent must mean "no manifest row", which derive_run_status renders
        # as NO_MANIFEST -- a real state, not a lookup failure.
        ids = [r["id"] for r in list_runs(limit=5)]
        manifests = get_run_manifests_bulk(ids)
        self.assertTrue(set(manifests).issubset(set(ids)))

    def test_bulk_readers_are_safe_on_an_empty_list(self):
        self.assertEqual(load_run_gate_fields_bulk([]), {})
        self.assertEqual(get_run_manifests_bulk([]), {})

    def test_run_list_statuses_are_unchanged_by_the_bulk_path(self):
        from apps.api.services.run_status import derive_run_status
        from apps.api.services.runs_service import list_run_summaries
        from utils.database import get_run_manifest, load_run

        summaries = list_run_summaries(limit=5)
        for s in summaries:
            expected = derive_run_status(
                (load_run(s.run_id) or {}).get("results", {}) or {},
                get_run_manifest(s.run_id),
            )
            self.assertEqual(s.status.code, expected.code, s.run_id)


if __name__ == "__main__":
    unittest.main()
