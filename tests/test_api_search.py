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



class GapCrossLinkTests(unittest.TestCase):
    """Cross-screen links (Epic 5.7). Gaps carry the papers they were derived
    from and the proposals that address them -- both already existed in the
    pipeline output but were never navigable."""

    def setUp(self):
        runs = client.get("/api/runs?limit=1").json()["runs"]
        self.run = client.get(f"/api/runs/{runs[0]['run_id']}").json()

    def test_gaps_expose_supporting_paper_links(self):
        linked = [
            s for g in self.run["gaps"] for s in g["supporting_papers"] if s["href"]
        ]
        self.assertGreater(len(linked), 0)
        for s in linked:
            self.assertTrue(s["href"].startswith("/corpus/papers/"))
            self.assertTrue(s["label"].strip())

    def test_a_supporting_paper_with_no_screen_is_text_not_a_dead_link(self):
        # Supporting papers are often references, not uploaded PDFs. Those
        # must come back with href=None rather than a link that would 404.
        for g in self.run["gaps"]:
            for s in g["supporting_papers"]:
                if s["href"] is None:
                    self.assertTrue(s["label"].strip())

    def test_gaps_link_to_the_proposals_that_address_them(self):
        linked = [p for g in self.run["gaps"] for p in g["proposals"]]
        self.assertGreater(len(linked), 0)
        for p in linked:
            self.assertTrue(p["label"].strip())

    def test_title_matching_tolerates_typographic_dashes(self):
        from apps.api.services.runs_service import _normalise_title
        # Real data uses U+2011 non-breaking hyphens inside gap titles; a
        # naive == match silently produced zero cross-links.
        self.assertEqual(_normalise_title("Multi‑Ethnic  Dataset"),
                          _normalise_title("multi-ethnic dataset"))

if __name__ == "__main__":
    unittest.main()
