"""PR-22a: faults found by running reference extraction on real papers (spaces lost by the text extractor, junk entries,
unverified title matches, DOIs broken across lines)."""
import json
import time
from unittest.mock import MagicMock, patch

import fitz
import pytest

import pipeline.reference_extractor as rx
from pipeline import pdf_parser
from tests.fakes import FakeClient
from utils.call_log import CallLog

MDPI = ("1. European Cystic Fibrosis Society. ECFS Patient Registry. 2020. Available online: https://www.ecfs.eu/ecfspr "
        "(accessed on 7 October 2021). "
        "2. Rowe, S.M.; Miller, S.; Sorscher, E.J. Cystic Fibrosis. N. Engl. J. Med. 2005, 352, 1992–2001. [CrossRef][PubMed] "
        "3. Shteinberg, M.; Haq, I.J.; Polineni, D.; Davies, J.C. Cystic fibrosis. Lancet 2021, 397, 2195–2211. [CrossRef] "
        "4. Bell, S.C.; De Boeck, K.; Amaral, M. New pharmacological approaches for cystic fibrosis: Promises, progress, "
        "pitfalls. Pharmacol. Ther. 2015, 145, 19–34. [CrossRef][PubMed] "
        "5. Veit, G.; Avramescu, R.G.; Chiang, A.N. From CFTR biology toward combinatorial pharmacotherapy. Mol. Biol. "
        "Cell 2016, 27, 424–433. [CrossRef][PubMed]")


# ── text cleaning ──────────────────────────────────────────────────────────────────────────
def test_ligatures_line_break_hyphens_and_split_dois_are_repaired():
    out = rx.clean_reference_text("Identiﬁcation of the cystic ﬁbrosis gene: cloning of com- plementary DNA; TLR-in- duced")
    assert out == "Identification of the cystic fibrosis gene: cloning of complementary DNA; TLR-induced"
    assert "doi.org/10.3389/fphar.2018.01113" in rx.clean_reference_text("https://doi.org/ 10.3389/fphar.2018.01113 .")
    assert "10.1186/s12967-017-1193-9" in rx.clean_reference_text("doi 10.1186/s12967-017- 1193-9 . [5]")
    assert "10.1038/sj.leu.2400607" in rx.clean_reference_text("doi: 10.1038/sj.leu. 2400607 . [37]")


def test_a_doi_followed_by_a_year_is_not_glued_to_it():
    text = "10.1016/j.cell.2019.01.001. 2020, 45"
    assert rx.clean_reference_text(text) == text


def test_dois_found_after_repair():
    found = rx._extract_dois_from_text(rx.clean_reference_text("see https://doi.org/ 10.3389/fphar.2018.01113 ."))
    assert found == ["10.3389/fphar.2018.01113"]


# ── splitting ──────────────────────────────────────────────────────────────────────────────
def test_numbered_entries_split_exactly_even_when_numbers_appear_inside_them():
    entries = rx._split_reference_entries(MDPI)
    assert len(entries) == 5
    assert entries[1].startswith("Rowe, S.M.") and entries[1].endswith("[CrossRef][PubMed]")
    assert "2005, 352, 1992–2001" in entries[1]                       # page numbers did not start a new entry


def test_bracket_and_parenthesis_styles_split_in_order():
    br = "[1] A. Author, First title of the paper, J. One 1 (2001) 1-9. [2] B. Writer, Second title here, J. Two 2 (2002) 2-9. " \
         "[3] C. Third, Third paper title, J. Three 3 (2003) 3-9. [4] D. Fourth, Another title, J. Four 4 (2004) 4-9."
    assert len(rx._split_reference_entries(br)) == 4
    pa = br.replace("[", "(").replace("]", ")")
    assert len(rx._split_reference_entries(pa)) == 4


