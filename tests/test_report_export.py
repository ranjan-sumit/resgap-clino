import json
import re

import fitz
import pytest

import utils.database as db
from tests.fixtures.make_golden_run import golden_comp, golden_results, legacy_results, seed_run
from utils import export as ex
from utils import project_store

PID = db.DEFAULT_PROJECT_ID
CTX = {"domain": "Healthcare AI", "interest": "outcomes in children", "gap_type": "Any"}


def _with_refs(results):
    results = dict(results)
    results["ref_papers"] = [
        {"title": "Emerging microRNA Therapeutic Approaches for Cystic Fibrosis", "year": "2018",
         "doi": "10.3389/fphar.2018.01113", "authors": "['Pauline Bardin', 'Florence Sonneville', 'Harriet Corvol', 'A Fourth']",
         "venue": "Frontiers in Pharmacology", "source": "crossref", "citations": 38},
        {"title": "A reference with nothing else", "year": "", "doi": "", "authors": [], "source": "manual"},
    ]
    return results


def _pdf_text(data: bytes) -> str:
    with fitz.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


# ── HTML ────────────────────────────────────────────────────────────────────────────────────
def test_html_report_has_every_section_and_no_lab_section_without_lab():
    html = ex.to_enterprise_html_report(golden_results(), CTX)
    for title in ("Executive Summary", "Corpus Overview", "Papers Analyzed", "Key Research Gaps",
                  "Recommended Research Proposals", "Risks and Limitations", "Appendix: Pipeline Audit"):
        assert f"<h2>{title}</h2>" in html, title
    assert "Computational Lab" not in html


def test_html_report_with_lab_has_the_lab_section():
    html = ex.to_enterprise_html_report(golden_results(), CTX, comp_results=golden_comp())
    assert "Computational Lab" in html and "<h2>Computational Lab</h2>" in html


def test_unchecked_sections_are_removed_and_the_cover_stays():
    html = ex.to_enterprise_html_report(golden_results(), CTX, comp_results=golden_comp(),
                                        sections=["gaps", "proposals"])
    assert "<h2>Key Research Gaps</h2>" in html and "<h2>Validation Evidence</h2>" in html
    assert "<h2>Recommended Research Proposals</h2>" in html
    for gone in ("Executive Summary", "Corpus Overview", "Papers Analyzed", "Knowledge Graph Summary",
                 "Risks and Limitations", "Appendix: Pipeline Audit", "Computational Lab", "Reference Corpus Summary"):
        assert f"<h2>{gone}</h2>" not in html, gone
    assert "Research Gap Analysis Report" in html and 'class="cover"' in html
    assert html.count("<section") == html.count("</section>")


def test_no_sections_leaves_just_the_cover():
    html = ex.to_enterprise_html_report(golden_results(), CTX, sections=[])
    assert 'class="cover"' in html and "<h2>" not in html


def test_the_section_registry_covers_every_html_heading():
    html = ex.to_enterprise_html_report(_with_refs(golden_results()), CTX, comp_results=golden_comp())
    for title in re.findall(r"<h2>(.*?)</h2>", html):
        assert title in ex._HTML_TITLE_TO_SECTION, f"section {title!r} cannot be switched off"
    assert set(ex._HTML_TITLE_TO_SECTION.values()) == set(ex.ALL_SECTION_IDS)


def test_references_list_authors_venue_year_and_a_doi_link():
    html = ex.to_enterprise_html_report(_with_refs(golden_results()), CTX)
    assert "Pauline Bardin, Florence Sonneville, Harriet Corvol et al." in html
    assert "<em>Frontiers in Pharmacology</em>" in html and "<td>2018</td>" in html
    assert "<a href='https://doi.org/10.3389/fphar.2018.01113'>10.3389/fphar.2018.01113</a>" in html
    assert "A reference with nothing else" in html                    # sparse metadata does not break the row


def test_hostile_text_is_escaped_in_the_report():
    r = golden_results()
    r["gaps"][0]["title"] = "p < 0.05 <script>alert(1)</script>"
    html = ex.to_enterprise_html_report(r, CTX)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_legacy_runs_export_without_error():
    html = ex.to_enterprise_html_report(legacy_results(), CTX)
    assert "Research Gap Analysis Report" in html
    assert ex.to_enterprise_pdf_report(legacy_results(), CTX)[:4] == b"%PDF"


# ── PDF ─────────────────────────────────────────────────────────────────────────────────────
def test_pdf_report_is_a_pdf_with_the_main_sections():
    data = ex.to_enterprise_pdf_report(_with_refs(golden_results()), CTX)
    assert data[:4] == b"%PDF" and len(data) > 3000
    text = _pdf_text(data)
    for title in ("Executive Summary", "Key Research Gaps", "Recommended Research Proposals", "Reference Corpus Summary"):
        assert title in text
    assert "Computational Lab" not in text
    assert "Bardin" in text and "Frontiers in Pharmacology" in text and "doi:10.3389/fphar.2018.01113" in text


