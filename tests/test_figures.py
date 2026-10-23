"""PR-22d: figures are found from the PDF, shown to a model with their caption, and the answer is labelled."""
import unittest
from unittest.mock import MagicMock, patch

import fitz
import pytest

from pipeline import figures as fg
from pipeline.pdf_parser import get_smart_excerpt, parse_pdf
from tests.test_unreadable_pdfs import _TEXT
from utils.azure_client import ErrorInfo, Failure, Success


def _pix(w, h, grey=200):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), False)
    pix.clear_with(grey)
    return pix


def _pdf(tmp_path, build, name="f.pdf") -> str:
    doc = fitz.open()
    page = doc.new_page()
    build(page)
    path = str(tmp_path / name)
    doc.save(path)
    doc.close()
    return path


def _chart(page, rect):
    """A vector chart: many short lines inside `rect`."""
    for i in range(40):
        x = rect.x0 + 5 + i * (rect.width - 10) / 40
        page.draw_line((x, rect.y1 - 5), (x, rect.y1 - 10 - (i % 7) * 12), color=(0, 0, 0))


# ── finding figures ────────────────────────────────────────────────────────────────────────
def test_a_picture_with_a_caption_below_it_is_a_figure(tmp_path):
    def build(p):
        p.insert_text((60, 60), "Some body text before the figure.", fontsize=10)
        p.insert_image(fitz.Rect(80, 100, 480, 400), pixmap=_pix(400, 300))
        p.insert_text((80, 420), "Figure 1. Ranking of the therapies by respondents.", fontsize=9)
    found = fg.find_figures(_pdf(tmp_path, build))
    assert [(f["label"], f["page"], f["kind"]) for f in found] == [("Figure 1", 1, "raster")]
    x0, y0, x1, y1 = found[0]["bbox"]
    assert y0 <= 100 and y1 >= 420 and x0 <= 80 and x1 >= 480                     # the picture and its caption
    assert found[0]["caption"].startswith("Figure 1. Ranking")


def test_a_chart_drawn_as_vectors_is_a_figure(tmp_path):
    def build(p):
        _chart(p, fitz.Rect(80, 100, 480, 300))
        p.insert_text((80, 320), "Fig. 2: Cilia and mucus in healthy and diseased chips.", fontsize=9)
    found = fg.find_figures(_pdf(tmp_path, build))
    assert [(f["label"], f["kind"]) for f in found] == [("Figure 2", "vector")]


def test_a_caption_above_its_picture_is_found_too(tmp_path):
    def build(p):
        p.insert_text((80, 80), "Figure 3. A diagram of the device.", fontsize=9)
        p.insert_image(fitz.Rect(80, 100, 480, 400), pixmap=_pix(400, 300))
    assert [f["label"] for f in fg.find_figures(_pdf(tmp_path, build))] == ["Figure 3"]


def test_a_logo_next_to_a_caption_is_not_a_figure(tmp_path):
    def build(p):
        p.insert_image(fitz.Rect(480, 20, 530, 50), pixmap=_pix(50, 30))             # a publisher logo
        p.insert_text((80, 80), "Figure 1. Mentioned here but nothing is drawn.", fontsize=9)
    assert fg.find_figures(_pdf(tmp_path, build)) == []


def test_a_caption_with_nothing_drawn_beside_it_is_not_a_figure(tmp_path):
    def build(p):
        p.insert_text((80, 100), "Figure 1. A caption without a picture.", fontsize=9)
    assert fg.find_figures(_pdf(tmp_path, build)) == []


def test_a_sentence_that_starts_with_figure_n_is_not_a_caption(tmp_path):
    def build(p):
        p.insert_image(fitz.Rect(80, 150, 480, 400), pixmap=_pix(400, 250))
        p.insert_text((80, 130), "Figure 2 shows the results of the second experiment in detail.", fontsize=9)
    assert fg.find_figures(_pdf(tmp_path, build)) == []


def test_a_table_title_beside_a_picture_is_not_a_figure(tmp_path):
    def build(p):
        p.insert_image(fitz.Rect(80, 100, 480, 400), pixmap=_pix(400, 300))
        p.insert_text((80, 420), "Table 1. Summary of the sample.", fontsize=9)
    assert fg.find_figures(_pdf(tmp_path, build)) == []


