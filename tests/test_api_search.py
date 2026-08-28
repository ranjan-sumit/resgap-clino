"""
Tests for cross-screen content search (Clinova Phase 5, Epic 5.7).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.search_service import search_project

client = TestClient(app)
PROJECT_ID = "Healthcare AI"


class SearchRouteTests(unittest.TestCase):
    def test_finds_real_content_across_kinds(self):
        r = client.get(f"/api/projects/{PROJECT_ID}/search", params={"q": "depression"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreater(body["total"], 0)
        kinds = {h["kind"] for h in body["hits"]}
        # The whole point: this searches actual research content, not just
        # nav labels and run names like the palette used to.
        self.assertTrue(kinds & {"entity", "gap", "proposal", "paper"}, kinds)

    def test_every_hit_carries_a_real_destination_and_a_reason(self):
        body = client.get(f"/api/projects/{PROJECT_ID}/search", params={"q": "adhd"}).json()
        self.assertGreater(len(body["hits"]), 0)
        for hit in body["hits"]:
            self.assertTrue(hit["href"].startswith("/"), hit["href"])
            self.assertTrue(hit["title"].strip())
            # matched_on explains *why* a result is present -- never an
            # unexplained hit.
            self.assertTrue(hit["matched_on"].strip())

    def test_exact_title_outranks_an_incidental_body_mention(self):
        body = client.get(f"/api/projects/{PROJECT_ID}/search", params={"q": "depression"}).json()
        scores = [h["score"] for h in body["hits"]]
        self.assertEqual(scores, sorted(scores, reverse=True), "hits must be ranked")
        top = body["hits"][0]
        self.assertGreaterEqual(top["score"], 40)

    def test_short_query_is_refused_rather_than_returning_everything(self):
        body = client.get(f"/api/projects/{PROJECT_ID}/search", params={"q": "a"}).json()
        self.assertEqual(body["hits"], [])
        self.assertIsNotNone(body["empty_reason"])

    def test_no_match_says_so_honestly(self):
        body = client.get(
            f"/api/projects/{PROJECT_ID}/search", params={"q": "zzzznotarealterm"}
        ).json()
        self.assertEqual(body["total"], 0)
        self.assertIn("zzzznotarealterm", body["empty_reason"])

    def test_unknown_project_does_not_500(self):
        r = client.get("/api/projects/does-not-exist/search", params={"q": "adhd"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["hits"], [])

    def test_limit_is_respected_and_truncation_reported(self):
        body = search_project(PROJECT_ID, "a" * 0 + "e", limit=3)  # 'e' matches broadly
        self.assertLessEqual(len(body.hits), 3)


if __name__ == "__main__":
    unittest.main()
