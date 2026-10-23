"""PR-22b: faults found by running the Corpus Quality Engine and canonical reference resolution on real papers."""
import pytest

from pipeline import extraction_reconciler as rec
from pipeline.canonical_resolver import filter_and_dedupe_references, resolve_canonical_identity, resolve_status
from pipeline.corpus_quality import (ACHIEVABLE_FIELD_COUNT, compute_corpus_quality, score_paper_completeness,
                                     structure_fields, table_captions)
import pipeline.reference_extractor as rx
from unittest.mock import patch


def seg(text, label="text", page=1):
    return {"text": text, "label": label, "page": page}


PAPER = {
    "filename": "p.pdf", "full_text": "",
    "text_segments": [seg("Abstract: Cystic fibrosis is a genetic disease."), seg("1. Introduction", "section_header"),
                      seg("Body text."), seg("2. Materials and Methods", "section_header"),
                      seg("Table 1. Summary of the sample."), seg("5. Conclusions", "section_header"), seg("End.")],
    "sections": {"_header": "x", "References": "..."},
}
RECONCILED = {"fields": {"doi": {"value": "10.1/x", "confidence": "high", "source": "both"},
                         "tables": {"value": [], "confidence": "low", "source": "none"}}}
WIKI = {"title": "A real title", "source_file": "p.pdf", "methods": ["m"], "datasets": ["d"], "key_findings": ["k"],
        "limitations": ["l"], "future_work": ["f"]}


# ── sections found from the paper's own headings ───────────────────────────────────────────
def test_abstract_introduction_and_conclusion_are_found_from_headings_and_inline_labels():
    f = structure_fields(PAPER)
    assert {k: v["status"] for k, v in f.items()} == {"abstract": "present", "introduction": "present", "conclusion": "present"}


@pytest.mark.parametrize("first_lines", [
    ["Journal of Cystic Fibrosis 21 (2022)", "a b s t r a c t", "Background: Cystic fibrosis is..."],     # Elsevier
    ["Contents lists available at ScienceDirect", "A B S T R A C T", "Keywords: Cystic fibrosis (CF)"],
    ["Article", "Title of the paper", "Authors", "Abstract: Cystic fibrosis is a life-threatening disease"],   # MDPI
    ["Title", "Abstract—We study the thing."],
])
def test_the_abstract_is_found_in_the_layouts_journals_actually_use(first_lines):
    paper = {"text_segments": [seg(t) for t in first_lines + ["filler text"] * 30], "sections": {}}
    assert structure_fields(paper)["abstract"]["status"] == "present"


def test_the_word_abstract_in_running_text_is_not_an_abstract():
    paper = {"text_segments": [seg("We wrote an abstract summary of the findings later.")] + [seg("filler")] * 5, "sections": {}}
    assert structure_fields(paper)["abstract"]["status"] == "empty"


def test_missing_sections_are_empty_not_invented_and_no_paper_means_not_extracted():
    bare = {"text_segments": [seg("Results", "section_header"), seg("Some text.")], "sections": {}}
    assert {v["status"] for v in structure_fields(bare).values()} == {"empty"}
    assert {v["status"] for v in structure_fields(None).values()} == {"not_extracted"}


def test_numbering_and_roman_numerals_do_not_hide_a_heading():
    paper = {"text_segments": [seg("I. INTRODUCTION", "section_header"), seg("IV. Conclusion", "section_header")], "sections": {}}
    f = structure_fields(paper)
    assert f["introduction"]["status"] == "present" and f["conclusion"]["status"] == "present"


# ── tables ─────────────────────────────────────────────────────────────────────────────────
def test_table_captions_are_counted_once_each():
    paper = {"text_segments": [seg("Table 1. A"), seg("see Table 1 above"), seg("Table 2  B"), seg("Table 2. B again")]}
    assert table_captions(paper) == ["1", "2"]


def test_a_paper_with_captions_but_no_detected_cells_is_not_scored_as_having_no_tables():
    s = score_paper_completeness(RECONCILED, WIKI, ref_count=10, paper=PAPER)
    assert s["fields"]["tables"]["status"] == "present" and s["fields"]["tables"]["source"] == "caption only"
    assert s["fields"]["tables"]["confidence"] == "low"
    none = score_paper_completeness(RECONCILED, WIKI, ref_count=10, paper={"text_segments": [seg("No tables here.")], "sections": {}})
    assert none["fields"]["tables"]["status"] == "empty"


# ── the ceiling is the real ceiling ────────────────────────────────────────────────────────
def test_the_achievable_count_matches_the_fields_that_can_never_be_found():
    s = score_paper_completeness(RECONCILED, WIKI, ref_count=10, has_figures=True, paper=PAPER)
    never = [k for k, v in s["fields"].items() if v["status"] == "not_extracted"]
    assert sorted(never) == ["authors", "metrics", "models_interventions"]
    assert ACHIEVABLE_FIELD_COUNT == s["total_fields"] - len(never)
    assert s["achievable_completeness_score"] == 1.0                    # everything findable was found: not penalised


# ── references per paper, and an honest funnel ─────────────────────────────────────────────
def test_a_paper_with_no_references_is_not_credited_with_another_papers():
    with_refs = score_paper_completeness(RECONCILED, WIKI, ref_count=40, paper=PAPER)
    without = score_paper_completeness(RECONCILED, WIKI, ref_count=0, paper=PAPER)
    assert with_refs["fields"]["references"]["status"] == "present" and without["fields"]["references"]["status"] == "empty"