def test_the_number_of_figures_is_capped(tmp_path):
    doc = fitz.open()
    for i in range(1, 6):
        page = doc.new_page()
        page.insert_image(fitz.Rect(80, 100, 480, 400), pixmap=_pix(400, 300))
        page.insert_text((80, 420), f"Figure {i}. Caption number {i} of the paper.", fontsize=9)
    path = str(tmp_path / "many.pdf")
    doc.save(path)
    assert [f["label"] for f in fg.find_figures(path, max_figures=3)] == ["Figure 1", "Figure 2", "Figure 3"]


def test_only_the_figure_region_is_rendered(tmp_path):
    def build(p):
        p.insert_image(fitz.Rect(80, 100, 280, 250), pixmap=_pix(200, 150))
        p.insert_text((80, 270), "Figure 1. Small figure.", fontsize=9)
    path = _pdf(tmp_path, build)
    fig = fg.find_figures(path)[0]
    png = fg.render_figure(path, fig)
    pix = fitz.Pixmap(png)
    assert png[:4] == b"\x89PNG" and pix.width < 595 * 150 / 72 * 0.6 and pix.height < 842 * 150 / 72 * 0.5


# ── what the model says ────────────────────────────────────────────────────────────────────
def test_numbers_that_are_in_neither_caption_nor_page_are_listed():
    desc = "Correctors scored 3.27 and potentiators 2.94 among 251 respondents (n=388)."
    assert fg.numbers_not_in_text(desc, "Figure 2. Ranking among 251 respondents.", "n=388 overall; 2.94 is mentioned") == ["3.27"]
    assert fg.numbers_not_in_text("about 5 and 7", "caption") == []              # single digits are ignored
    assert fg.numbers_not_in_text("0,5 and 12,5", "12.5 appears") == ["0,5"]       # comma decimals match point decimals


def test_unsupported_numbers_are_marked_with_a_star_and_a_note():
    out = fg.mark_unsupported("Scores 3.27 and 2.94, n=251, year 2022.", ["3.27", "251"])
    assert "3.27*" in out and "251*" in out and "2.94*" not in out and "2022*" not in out
    assert out.endswith("(* read from the image; not stated in the text)")
    assert fg.mark_unsupported("nothing to mark", []) == "nothing to mark"
    assert "13.27" in fg.mark_unsupported("13.27 and 3.27", ["3.27"]) and "13.27*" not in fg.mark_unsupported("13.27 and 3.27", ["3.27"])


def test_markdown_and_latex_in_the_answer_become_plain_text():
    raw = r"Chip **width** $1\text{ mm}$; pores $7\ \mu\text{m}$ across and $\beta$-Tubulin in green."
    out = fg.plain_text(raw)
    assert "**" not in out and "$" not in out and "\\" not in out
    assert "µm" in out and "β-Tubulin" in out and "1 mm" in out


def _figs(path_pages):
    return [{"label": f"Figure {i}", "page": i, "caption": f"Figure {i}. A chart of 40 and 12.", "bbox": (0, 0, 100, 100),
             "kind": "raster"} for i in range(1, path_pages + 1)]


def _text_pdf(tmp_path, pages):
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((50, 100), f"Page {i + 1}. {_TEXT[:150]} The value 40 is stated here.", fontsize=9)
    path = str(tmp_path / "t.pdf")
    doc.save(path)
    return path


def test_a_described_figure_carries_its_caption_a_clean_answer_and_its_unsupported_numbers(tmp_path):
    path = _text_pdf(tmp_path, 1)
    client = MagicMock()
    client.vision.return_value = Success("**Bars** at 40 and about $12$, rising to 77 in the last group.")
    with patch.object(fg, "render_figure", return_value=b"png"):
        out = fg.analyze_figures(path, client, _figs(1))
    assert out[0]["description"] == "Bars at 40 and about 12, rising to 77 in the last group."
    assert out[0]["numbers_not_in_text"] == ["77"] and out[0]["error"] is None
    sent = client.vision.call_args.kwargs
    assert "Figure 1. A chart of 40 and 12." in sent["user_text"] and "Describe only what is visible" in sent["system"]