def test_a_number_out_of_sequence_is_not_a_boundary():
    text = "1. Alpha A. First study of things. J A 2001, 5, 1-2. 7. Beta B. Second study here. J B 2002, 6, 3-4. " \
           "2. Gamma G. Third study there. J C 2003, 7, 5-6. 3. Delta D. Fourth study again. J D 2004, 8, 7-8."
    entries = rx._split_reference_entries(text)
    assert len(entries) == 3 and "7. Beta B." in entries[0]          # "7." is inside entry 1, not a new entry


# ── page furniture and trailing sections ───────────────────────────────────────────────────
def test_a_running_footer_between_entries_is_removed_and_does_not_join_an_entry():
    text = ("References\n1. Rowe, S.M.; Miller, S. Cystic Fibrosis. N. Engl. J. Med. 2005, 352, 1992–2001.\n"
            "J. Clin. Med. 2022, 11, 1283 14 of 16\n"
            "2. Shteinberg, M.; Haq, I.J. Cystic fibrosis. Lancet 2021, 397, 2195–2211.\n"
            "3. Bell, S.C.; De Boeck, K. New pharmacological approaches. Pharmacol. Ther. 2015, 145, 19–34.\n"
            "J. Clin. Med. 2022, 11, 1283 15 of 16\n"
            "4. Veit, G.; Avramescu, R.G. Combinatorial pharmacotherapy. Mol. Biol. Cell 2016, 27, 424–433.")
    out = rx.strip_reference_noise(text)
    assert "14 of 16" not in out and "15 of 16" not in out
    entries = rx._split_reference_entries(out.split("\n", 1)[1])
    assert len(entries) == 4 and not any("J. Clin. Med. 2022" in e for e in entries)


def test_a_funding_or_contributions_heading_ends_the_list():
    text = "1. Alpha A. First study of things. J A 2001, 5, 1-2.\n2. Beta B. Second study here. J B 2002, 6, 3-4.\n" \
           "3. Gamma G. Third study there. J C 2003, 7, 5-6.\nFunding: This work was supported by a grant.\nAuthor Contributions: all."
    out = rx.strip_reference_noise(text)
    assert "supported by a grant" not in out and rx._split_reference_entries(out)[-1].endswith("5-6.")


def test_real_entries_that_look_alike_are_kept():
    text = "[1] A. Author, Title one about a thing, J. X 1 (2001) 1-9.\n[2] B. Writer, Title two about a thing, J. X 2 (2002) 2-9.\n" \
           "[3] C. Third, Title three about a thing, J. X 3 (2003) 3-9.\net al.\nand colleagues"
    out = rx.strip_reference_noise(text)
    assert out.count("J. X") == 3 and "et al." in out


# ── titles ─────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("title,ok", [
    ("Pharmacol", False), ("Care Med", False), ("Available online: https://www.cff.org/x", False),
    ("Accessed on 7 October 2021", False), ("Cystic fibrosis [CrossRef][PubMed]", False),
    ("Title of study", True), ("Emerging microRNA therapeutic approaches for cystic fibrosis", True),
])
def test_only_plausible_titles_are_searched_for(title, ok):
    assert rx._plausible_title(title) is ok


def test_a_guessed_title_that_is_not_a_title_is_dropped_from_the_fallback_reference():
    ref = rx._entry_to_reference("European Cystic Fibrosis Society. Available online: https://www.ecfs.eu/x (accessed on 7 October 2021).")
    assert ref["title"] == "" and ref["raw_reference"].startswith("European")


def test_html_in_a_crossref_title_is_removed():
    assert rx._plain_title("Triple Therapy for Cystic Fibrosis with a Phe508del\n   <i>CFTR</i>\n  Mutation") == \
        "Triple Therapy for Cystic Fibrosis with a Phe508del CFTR Mutation"


