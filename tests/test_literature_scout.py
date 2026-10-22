"""
Literature Scout. A real run had EVERY gap come back "open, no papers found": whole-title queries,
arXiv for biomedicine, and a failed search read as an empty result. These tests pin the fixes.
"""
import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from pipeline import literature_scout as ls
from pipeline.literature_scout import (
    _assess, _fallback_queries, _merge, _search_europepmc, plan_queries, scout_gaps,
)
from tests.pg_test_utils import new_test_schema, drop_test_schema
from utils.azure_client import ErrorInfo, Failure, Success


def paper(title, year=2022, abstract="abs", source="Semantic Scholar"):
    return {"title": title, "year": year, "abstract": abstract, "citations": 1, "authors": [], "source": source}


def gap(i, title=None):
    return {"gap_id": f"gid{i}", "title": title or f"Airway chip gap {i}", "description": f"description {i}",
            "missing_connection": f"missing {i}"}


class FakeClient:
    def __init__(self, planner=None, assessor=None):
        self.planner, self.assessor, self.calls = planner, assessor, []

    def set_stage(self, s):
        pass

    def chat_json(self, system, user, **kw):
        if "Query Planner" in system:
            self.calls.append("plan")
            if self.planner == "fail":
                return Failure(ErrorInfo(kind="timeout", detail="x"))
            return Success(self.planner if isinstance(self.planner, str) else json.dumps(self.planner))
        self.calls.append("assess")
        if self.assessor == "fail":
            return Failure(ErrorInfo(kind="timeout", detail="x"))
        return Success(json.dumps(self.assessor or {"status": "open", "reasoning": "r", "relevant": []}))


def plan(*queries_per_gap):
    return {"queries": [{"id": f"G{i + 1}", "queries": qs} for i, qs in enumerate(queries_per_gap)]}


class _DB(unittest.TestCase):
    def setUp(self):
        self.schema = new_test_schema()
        self.p = patch.object(db, "_SCHEMA", self.schema)
        self.p.start()
        db._INITIALIZED.discard(self.schema)
        self.sleep = patch("pipeline.literature_scout.time.sleep")
        self.sleep.start()
        self.s2wait = patch("pipeline.literature_scout._s2_wait")
        self.s2wait.start()

    def tearDown(self):
        self.s2wait.stop()
        self.sleep.stop()
        self.p.stop()
        db._INITIALIZED.discard(self.schema)
        drop_test_schema(self.schema)


class PlannerTests(unittest.TestCase):
    def test_queries_come_back_keyed_by_gap_id_in_order(self):
        gaps = [gap(1), gap(2)]
        out, err = plan_queries(gaps, FakeClient(planner=plan(["a b c", "d e f"], ["x y z"])))
        self.assertIsNone(err)
        self.assertEqual(out, {"gid1": ["a b c", "d e f"], "gid2": ["x y z"]})

    def test_at_most_three_queries_and_blank_ones_dropped(self):
        out, _ = plan_queries([gap(1)], FakeClient(planner=plan(["a", " ", "b", "c", "d"])))
        self.assertEqual(out["gid1"], ["a", "b", "c"])

    def test_a_fenced_reply_is_read(self):
        out, err = plan_queries([gap(1)], FakeClient(planner="```json\n" + json.dumps(plan(["a b"])) + "\n```"))
        self.assertEqual(out["gid1"], ["a b"])

    def test_failure_and_garbage_are_reported_not_raised(self):
        self.assertEqual(plan_queries([gap(1)], FakeClient(planner="fail"))[1], "query planner failed: timeout")
        self.assertEqual(plan_queries([gap(1)], FakeClient(planner="not json"))[1], "query planner reply could not be read")

    def test_no_gaps_no_call(self):
        c = FakeClient()
        self.assertEqual(plan_queries([], c), ({}, None))
        self.assertEqual(c.calls, [])

    def test_fallback_queries_strip_gap_framing_and_stay_short(self):
        qs = _fallback_queries({"title": "Missing validation of mucoid Pseudomonas aeruginosa in airway chips under flow"})
        self.assertTrue(qs)
        self.assertNotIn("Missing", qs[0])
        self.assertLessEqual(len(qs[0].split()), 7)


