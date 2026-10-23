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