def test_a_hit_is_the_cited_paper_only_if_its_title_and_year_appear_in_the_citation():
    cite = "Wainwright CE, Elborn JS. Lumacaftor–Ivacaftor in Patients with Cystic Fibrosis Homozygous for Phe508del CFTR. N Engl J Med 2015;373"
    assert rx._title_in_citation("Lumacaftor–Ivacaftor in Patients with Cystic Fibrosis Homozygous for Phe508del CFTR", 2015, cite)
    assert not rx._title_in_citation("Lumacaftor–Ivacaftor in Patients with Cystic Fibrosis Homozygous for Phe508del CFTR", 1999, cite)
    assert not rx._title_in_citation("Gene therapy for rare respiratory diseases", 2015, cite)
    assert not rx._title_in_citation("Cystic fibrosis", 2015, cite)                  # too short to be a safe match


# ── lookups: a hit must be the paper that was asked for ─────────────────────────────────────
def _resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    return r


def test_openalex_does_not_return_an_unrelated_first_hit():
    hits = {"results": [{"title": "Mol. Pharmacol.", "publication_year": 2000, "abstract_inverted_index": {"x": [0]}, "doi": ""}]}
    with patch("pipeline.reference_extractor.requests.get", return_value=_resp(hits)):
        assert rx._openalex_by_title("Pharmacol") is None


def test_openalex_returns_the_best_matching_title_not_the_first():
    hits = {"results": [
        {"title": "A review of cystic fibrosis", "publication_year": 2000, "abstract_inverted_index": {}, "doi": "10.1/a"},
        {"title": "Gene therapy for cystic fibrosis lung disease", "publication_year": 2019,
         "abstract_inverted_index": {"Abstract": [0], "text": [1]}, "doi": "https://doi.org/10.1/b"}]}
    with patch("pipeline.reference_extractor.requests.get", return_value=_resp(hits)):
        got = rx._openalex_by_title("Gene therapy for cystic fibrosis lung disease")
    assert got["doi"] == "10.1/b" and got["abstract"] == "Abstract text"


def test_pubmed_title_search_rejects_a_different_paper():
    calls = [_resp({"esearchresult": {"idlist": ["42"]}}),
             _resp({"result": {"42": {"title": "A totally different paper about vitamins", "pubdate": "2001", "source": "J", "authors": []}}})]
    with patch("pipeline.reference_extractor.requests.get", side_effect=calls) as get:
        assert rx._pubmed_search(title="Gene therapy for cystic fibrosis lung disease") is None
    assert get.call_args_list[0].kwargs["params"]["term"].endswith('"[Title]')


def test_crossref_citation_search_accepts_only_a_hit_named_in_the_citation():
    item = {"DOI": "10.1/x", "title": ["Twenty Facts About Cystic Fibrosis"], "published": {"date-parts": [[2017]]},
            "container-title": ["AJRCCM"], "author": [], "is-referenced-by-count": 3}
    other = {"DOI": "10.1/y", "title": ["Something else entirely different here"], "published": {"date-parts": [[2017]]}}
    cite = "M.M. Sockrider, T.W. Ferkol, Twenty facts about cystic fibrosis, Am. J. Respir. Crit. Care Med. 196 (2017) 23-24"
    with patch("pipeline.reference_extractor.requests.get", return_value=_resp({"message": {"items": [other, item]}})):
        got = rx._crossref_citation_search(cite)
    assert got["doi"] == "10.1/x" and got["source_api"] == "crossref_citation"
    with patch("pipeline.reference_extractor.requests.get", return_value=_resp({"message": {"items": [other]}})):
        assert rx._crossref_citation_search(cite) is None


def test_a_missing_abstract_is_filled_in_from_openalex_by_doi(isolated_env):
    crossref = {"title": "Some Paper About Airways And Mucus", "year": 2018, "abstract": "", "doi": "10.9/abc",
                "venue": "J", "authors": [], "citations": 0, "url": "", "source_api": "crossref"}
    with patch.object(rx, "_ss_by_doi", return_value=None), patch.object(rx, "_crossref_by_doi", return_value=crossref), \
         patch.object(rx, "_openalex_by_doi", return_value={"abstract": "The abstract.", "openalex_id": "W1"}) as oa, \
         patch.object(rx, "_unpaywall_by_doi", return_value=None):
        out = rx.enrich_reference({"doi": "10.9/abc", "title": ""}, delay=0)
    assert out["tier"] == 2 and out["abstract"] == "The abstract." and out["source"] == "crossref" and oa.called