class ProviderTests(unittest.TestCase):
    def test_europe_pmc_results_are_normalised(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"resultList": {"result": [
            {"title": "A chip study.", "pubYear": "2021", "abstractText": "<h4>Bg</h4> Text here", "citedByCount": 7,
             "authorString": "Smith J, Lee K, Park S, Chen L"},
            {"title": "", "pubYear": "2020"}]}}
        with patch("pipeline.literature_scout.requests.get", return_value=resp) as get:
            papers, ok = _search_europepmc("airway chip")
        self.assertTrue(ok)
        self.assertEqual(len(papers), 1)
        self.assertEqual((papers[0]["title"], papers[0]["year"], papers[0]["source"]), ("A chip study", 2021, "Europe PMC"))
        self.assertNotIn("<", papers[0]["abstract"])
        self.assertEqual(papers[0]["authors"], ["Smith J", "Lee K", "Park S"])
        self.assertEqual(get.call_args.kwargs["params"]["query"], "airway chip")

    def test_europe_pmc_records_without_a_real_title_are_skipped(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"resultList": {"result": [
            {"title": "Abstract", "pubYear": "2026"}, {"title": "Erratum", "pubYear": "2020"},
            {"title": "Short", "pubYear": "2020"},
            {"title": "A real study of airway chips in cystic fibrosis", "pubYear": "2021"}]}}
        with patch("pipeline.literature_scout.requests.get", return_value=resp):
            papers, _ = _search_europepmc("q")
        self.assertEqual([p["title"] for p in papers], ["A real study of airway chips in cystic fibrosis"])

    def test_europe_pmc_failure_is_reported_as_not_ok(self):
        with patch("pipeline.literature_scout.requests.get", side_effect=ConnectionError("down")):
            self.assertEqual(_search_europepmc("q"), ([], False))

    def test_merge_dedupes_by_title_keeping_the_longer_abstract(self):
        merged = _merge([paper("The Chip Paper", abstract="short"), paper("the chip paper!", abstract="a much longer abstract"),
                         paper("Other")])
        self.assertEqual(len(merged), 2)
        self.assertEqual(next(p for p in merged if "chip" in p["title"].lower())["abstract"], "a much longer abstract")


class AssessTests(unittest.TestCase):
    def test_no_papers_means_open_without_a_model_call(self):
        c = FakeClient()
        result, genuine = _assess(gap(1), [], c)
        self.assertEqual((result["status"], genuine), ("open", True))
        self.assertEqual(c.calls, [])

    def test_relevant_numbers_are_validated_and_capped(self):
        c = FakeClient(assessor={"status": "partial", "reasoning": "r", "relevant": [1, 99, "x", 2, 3, 4]})
        result, _ = _assess(gap(1), [paper(f"P{i}") for i in range(5)], c)
        self.assertEqual(result["relevant"], [1, 2, 3])

    def test_a_model_failure_gives_a_non_genuine_partial(self):
        result, genuine = _assess(gap(1), [paper("P")], FakeClient(assessor="fail"))
        self.assertEqual((result["status"], genuine), ("partial", False))

    def test_an_off_schema_answer_is_not_genuine(self):
        c = FakeClient(assessor={"status": "maybe"})
        self.assertFalse(_assess(gap(1), [paper("P")], c)[1])


