import json
import threading
import time
from unittest.mock import patch

import pytest

import utils.database as db
from pipeline import literature_scout as ls
from utils.azure_client import Success


class ScoutClient:
    """Answers the planner with two queries per gap and the assessor with 'partial'."""

    def __init__(self):
        self.lock = threading.Lock()
        self.assess_calls = 0

    def set_stage(self, s):
        pass

    def chat_json(self, system, user, **kw):
        if "Query Planner" in system:
            n = user.count('"title"')
            return Success(json.dumps({"queries": [{"id": f"G{i + 1}", "queries": [f"q{i}a", f"q{i}b"]}
                                                   for i in range(n)]}))
        with self.lock:
            self.assess_calls += 1
        return Success(json.dumps({"status": "partial", "reasoning": "related", "relevant": [1]}))


def gaps(n):
    return [{"gap_id": f"g{i}", "title": f"Gap number {i} about topic {i}", "description": f"desc {i}"} for i in range(n)]


def paper(title, doi=None, url=None, source="Semantic Scholar", abstract="abs"):
    return {"title": title, "year": 2022, "abstract": abstract, "source": source, "doi": doi, "url": url}


@pytest.fixture(autouse=True)
def _no_pacing():
    with patch("pipeline.literature_scout._s2_wait"), patch("pipeline.literature_scout.time.sleep"):
        yield


def test_eight_gaps_take_under_half_the_sequential_time(isolated_env):
    delay = 0.08

    def slow_s2(q, key):
        time.sleep(delay)
        return [paper(f"S2 hit for {q} paper")], True

    def slow_epmc(q, limit=6):
        time.sleep(delay)
        return [paper(f"EPMC hit for {q} paper", source="Europe PMC")], True

    with patch("pipeline.literature_scout._search_s2", slow_s2), patch("pipeline.literature_scout._search_europepmc", slow_epmc):
        start = time.time()
        out = ls.scout_gaps(gaps(8), ScoutClient())
        elapsed = time.time() - start
    sequential = 8 * 2 * 2 * delay            # 8 gaps x 2 queries x 2 providers, one after another
    assert elapsed < sequential / 2, (elapsed, sequential)
    assert out["diagnostics"]["searched"] == 8
    assert all(g["validation_status"] == "partial" for g in out["gaps"])


def test_results_keep_gap_order_and_each_gap_gets_its_own_papers(isolated_env):
    with patch("pipeline.literature_scout._search_s2", lambda q, k: ([paper(f"Paper for {q} here")], True)), \
         patch("pipeline.literature_scout._search_europepmc", lambda q, limit=6: ([], True)):
        out = ls.scout_gaps(gaps(4), ScoutClient())
    assert [g["gap_id"] for g in out["gaps"]] == ["g0", "g1", "g2", "g3"]
    assert "q2a" in out["gaps"][2]["existing_papers"][0]["title"] or "q2b" in out["gaps"][2]["existing_papers"][0]["title"]


def test_found_papers_carry_url_and_doi(isolated_env):
    s2 = [paper("A paper with a DOI and a url", doi="10.1/abc", url="https://www.semanticscholar.org/paper/x")]
    em = [paper("Another paper with a DOI present", doi="10.2/def", url="https://doi.org/10.2/def", source="Europe PMC")]
    with patch("pipeline.literature_scout._search_s2", lambda q, k: (s2, True)), \
         patch("pipeline.literature_scout._search_europepmc", lambda q, limit=6: (em, True)):
        out = ls.scout_gaps(gaps(1), ScoutClient())
    papers = out["gaps"][0]["existing_papers"]
    assert papers and all(p["url"] and p["doi"] for p in papers)


def test_europe_pmc_records_get_a_doi_url_or_an_article_url():
    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"resultList": {"result": [
            {"title": "A long enough title about CFTR", "doi": "10.1/x", "pubYear": "2021"},
            {"title": "Another long enough title here", "source": "MED", "id": "12345", "pubYear": "2020"}]}}
    with patch("pipeline.literature_scout.requests.get", return_value=Resp()):
        papers, ok = ls._search_europepmc("q")
    assert papers[0]["url"] == "https://doi.org/10.1/x" and papers[0]["doi"] == "10.1/x"
    assert papers[1]["url"] == "https://europepmc.org/article/MED/12345"


def test_the_same_doi_from_two_providers_is_one_paper_with_the_longer_abstract():
    a = paper("CFTR modulators in airway chips", doi="https://doi.org/10.1/ABC", abstract="short")
    b = paper("CFTR Modulators in Airway-Chips (preprint title differs)", doi="10.1/abc", url="https://x", abstract="a much longer abstract")
    merged = ls._merge([a, b])
    assert len(merged) == 1 and merged[0]["abstract"] == "a much longer abstract" and merged[0]["url"] == "https://x"


def test_same_title_without_doi_still_merges_and_distinct_papers_stay():
    merged = ls._merge([paper("Same Title"), paper("same  title!"), paper("A different paper title")])
    assert len(merged) == 2


def test_a_cached_verdict_expires_and_is_searched_again(isolated_env):
    calls = []

    def s2(q, k):
        calls.append(q)
        return [paper("Some related paper title")], True

    clock = [1_000_000.0]
    with patch("pipeline.literature_scout._search_s2", s2), \
         patch("pipeline.literature_scout._search_europepmc", lambda q, limit=6: ([], True)):
        first = ls.scout_gaps(gaps(1), ScoutClient(), now=lambda: clock[0])
        n_first = len(calls)
        again = ls.scout_gaps(gaps(1), ScoutClient(), now=lambda: clock[0] + 5 * 24 * 3600)
        assert again["diagnostics"]["cache_hits"] == 1 and len(calls) == n_first      # fresh: served from cache
        late = ls.scout_gaps(gaps(1), ScoutClient(), now=lambda: clock[0] + 31 * 24 * 3600)
    assert late["diagnostics"]["cache_hits"] == 0 and late["diagnostics"]["cache_expired"] == 1
    assert len(calls) > n_first                                                          # searched again


def test_entries_without_a_date_count_as_expired():
    assert ls._is_fresh({"validation_status": "open"}, 10.0) is False
    assert ls._is_fresh({"cached_at": 5.0}, 10.0) is True
    assert ls._is_fresh({"cached_at": 5.0}, 5.0 + ls.CACHE_TTL_SECONDS + 1) is False


def test_progress_ends_at_all_done_even_with_parallel_workers(isolated_env):
    seen = []
    with patch("pipeline.literature_scout._search_s2", lambda q, k: ([paper("Some related paper title")], True)), \
         patch("pipeline.literature_scout._search_europepmc", lambda q, limit=6: ([], True)):
        ls.scout_gaps(gaps(6), ScoutClient(), progress_callback=lambda d, n: seen.append((d, n)))
    assert seen[0] == (0, 6) and seen[-1] == (6, 6) and [d for d, _ in seen] == sorted(d for d, _ in seen)


def test_all_providers_failing_still_gives_unverified_in_parallel(isolated_env):
    with patch("pipeline.literature_scout._search_s2", lambda q, k: ([], False)), \
         patch("pipeline.literature_scout._search_europepmc", lambda q, limit=6: ([], False)):
        out = ls.scout_gaps(gaps(3), ScoutClient())
    assert [g["validation_status"] for g in out["gaps"]] == ["unverified"] * 3
    assert out["diagnostics"]["unverified"] == 3