def test_an_unresolved_reference_is_labelled_with_its_citation_not_unknown(isolated_env):
    with patch.object(rx, "_crossref_citation_search", return_value=None):
        out = rx.enrich_reference({"title": "", "doi": "", "raw_reference": "Cabrini G. Innovative therapies for cystic fibrosis. Mol Diagn Ther 2019"}, delay=0)
    assert out["tier"] == 3 and out["title"].startswith("Cabrini G.")


# ── short titles need the year and an author to agree ────────────────────────────────────────
def _hit(title, year, authors):
    return {"results": [{"title": title, "publication_year": year, "abstract_inverted_index": {"A": [0]},
                         "doi": "https://doi.org/10.1/x", "authorships": [{"author": {"display_name": a}} for a in authors]}]}


ELBORN = {"title": "Cystic fibrosis", "year": 2016, "authors": [],
          "raw_reference": "J.S. Elborn, Cystic fibrosis, Lancet 388 (10059) (2016) 2519 – 2531"}


def test_a_two_word_title_is_matched_when_year_and_author_agree(isolated_env):
    with patch.object(rx.requests, "get", return_value=_resp(_hit("Cystic fibrosis", 2016, ["J Stuart Elborn"]))):
        out = rx.enrich_reference(dict(ELBORN), delay=0)
    assert out["tier"] == 2 and out["source"] == "openalex" and out["authors"] == ["J Stuart Elborn"]


@pytest.mark.parametrize("hit", [
    _hit("Cystic fibrosis", 1998, ["J Stuart Elborn"]),            # right author, wrong year
    _hit("Cystic fibrosis", 2016, ["Someone Else"]),               # right year, wrong author
    _hit("Cystic fibrosis", 2016, []),                             # nothing to check it against
])
def test_a_two_word_title_is_not_matched_when_year_or_author_disagree(isolated_env, hit):
    with patch.object(rx.requests, "get", return_value=_resp(hit)), \
         patch.object(rx, "_crossref_search", return_value=None), patch.object(rx, "_ss_search_by_title", return_value=None), \
         patch.object(rx, "_pubmed_search", return_value=None), patch.object(rx, "_crossref_citation_search", return_value=None):
        out = rx.enrich_reference(dict(ELBORN), delay=0)
    assert out["tier"] == 3


def test_a_longer_title_does_not_need_the_extra_checks(isolated_env):
    ref = {"title": "Emerging microRNA therapeutic approaches for cystic fibrosis", "year": None, "authors": []}
    with patch.object(rx.requests, "get", return_value=_resp(_hit("Emerging microRNA therapeutic approaches for cystic fibrosis", 2018, []))):
        assert rx.enrich_reference(ref, delay=0)["tier"] == 2


def test_the_citation_search_accepts_a_short_title_only_with_year_and_author():
    item = {"DOI": "10.1/x", "title": ["Cystic fibrosis"], "published": {"date-parts": [[2016]]},
            "author": [{"given": "J. Stuart", "family": "Elborn"}], "container-title": ["Lancet"]}
    with patch.object(rx.requests, "get", return_value=_resp({"message": {"items": [item]}})):
        assert rx._crossref_citation_search(ELBORN["raw_reference"])["doi"] == "10.1/x"
        assert rx._crossref_citation_search("A. Other, Cystic fibrosis, Some Journal (2016) 1-9, in a long enough citation") is None


# ── a provider that refuses us is left alone, and the reader is told ──────────────────────────
BUDGET_MSG = ('{"error":"Rate limit exceeded","message":"Insufficient budget. This request has no API key, so it counts '
              'against the free daily budget shared by everyone on your network\'s IP address"}')


