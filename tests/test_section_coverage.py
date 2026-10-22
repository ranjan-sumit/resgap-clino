"""
Regression tests for "a paper silently contributes nothing".

A review paper whose headings are topics ("2. CFTR expression") landed in one
84k-character "_header" section; get_smart_excerpt skipped that section as too
big, so the wiki model saw no text, and the Lab extractor (which only read
sections named like "results") had nothing either.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import pdf_parser
from pipeline.pdf_parser import get_smart_excerpt, _sections_from_structure
from pipeline import param_extractor
from utils.azure_client import Success


def _seg(text, label="text", page=1):
    return {"text": text, "page": page, "label": label}


class SmartExcerptTests(unittest.TestCase):
    def test_a_section_bigger_than_the_budget_is_truncated_not_dropped(self):
        paper = {"sections": {"_header": "word " * 20000}}      # 100k chars, one blob
        out = get_smart_excerpt(paper, max_chars=10000)
        self.assertGreater(len(out), 5000)
        self.assertLessEqual(len(out), 10200)

    def test_priority_sections_still_come_first(self):
        paper = {"sections": {"1. Intro": "intro " * 50, "Results": "result text " * 50}}
        out = get_smart_excerpt(paper, max_chars=10000)
        self.assertLess(out.index("[Results]"), out.index("[1. Intro]"))

    def test_empty_sections_are_skipped(self):
        out = get_smart_excerpt({"sections": {"_header": "", "A": "  "}}, max_chars=1000)
        self.assertNotIn("[A]", out)


class StructuralSectionsTests(unittest.TestCase):
    def _run(self, segments):
        with patch("pipeline.docling_parser.extract_with_docling",
                   return_value={"text_segments": segments}):
            return _sections_from_structure("x.pdf", "x.pdf")

    def test_splits_at_headings_that_are_not_keywords(self):
        segs = [_seg("Title", "section_header"), _seg("front matter"),
                _seg("1. Introduction", "section_header"), _seg("intro body"),
                _seg("2. CFTR expression", "section_header"), _seg("cftr body"),
                _seg("3. Treatment", "section_header"), _seg("treat body")]
        s = self._run(segs)
        self.assertIn("2. CFTR expression", s)
        self.assertIn("cftr body", s["2. CFTR expression"])
        self.assertNotIn("cftr body", s["1. Introduction"])

    def test_page_furniture_is_not_included(self):
        segs = [_seg("1. A", "section_header"), _seg("body"), _seg("Journal 12", "page_header"),
                _seg("2. B", "section_header"), _seg("b"), _seg("3. C", "section_header"), _seg("c")]
        s = self._run(segs)
        self.assertNotIn("Journal 12", "".join(s.values()))

    def test_too_few_headings_returns_none_so_the_legacy_split_stays(self):
        self.assertIsNone(self._run([_seg("1. A", "section_header"), _seg("a"), _seg("b")]))

    def test_repeated_heading_names_do_not_overwrite_each_other(self):
        segs = [_seg("Results", "section_header"), _seg("first"),
                _seg("Methods", "section_header"), _seg("m"),
                _seg("Results", "section_header"), _seg("second"),
                _seg("End", "section_header"), _seg("e")]
        s = self._run(segs)
        self.assertEqual(sum("first" in v or "second" in v for v in s.values()), 2)

    def test_parser_failure_returns_none(self):
        with patch("pipeline.docling_parser.extract_with_docling", side_effect=RuntimeError("boom")):
            self.assertIsNone(_sections_from_structure("x.pdf", "x.pdf"))


class TableFilterTests(unittest.TestCase):
    def _tables(self, page_tables):
        page = MagicMock()
        page.extract_tables.return_value = page_tables
        pdf = MagicMock()
        pdf.pages = [page]
        cm = MagicMock()
        cm.__enter__.return_value = pdf
        with patch.object(pdf_parser.pdfplumber, "open", return_value=cm):
            return pdf_parser._extract_tables("x.pdf")

    def test_tables_with_every_cell_empty_are_dropped(self):
        self.assertEqual(self._tables([[[None], [""]], [["", " "], [None, ""]]]), [])

    def test_a_real_table_is_kept_with_its_text(self):
        out = self._tables([[["Test", "p"], ["Mann-Whitney", "0.01"]]])
        self.assertEqual(len(out), 1)
        self.assertIn("Mann-Whitney | 0.01", out[0]["content"])

    def test_a_table_with_a_single_filled_cell_is_kept(self):
        self.assertEqual(len(self._tables([[["", ""], ["", "x"]]])), 1)


class ParamContextTests(unittest.TestCase):
    def _prompt_for(self, sections):
        client = MagicMock()
        client.chat_json.return_value = Success("[]")
        wiki = {"pages": [{"title": "T", "key_findings": ["f"]}]}
        papers = [{"filename": "t.pdf", "sections": sections, "tables": []}]
        with patch.object(param_extractor, "get_cached_parameters", return_value=None), \
             patch.object(param_extractor, "save_cached_parameters"):
            param_extractor.extract_parameters(wiki, papers, client)
        return client.chat_json.call_args[0][1]

    def test_topic_headed_paper_still_sends_its_text(self):
        prompt = self._prompt_for({"2. CFTR expression": "CFTR is expressed at 3.2 mg/L " * 20})
        self.assertIn("CFTR is expressed", prompt)

    def test_empty_results_heading_is_topped_up_from_subsections(self):
        prompt = self._prompt_for({"3. Results": "", "3.1. The chip": "CBF rose by 41% " * 20})
        self.assertIn("CBF rose by 41%", prompt)

    def test_references_are_not_sent_as_evidence(self):
        prompt = self._prompt_for({"Intro": "x " * 100, "References": "SMITH J 2020 " * 100})
        self.assertNotIn("SMITH J 2020", prompt)

    def test_plenty_of_keyword_text_means_no_extra_sections(self):
        prompt = self._prompt_for({"3. Results": "r " * 2500, "2. Methods": "m " * 2500,
                                   "Other": "UNIQUE-OTHER-TEXT"})
        self.assertNotIn("UNIQUE-OTHER-TEXT", prompt)


if __name__ == "__main__":
    unittest.main()