def test_pdf_report_with_lab_and_with_sections_removed():
    full = _pdf_text(ex.to_enterprise_pdf_report(golden_results(), CTX, comp_results=golden_comp()))
    assert "Computational Lab" in full
    cut = _pdf_text(ex.to_enterprise_pdf_report(golden_results(), CTX, comp_results=golden_comp(),
                                                sections=["gaps", "risks"]))
    assert "Key Research Gaps" in cut and "Risks and Limitations" in cut
    for gone in ("Executive Summary", "Corpus Overview", "Papers Analyzed", "Computational Lab",
                 "Recommended Research Proposals", "Appendix"):
        assert gone not in cut, gone


# ── Markdown, JSON, quick PDF ───────────────────────────────────────────────────────────────
def test_markdown_report_contains_gaps_and_proposals():
    md = ex.to_markdown_report(golden_results(), CTX)
    assert "No long-term follow-up" in md and "Two-year extension cohort" in md


def test_json_export_round_trips():
    out = json.loads(ex.to_json(golden_results()))
    assert out["gaps"][0]["title"] == "No long-term follow-up" and len(out["papers"]) == 3


def test_quick_pdf_report_is_a_pdf():
    assert ex.to_pdf_report(golden_results(), CTX)[:4] == b"%PDF"


@pytest.mark.parametrize("fn", [ex.to_markdown_report, ex.to_pdf_report])
def test_simple_formats_accept_runs_with_and_without_a_graph_or_refs(fn):
    for r in (golden_results(), legacy_results()):
        assert fn(r, CTX)


# ── the Export screen ───────────────────────────────────────────────────────────────────────
def _export(app_test, comp=None, automatic_report=True):
    rid = seed_run(golden_results(), comp_results=comp)
    project_store.write_run_artifacts(PID, rid, golden_results(), CTX, make_reports=automatic_report,
                                      manifest={"run_name": "Golden run"})
    at = app_test(timeout=90)
    at.session_state["result_tab"] = "Export"
    return at.run(), rid


def _no_llm(at):
    next(c for c in at.checkbox if c.label.startswith("Use LLM narrative polish")).uncheck()
    return at.run()


def test_the_section_checklist_defaults_to_all_but_lab_when_the_lab_was_not_run(app_test, isolated_env):
    at, _ = _export(app_test)
    box = at.multiselect(key="report_sections")
    assert "lab" not in box.value and set(box.value) == set(ex.ALL_SECTION_IDS) - {"lab"}
    at2, _ = _export(app_test, comp=golden_comp())
    assert "lab" in at2.multiselect(key="report_sections").value


def test_generate_is_disabled_with_no_sections(app_test, isolated_env):
    at, _ = _export(app_test)
    at.multiselect(key="report_sections").set_value([]).run()
    assert at.button(key="generate_final_report").disabled


def test_the_preview_equals_the_download_equals_the_saved_file(app_test, isolated_env):
    at, rid = _export(app_test)
    _no_llm(at)
    at.multiselect(key="report_sections").set_value(["summary", "gaps"]).run()
    at.button(key="generate_final_report").click().run()
    assert not at.exception, [e.value for e in at.exception]
    bundle = at.session_state["report_bundle"]
    assert bundle["sections"] == ["summary", "gaps"] and "<h2>Key Research Gap" in bundle["html"]
    assert "Corpus Overview" not in bundle["html"]
    assert any(e.label == "Preview the report" for e in at.expander)          # the in-app preview
    at.button(key="save_final_report").click().run()
    saved = (project_store.project_dir(PID) / "runs" / rid / "report.html").read_text(encoding="utf-8")
    assert saved == bundle["html"]
    pdf = (project_store.project_dir(PID) / "runs" / rid / "report.pdf").read_bytes()
    assert pdf == bundle["pdf"] and "Key Research Gaps" in _pdf_text(pdf)


def test_a_saved_report_replaces_the_automatic_one(app_test, isolated_env):
    at, rid = _export(app_test)
    path = project_store.project_dir(PID) / "runs" / rid / "report.html"
    automatic = path.read_text(encoding="utf-8")
    assert "Corpus Overview" in automatic                                      # the automatic report has everything
    _no_llm(at)
    at.multiselect(key="report_sections").set_value(["risks"]).run()
    at.button(key="generate_final_report").click().run()
    at.button(key="save_final_report").click().run()
    assert path.read_text(encoding="utf-8") != automatic and "Corpus Overview" not in path.read_text(encoding="utf-8")
    kinds = [f["kind"] for f in db.list_project_files(PID, run_id=rid)]
    assert kinds.count("report_html") == 1 and kinds.count("report_pdf") == 1   # replaced, not duplicated


def test_a_report_with_the_lab_says_so_and_includes_it(app_test, isolated_env):
    at, _ = _export(app_test, comp=golden_comp())
    _no_llm(at)
    at.button(key="generate_final_report").click().run()
    bundle = at.session_state["report_bundle"]
    assert bundle["with_lab"] is True and "<h2>Computational Lab</h2>" in bundle["html"]
    assert "Lab section: yes" in " ".join(i.value for i in at.info)


def test_quick_downloads_exist_for_every_format(app_test, isolated_env):
    at, _ = _export(app_test)
    labels = {e.proto.label for e in at.get("download_button")}
    assert {"Download Quick PDF", "Download Markdown", "Download JSON"} <= labels