def _r429(text=BUDGET_MSG):
    r = MagicMock()
    r.status_code, r.text = 429, text
    return r


def test_openalex_out_of_free_budget_is_skipped_for_the_rest_of_the_run_with_a_note():
    rx._reset_providers()
    with patch.object(rx.requests, "get", return_value=_r429()) as get:
        assert rx._openalex_by_title("Gene therapy for cystic fibrosis lung disease") is None
        assert rx._openalex_by_doi("10.1/abc") is None
        assert rx._openalex_by_title("Another long enough title about airways") is None
    assert get.call_count == 1                                          # one refusal, then no more requests to it
    assert "OPENALEX_API_KEY" in rx._BLOCKED["openalex"]
    rx._reset_providers()


def test_a_run_reports_a_blocked_provider_and_still_resolves_what_other_sources_find(isolated_env):
    text = "[1] A. Au, Gene therapy for cystic fibrosis lung disease, J. X 1 (2001) 1-9. [2] B. Bu, Second long title about airways, J. X 2 (2002) 2-9. " \
           "[3] C. Cu, Third long title about mucus clearance, J. X 3 (2003) 3-9."
    crossref = {"message": {"items": []}}

    def fake_get(url, **kw):
        if "openalex" in url:
            return _r429()
        return _resp(crossref)
    with patch.object(rx.requests, "get", side_effect=fake_get):
        refs, diag = rx.extract_and_enrich_references([_paper(text)], None, max_refs_per_paper=None, return_diagnostics=True)
    assert len(refs) == 3 and any("OPENALEX_API_KEY" in n for n in diag["provider_notes"])


def test_the_openalex_key_is_sent_when_set(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "oa-test-key")
    assert rx._openalex_headers()["Authorization"] == "Bearer oa-test-key"
    monkeypatch.delenv("OPENALEX_API_KEY")
    assert "Authorization" not in rx._openalex_headers()


def test_semantic_scholar_title_search_is_given_up_after_a_rate_limit():
    rx._reset_providers()
    with patch.object(rx.requests, "get", return_value=_r429('{"message":"Too Many Requests"}')) as get:
        rx._ss_search_by_title("Gene therapy for cystic fibrosis lung disease")
        rx._ss_search_by_title("Another long enough title about airways")
    assert get.call_count == 1 and "SEMANTIC_SCHOLAR_API_KEY" in rx._BLOCKED["semantic_scholar_search"]
    rx._reset_providers()


def test_unpaywall_is_only_called_with_a_real_contact_address(monkeypatch):
    monkeypatch.delenv("RESGAP_CONTACT_EMAIL", raising=False)
    with patch.object(rx.requests, "get") as get:
        assert rx._unpaywall_by_doi("10.1/abc") is None
    assert not get.called
    monkeypatch.setenv("RESGAP_CONTACT_EMAIL", "someone@university.edu")
    with patch.object(rx.requests, "get", return_value=_resp({"is_oa": True, "best_oa_location": {"url_for_pdf": "http://x/p.pdf"}})) as get:
        assert rx._unpaywall_by_doi("10.1/abc") == "http://x/p.pdf"
    assert get.call_args.kwargs["params"]["email"] == "someone@university.edu"


# ── every entry is read by the model, in chunks ────────────────────────────────────────────
def _numbered_refs(n):
    return "\n".join(f"{i}. Author{i} A. Distinct study title number {i} of the series. J Series {i} (2000):1-{i + 9}." for i in range(1, n + 1))