def test_a_failed_or_empty_answer_is_an_error_and_never_a_description(tmp_path):
    path = _text_pdf(tmp_path, 2)
    client = MagicMock()
    client.vision.side_effect = [Failure(ErrorInfo(kind="timeout", detail="slow")), Success("   ")]
    with patch.object(fg, "render_figure", return_value=b"png"):
        out = fg.analyze_figures(path, client, _figs(2))
    assert [o["description"] for o in out] == ["", ""] and all(o["error"] for o in out)


# ── through the parser and the excerpt ─────────────────────────────────────────────────────
def _paper_pdf(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 550, 300), _TEXT * 3, fontsize=10)
    page.insert_image(fitz.Rect(80, 320, 480, 600), pixmap=_pix(400, 280))
    page.insert_text((80, 620), "Figure 1. Response rate by group.", fontsize=9)
    path = str(tmp_path / "paper.pdf")
    doc.save(path)
    return path


def test_figures_are_listed_without_any_model_and_described_only_when_vision_is_on(tmp_path):
    path = _paper_pdf(tmp_path)
    plain = parse_pdf(path, "paper.pdf")
    assert [f["label"] for f in plain["figure_list"]] == ["Figure 1"] and plain["figures"] == []
    client = MagicMock()
    client.vision.return_value = Success("Response rate is 40 in group A.")
    seen = []
    described = parse_pdf(path, "paper.pdf", client=client, use_vision=True, on_progress=seen.append)
    assert len(described["figures"]) == 1 and described["figures"][0]["label"] == "Figure 1" and seen == ["Figure 1 (1/1)"]


def test_the_excerpt_labels_model_read_figures_and_leaves_out_failed_ones():
    paper = {"filename": "p.pdf", "sections": {"Results": "Some results text."}, "full_text": "x", "tables": [],
             "figures": [{"label": "Figure 2", "page": 5, "description": "Bars at 3.27 and 2.94.", "numbers_not_in_text": ["3.27"],
                          "error": None},
                         {"label": "Figure 3", "page": 6, "description": "", "error": "TimeoutError"}]}
    out = get_smart_excerpt(paper)
    assert "described by a model from the images" in out and "Figure 2 (page 5)" in out and "3.27*" in out
    assert "Figure 3" not in out and "TimeoutError" not in out


# ── the router's image path is a model call like any other ─────────────────────────────────
class RouterVisionTests(unittest.TestCase):
    def _router(self):
        from utils.cost_guard import TokenBudget
        from utils.model_router import ModelConfig, ModelRouter, ModelSpec
        from utils.model_router import (ROLE_ANALYSIS, ROLE_COUNCIL_A, ROLE_COUNCIL_B, ROLE_COUNCIL_C, ROLE_COUNCIL_CHAIR,
                                        ROLE_EXTRACTION, ROLE_WIKI)
        spec = ModelSpec("gemini", "gemini-x")
        cfg = ModelConfig({r: spec for r in (ROLE_EXTRACTION, ROLE_WIKI, ROLE_ANALYSIS, ROLE_COUNCIL_A, ROLE_COUNCIL_B,
                                             ROLE_COUNCIL_C, ROLE_COUNCIL_CHAIR)}, spec)
        client = MagicMock()
        client.vision_model = "v"
        client.vision.return_value = Success("a chart")
        router = ModelRouter(cfg, {"gemini": "k"}, factory=lambda s, k, m: client)
        router.budget = TokenBudget(1_000_000)
        return router, client

    def test_the_data_rule_is_added_the_budget_is_charged_and_the_rate_limit_is_respected(self):
        from utils.model_router import VISION_IMAGE_TOKENS
        from utils.text_hygiene import DATA_GUARD
        router, client = self._router()
        with patch.object(router.limiter, "acquire") as acquire:
            router.vision("Read the figure.", "Caption: x", b"img")
        assert DATA_GUARD in client.vision.call_args.args[0] and acquire.called
        assert router.budget.used >= VISION_IMAGE_TOKENS

    def test_an_exhausted_budget_stops_further_image_calls(self):
        from utils.cost_guard import BudgetExceededError, TokenBudget
        router, client = self._router()
        router.budget = TokenBudget(10)
        router.budget.add(50)
        with pytest.raises(BudgetExceededError):
            router.vision("s", "u", b"img")
        assert not client.vision.called