def test_the_pipeline_passes_each_papers_own_reference_count():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "pipeline" / "run_pipeline.py").read_text(encoding="utf-8")
    assert '_per_paper.get(paper.get("filename")' in src and "paper=paper" in src


def test_resolved_means_found_by_a_lookup_and_unmatched_references_are_unresolved():
    diag = {"raw_entries": 100, "structured_entries": 0, "fallback_entries": 100, "enriched": 22, "title_only": 14,
            "resolved_no_abstract": 4, "unmatched": 10, "unresolved": 0, "duplicates_skipped": 0,
            "papers": [{"filename": "a.pdf", "raw_entries": 60}, {"filename": "b.pdf", "raw_entries": 40}]}
    m = compute_corpus_quality([score_paper_completeness(RECONCILED, WIKI, 5, paper=PAPER)], diag,
                               ref_papers=[{"doi": "10.1/a"}] * 3 + [{"doi": ""}])
    f = m["reference_funnel"]
    assert f["resolved"] == 26 and f["unresolved"] == 10 and f["detected"] == 100
    assert m["references_per_paper"] == {"a.pdf": 60, "b.pdf": 40}


def test_old_diagnostics_without_the_new_counts_still_work():
    old = {"raw_entries": 10, "structured_entries": 10, "fallback_entries": 0, "enriched": 6, "title_only": 2, "unresolved": 1}
    m = compute_corpus_quality([score_paper_completeness(RECONCILED, WIKI, 5, paper=PAPER)], old, ref_papers=[])
    assert m["reference_funnel"]["resolved"] == 8 and m["reference_funnel"]["unresolved"] == 1


def test_enrichment_counts_found_and_unmatched_references_separately(isolated_env):
    def fake(ref, delay=0.3):
        found = "Found" in ref["raw_reference"]
        return {"title": ref["title"], "tier": 2 if found else 3, "source": "s", "abstract": "", "doi": ""}

    text = ("[1] A. Au, Found paper number one about things, J. X 1 (2001) 1-9. "
            "[2] B. Bu, Lost paper number two about things, J. X 2 (2002) 2-9. "
            "[3] C. Cu, Found paper number three about things, J. X 3 (2003) 3-9.")
    with patch.object(rx, "enrich_reference", fake):
        _, diag = rx.extract_and_enrich_references([{"filename": "p.pdf", "sections": {"References": text}, "full_text": ""}],
                                                   None, max_refs_per_paper=None, return_diagnostics=True)
    assert diag["resolved_no_abstract"] == 2 and diag["unmatched"] == 1 and diag["title_only"] == 3


# ── canonical resolution ───────────────────────────────────────────────────────────────────
def test_a_reference_with_a_real_title_and_a_year_is_kept_not_quarantined():
    ref = {"title": "New pharmacological approaches for cystic fibrosis", "year": 2015, "authors": [], "tier": 3}
    r = resolve_canonical_identity(ref)
    assert r["identity_level"] == "title_year" and resolve_status(r["identity_level"]) == "ACCEPTED"
    kept, diag = filter_and_dedupe_references([ref, dict(ref)])
    assert len(kept) == 1 and diag["duplicates_removed"] == 1


@pytest.mark.parametrize("ref", [
    {"title": "Cystic fibrosis", "year": 2015},               # too short to be an identity on its own
    {"title": "A long enough title for a reference", "year": None},
    {"title": "", "year": 2015},
])
def test_weak_references_are_still_quarantined_or_unresolved(ref):
    assert resolve_status(resolve_canonical_identity(ref)["identity_level"]) in ("QUARANTINED", "UNRESOLVED")


# ── a DOI is the paper's own only if it is in the front matter ─────────────────────────────
def _p(text):
    return {"full_text": text, "tables": []}


def test_a_doi_that_appears_only_in_the_reference_list_is_not_the_papers_own():
    body = "Thesis text without an identifier. " * 1500
    text = body + "\nReferences\n[1] Smith J. Something. doi:10.1016/j.cell.2019.01.001"
    out = rec.reconcile_paper(_p(text), _p(text), "thesis.pdf")["fields"]["doi"]
    assert out["value"] is None and out["needs_llm_recovery"] is True
    assert [c["value"] for c in out["candidates"]] == ["10.1016/j.cell.2019.01.001"] * 2     # still listed, flagged
    assert not any(c["front_matter"] for c in out["candidates"])


def test_a_front_matter_doi_is_the_papers_own_even_when_references_hold_others():
    text = "Title\nhttps://doi.org/10.3390/jcm11051283\n" + ("x " * 30000) + "\nReferences\n[1] doi:10.1016/j.cell.2019.01.001"
    out = rec.reconcile_paper(_p(text), _p(text), "p.pdf")["fields"]["doi"]
    assert out["value"] == "10.3390/jcm11051283" and out["confidence"] == "high"


def test_short_papers_still_find_their_doi():
    text = "Short note. DOI 10.1000/xyz123. " + "word " * 200
    assert rec.reconcile_paper(_p(text), _p(text), "n.pdf")["fields"]["doi"]["value"] == "10.1000/xyz123"