def test_the_model_reads_all_requested_entries_in_chunks_of_25():
    entries = rx._split_reference_entries(_numbered_refs(60))
    assert len(entries) == 60
    seen = []

    class Echo(FakeClient):
        def chat_json(self, system, user, *a, **kw):
            lines = [l for l in user.split("\n\n", 1)[1].splitlines()]
            seen.append(len(lines))
            return super().chat_json(system, user, *a, **kw)

    def reply(n0, n):
        return json.dumps([{"title": f"Distinct study title number {i} of the series", "year": 2000, "authors": [f"Author{i} A"]}
                           for i in range(n0, n0 + n)])
    client = Echo([reply(1, 25), reply(26, 25), reply(51, 10)])
    out = rx.parse_references_with_llm("", client, entries=entries, max_refs=None)
    assert sorted(seen) == [10, 25, 25] and len(out) == 60
    assert {r["title"] for r in out} == {f"Distinct study title number {i} of the series" for i in range(1, 61)}


def test_a_limit_below_the_total_reads_only_that_many_and_one_bad_chunk_does_not_lose_the_rest():
    entries = rx._split_reference_entries(_numbered_refs(60))
    client = FakeClient(["!api_error", json.dumps([{"title": "Distinct study title number 30 of the series", "year": 2000}])])
    out = rx.parse_references_with_llm("", client, entries=entries, max_refs=50)
    assert len(client.calls) == 2                                           # 50 entries = two chunks of 25
    assert [r["title"] for r in out] == ["Distinct study title number 30 of the series"]


# ── the model stage ────────────────────────────────────────────────────────────────────────
def test_the_model_is_given_the_numbered_entries_it_will_be_asked_about():
    entries = rx._split_reference_entries(MDPI)
    reply = [{"title": "Cystic fibrosis", "authors": ["Rowe S"], "year": 2005, "doi": None, "journal": "NEJM"}]
    client = FakeClient([json.dumps(reply)])
    client.call_log = CallLog()
    out = rx.parse_references_with_llm("", client, entries=entries, max_refs=3)
    listing = client.calls[0]["user"].split("\n\n", 1)[1]
    assert listing.count("\n") == 2 and listing.splitlines()[-1].startswith("3. Shteinberg") and "4. Bell" not in listing
    assert out[0]["title"] == "Cystic fibrosis"


def test_a_model_reference_without_a_title_is_rejected_and_logged():
    reply = [{"authors": ["x"], "year": 2001}, {"title": "A real paper title here", "year": "2003", "doi": "https://doi.org/10.1/ABC"}]
    client = FakeClient([json.dumps(reply)])
    client.call_log = CallLog()
    out = rx.parse_references_with_llm("References: " + "x" * 100, client)
    assert [r["title"] for r in out] == ["A real paper title here"] and out[0]["doi"] == "10.1/abc"
    assert client.call_log.schema_error_count == 1


def _paper(entries_text):
    return {"filename": "p.pdf", "sections": {"References": entries_text}, "full_text": ""}


def test_an_entry_the_model_already_parsed_is_not_added_again_and_order_follows_the_paper(isolated_env):
    seen = []

    def fake_enrich(ref, delay=0.3):
        seen.append(ref)
        return {"title": ref.get("title") or ref.get("raw_reference", "")[:50], "tier": 3, "source": "parsed_only",
                "abstract": "", "doi": ref.get("doi")}

    structured = [{"title": "T%d" % i, "authors": [], "year": 2021, "doi": None} for i in range(3)]
    with patch.object(rx, "enrich_reference", fake_enrich), \
         patch.object(rx, "parse_references_with_llm", return_value=structured):
        refs = rx.extract_and_enrich_references([_paper(MDPI)], client=MagicMock(), max_refs_per_paper=None)
    assert [r["title"] for r in refs] == ["T0", "T1", "T2"]            # 3 of the 5 entries parsed: all five are covered

    seen.clear()
    one = [{"title": "New pharmacological approaches for cystic fibrosis: Promises, progress, pitfalls",
            "authors": [], "year": 2015, "doi": None}]
    with patch.object(rx, "enrich_reference", fake_enrich), \
         patch.object(rx, "parse_references_with_llm", return_value=one):
        refs = rx.extract_and_enrich_references([_paper(MDPI)], client=MagicMock(), max_refs_per_paper=None)
    # the model parsed too few entries to cover the list: rule-based entries fill in, except the one it parsed
    assert len(refs) == 5 and sum(1 for r in refs if r["title"].startswith("Bell")) == 0


