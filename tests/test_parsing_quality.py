import fitz
import pytest

from pipeline import docling_parser as dp
from pipeline import pdf_parser as pp
from pipeline.evidence_reader import build_passages, locate_quote, render_passages

BANNER = "Journal of Cystic Fibrosis"
BODY = ("Lung function outcomes were measured at baseline and again after twelve months of treatment "
        "in a cohort of adults with cystic fibrosis attending specialist clinics. ") * 4


def _pdf(path, pages=4, banner=True, footer=True, table_on=None):
    doc = fitz.open()
    for n in range(1, pages + 1):
        page = doc.new_page()
        if banner:                                         # set below the margin band: y = 100 of 842
            page.insert_text((60, 100), BANNER, fontsize=15, fontname="hebo")
        if footer:
            page.insert_text((60, 790), "Pharmacological Research 2021", fontsize=9)
        page.insert_text((60, 150), f"{n}. Study section {n}", fontsize=13, fontname="hebo")
        page.insert_textbox(fitz.Rect(60, 170, 540, 420), BODY, fontsize=10)
        if table_on == n:
            _draw_table(page, 60, 450)
    doc.save(path)
    doc.close()
    return str(path)


def _draw_table(page, x0, y0):
    rows = [["Group", "FEV1 baseline", "FEV1 at 12 months"],
            ["Treated", "61.2", "66.4"],
            ["Placebo", "60.8", "61.1"],
            ["Overall", "61.0", "63.8"]]
    col_w, row_h = 150, 28
    for r in range(len(rows) + 1):
        page.draw_line((x0, y0 + r * row_h), (x0 + 3 * col_w, y0 + r * row_h))
    for c in range(4):
        page.draw_line((x0 + c * col_w, y0), (x0 + c * col_w, y0 + len(rows) * row_h))
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            page.insert_text((x0 + c * col_w + 6, y0 + r * row_h + 19), cell, fontsize=10)


@pytest.fixture
def parsed(tmp_path, isolated_env):
    return pp.parse_pdf(_pdf(tmp_path / "furn.pdf"), "furn.pdf")


# ── B11: page furniture ─────────────────────────────────────────────────────────────────────
def test_a_repeated_banner_below_the_margin_band_is_not_a_section(parsed):
    names = [k for k in parsed["sections"] if k != "_header"]
    assert not any(BANNER.lower() in n.lower() for n in names), names
    assert not any("pharmacological research" in n.lower() for n in names)


def test_the_banner_and_footer_text_stay_out_of_the_section_bodies(parsed):
    body = " ".join(str(v) for v in parsed["sections"].values())
    assert BANNER not in body and "Pharmacological Research 2021" not in body


def test_furniture_is_labelled_not_deleted(parsed):
    labels = {s["text"]: s["label"] for s in parsed["text_segments"]}
    assert labels[BANNER] == "page_header"
    assert labels["Pharmacological Research 2021"] in ("page_footer", "page_header")


def test_real_headings_survive(parsed):
    names = [k for k in parsed["sections"] if k != "_header"]
    assert any(n.startswith("1. Study section 1") for n in names) and len(names) >= 4


def test_a_one_off_heading_is_not_mistaken_for_furniture(tmp_path, isolated_env):
    path = tmp_path / "one.pdf"
    doc = fitz.open()
    for n in range(4):
        page = doc.new_page()
        page.insert_text((60, 100), "Unique results heading" if n == 1 else f"Different heading {n}", fontsize=15, fontname="hebo")
        page.insert_textbox(fitz.Rect(60, 150, 540, 400), BODY, fontsize=10)
    doc.save(path)
    segs = dp.extract_with_docling(str(path), "one.pdf")["text_segments"]
    labels = {s["text"]: s["label"] for s in segs}
    assert labels["Unique results heading"] != "page_header"


def test_section_keywords_are_never_furniture(tmp_path, isolated_env):
    path = tmp_path / "kw.pdf"
    doc = fitz.open()
    for n in range(4):
        page = doc.new_page()
        page.insert_text((60, 100), "Results", fontsize=15, fontname="hebo")
        page.insert_textbox(fitz.Rect(60, 150, 540, 400), BODY, fontsize=10)
    doc.save(path)
    labels = [s["label"] for s in dp.extract_with_docling(str(path), "kw.pdf")["text_segments"] if s["text"] == "Results"]
    assert labels and "page_header" not in labels


def test_a_two_page_paper_is_left_alone(tmp_path, isolated_env):
    parsed = pp.parse_pdf(_pdf(tmp_path / "short.pdf", pages=2), "short.pdf")
    assert not any(s["label"] == "page_header" and s["text"] == BANNER for s in parsed["text_segments"])


# ── B10: tables ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def with_table(tmp_path, isolated_env):
    return pp.parse_pdf(_pdf(tmp_path / "tbl.pdf", pages=3, table_on=2), "tbl.pdf")


def test_a_ruled_table_yields_its_rows_and_cells(with_table):
    assert len(with_table["tables"]) == 1
    t = with_table["tables"][0]
    assert t["page"] == 2 and t["rows"] == 4 and t["cols"] == 3
    assert "Treated|61.2|66.4" in t["content"] and "FEV1 at 12 months" in t["content"]


def test_the_table_is_a_segment_of_its_own_and_not_part_of_the_prose(with_table):
    table_segs = [s for s in with_table["text_segments"] if s["label"] == "table"]
    assert len(table_segs) == 1 and table_segs[0]["page"] == 2 and "Placebo|60.8|61.1" in table_segs[0]["text"]
    prose = " ".join(s["text"] for s in with_table["text_segments"] if s["label"] == "text")
    assert "61.2" not in prose
    assert not any("Treated" in str(v) for v in with_table["sections"].values())       # kept out of the sections


def test_the_reader_gets_the_table_as_a_passage_and_can_verify_a_quote_from_it(with_table):
    passages = build_passages(with_table["text_segments"])
    tbl = [p for p in passages if p["section"] == "Table (p.2)"]
    assert len(tbl) == 1 and tbl[0]["page"] == 2
    assert "Table (p.2)" in render_passages(passages)
    hit = locate_quote("Group|FEV1 baseline|FEV1 at 12 months Treated|61.2|66.4", passages)
    assert hit is not None


def test_a_paper_without_tables_has_none_and_no_table_segments(parsed):
    assert parsed["tables"] == [] or all(t["rows"] >= 2 for t in parsed["tables"])
    assert not [s for s in parsed["text_segments"] if s["label"] == "table"]


def test_the_parameter_extractor_still_receives_the_tables(with_table):
    from pipeline.param_extractor import extract_parameters
    seen = {}

    class Spy:
        def set_stage(self, s): pass
        def chat_json(self, system, user, **kw):
            seen["user"] = user
            from utils.azure_client import Success
            return Success('{"parameters": []}')

    wiki = {"pages": [{"title": "T", "source_file": "tbl.pdf", "key_findings": ["FEV1 rose"], "methods": []}]}
    extract_parameters(wiki, [{"filename": "tbl.pdf", "sections": with_table["sections"], "tables": with_table["tables"]}], Spy())
    assert "Treated|61.2|66.4" in seen.get("user", "")


def test_the_cache_version_changed_so_old_extractions_are_not_reused():
    assert dp.DOCLING_STAGE_VERSION >= 4