class ScoutTests(_DB):
    def _run(self, gaps, client, s2=None, epmc=None, arxiv=None, **kw):
        s2 = s2 or (lambda q, k: ([paper("S2 hit " + q)], True))
        epmc = epmc or (lambda q, limit=6: ([paper("EPMC hit " + q, source="Europe PMC")], True))
        with patch("pipeline.literature_scout._search_s2", side_effect=s2) as m_s2, \
             patch("pipeline.literature_scout._search_europepmc", side_effect=epmc) as m_e, \
             patch("pipeline.academic_search._search_arxiv_with_status", side_effect=arxiv or (lambda q, limit=3: ([], True))) as m_a:
            out = scout_gaps(gaps, client, **kw)
        return out, m_s2, m_e, m_a

    def test_every_planned_query_goes_to_semantic_scholar_and_europe_pmc(self):
        g = gap(1)
        out, m_s2, m_e, m_a = self._run([g], FakeClient(planner=plan(["q one", "q two", "q three"])))
        self.assertEqual(m_s2.call_count, 3)
        self.assertEqual(m_e.call_count, 3)
        m_a.assert_not_called()                                            # arXiv off for biomedical corpora
        self.assertEqual(g["search_query_used"], "q one | q two | q three")
        self.assertEqual(g["search_providers"], {"semantic_scholar": True, "europe_pmc": True})
        self.assertEqual(g["papers_considered"], 6)

    def test_arxiv_gets_only_the_first_query_and_only_when_asked(self):
        _, _, _, m_a = self._run([gap(1)], FakeClient(planner=plan(["q one", "q two"])), use_arxiv=True)
        self.assertEqual(m_a.call_count, 1)
        self.assertEqual(m_a.call_args.args[0], "q one")

    def test_the_assessor_decides_and_the_relevant_papers_come_first(self):
        g = gap(1)
        client = FakeClient(planner=plan(["q"]), assessor={"status": "partial", "reasoning": "closest is P2", "relevant": [2]})
        s2 = lambda q, k: ([paper("P1"), paper("P2")], True)
        self._run([g], client, s2=s2, epmc=lambda q, limit=6: ([], True))
        self.assertEqual(g["validation_status"], "partial")
        self.assertEqual(g["existing_papers"][0]["title"], "P2")

    def test_when_every_provider_fails_the_gap_is_unverified_never_open_and_not_cached(self):
        g = gap(1)
        client = FakeClient(planner=plan(["q"]))
        fail = lambda q, k=None, limit=None: ([], False)
        out, *_ = self._run([g], client, s2=fail, epmc=fail)
        self.assertEqual(g["validation_status"], "unverified")
        self.assertEqual(out["diagnostics"]["unverified"], 1)
        self.assertNotIn("assess", client.calls)
        # nothing was cached: a second run searches again
        g2 = gap(1)
        _, m_s2, _, _ = self._run([g2], FakeClient(planner=plan(["q"])), s2=fail, epmc=fail)
        self.assertEqual(m_s2.call_count, 1)

    def test_one_provider_failing_still_assesses_but_notes_it_and_does_not_cache(self):
        g = gap(1)
        client = FakeClient(planner=plan(["q"]))
        self._run([g], client, s2=lambda q, k: ([], False))
        self.assertIn("assess", client.calls)
        self.assertIn("incomplete", g["validation_reasoning"])
        self.assertIn("semantic scholar", g["validation_reasoning"])
        g2 = gap(1)
        _, _, m_e, _ = self._run([g2], FakeClient(planner=plan(["q"])), s2=lambda q, k: ([], False))
        self.assertEqual(m_e.call_count, 1)                              # searched again: not served from cache

    def test_a_clean_result_is_cached_and_not_searched_twice(self):
        client = FakeClient(planner=plan(["q"]))
        self._run([gap(1)], client)
        g2 = gap(1)
        out, m_s2, _, _ = self._run([g2], FakeClient(planner=plan(["q"])))
        m_s2.assert_not_called()
        self.assertEqual(out["diagnostics"]["cache_hits"], 1)
        self.assertEqual(g2["validation_status"], "open")

    def test_a_failed_planner_falls_back_to_title_keywords(self):
        g = gap(1, "Evaluating mucoid Pseudomonas aeruginosa strains in advanced airway chips")
        out, m_s2, _, _ = self._run([g], FakeClient(planner="fail"))
        self.assertEqual(out["diagnostics"]["planner_error"], "query planner failed: timeout")
        self.assertGreaterEqual(m_s2.call_count, 1)
        self.assertIn("mucoid", g["search_query_used"])

    def test_progress_is_reported_for_every_gap(self):
        seen = []
        self._run([gap(1), gap(2)], FakeClient(planner=plan(["a"], ["b"])), progress_callback=lambda d, n: seen.append((d, n)))
        self.assertEqual(seen, [(0, 2), (1, 2), (2, 2)])      # starts at 0, ends at all done

    def test_gaps_keep_their_order(self):
        gaps = [gap(1), gap(2), gap(3)]
        out, *_ = self._run(gaps, FakeClient(planner=plan(["a"], ["b"], ["c"])))
        self.assertEqual([g["gap_id"] for g in out["gaps"]], ["gid1", "gid2", "gid3"])


if __name__ == "__main__":
    unittest.main()