def test_entries_keep_their_citation_text_and_doi_in_the_papers_order(isolated_env):
    text = "[1] A. Author, First title of the paper here, J. One 1 (2001) 1-9, https://doi.org/10.1000/aaa . " \
           "[2] B. Writer, Second title of the paper here, J. Two 2 (2002) 2-9. [3] C. Third, Third title of the paper here, J. Three 3 (2003) 3-9."
    seen = []
    with patch.object(rx, "enrich_reference", lambda ref, delay=0.3: (seen.append(ref), {"title": ref["title"] or "x", "tier": 3, "source": "s", "abstract": "", "doi": ref.get("doi")})[1]):
        rx.extract_and_enrich_references([_paper(text)], client=None, max_refs_per_paper=None)
    assert [s.get("doi") for s in seen] == ["10.1000/aaa", None, None]                # one record per entry, in order
    assert seen[0]["raw_reference"].startswith("A. Author") and seen[1]["raw_reference"].startswith("B. Writer")


def test_lookups_run_side_by_side_and_results_keep_the_paper_order(isolated_env):
    def slow(ref, delay=0.3):
        time.sleep(0.3)
        return {"title": ref["title"], "tier": 3, "source": "s", "abstract": "", "doi": ""}

    text = " ".join(f"[{i}] Author{i} A. Distinct title number {i} about topic {i} of the field, J. X {i} (200{i % 10}) 1-9." for i in range(1, 10))
    t0 = time.time()
    with patch.object(rx, "enrich_reference", slow):
        refs = rx.extract_and_enrich_references([_paper(text)], client=None, max_refs_per_paper=None)
    elapsed = time.time() - t0
    assert [r["title"][:14] for r in refs] == [f"Distinct title" for _ in range(9)]
    assert [r["title"] for r in refs] == sorted([r["title"] for r in refs], key=lambda t: int(t.split()[3]))
    assert elapsed < 9 * 0.3 * 0.7                                       # sequential would take 2.7 s


# ── the text extractor ─────────────────────────────────────────────────────────────────────
def _tight_pdf(words: list[str], gap: float, path: str) -> str:
    """A PDF whose words are separate text runs `gap` points apart (smaller than the usual space)."""
    doc = fitz.open()
    page = doc.new_page()
    x, y = 50.0, 100.0
    for w in words:
        page.insert_text((x, y), w, fontsize=10, fontname="helv")
        x += fitz.get_text_length(w, fontname="helv", fontsize=10) + gap
        if x > 520:
            x, y = 50.0, y + 14
    doc.save(path)
    doc.close()
    return path


def test_words_set_tightly_are_not_fused_into_one_long_word(tmp_path):
    words = ("Cystic fibrosis outcomes measured twelve months cohort adults treatment response baseline "
             "elexacaftor tezacaftor ivacaftor patients registry survey expert opinion genetic therapies "
             "modulator pharmacotherapy lung function exacerbations hospitalisation").split() * 3
    path = _tight_pdf(words, 2.0, str(tmp_path / "tight.pdf"))
    text = pdf_parser._extract_text_by_section(path)["full_text"]
    assert "Cystic fibrosis outcomes measured" in text
    assert not pdf_parser._words_run_together(text)


def test_the_run_together_check_flags_fused_text_and_not_normal_text():
    fused = "Newpharmacologicalapproachesforcysticfibrosis:Promises,progress,pitfalls.Pharmacol.Ther.2015,145,19–34. " * 50
    assert pdf_parser._words_run_together(fused)
    assert not pdf_parser._words_run_together("The overall response rate was higher in treated patients. " * 50)
    assert not pdf_parser._words_run_together("too short")
