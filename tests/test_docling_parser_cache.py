"""
Tests for pipeline/docling_parser.py (Clinova Phase 1 Story 1.1.1a/1.1.2,
engine swapped Docling -> PyMuPDF).

Cache behaviour is still enforced (content-addressed, stage-versioned, a
cache-write failure never discards a fresh result). The extraction itself is
now tested against REAL PDFs generated in-process with PyMuPDF -- no mocks of
the parser engine -- so heading/header/table/page-number logic is exercised
end to end.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf

from pipeline.docling_parser import extract_with_docling, DOCLING_STAGE_VERSION

BODY = "This is a body paragraph that describes the experimental setup in plain words."


def _make_pdf(path: str, pages: int = 3, with_table: bool = False) -> None:
    doc = pymupdf.open()
    for i in range(1, pages + 1):
        page = doc.new_page()
        page.insert_text((72, 30), "Journal of Testing 2026", fontsize=9)           # running header
        page.insert_text((72, 100), "Methods" if i == 2 else "Introduction", fontsize=18)
        page.insert_text((72, 140), BODY + f" (page {i})", fontsize=11)
        page.insert_text((72, 160), BODY, fontsize=11)
        page.insert_text((300, 820), str(i), fontsize=9)                              # page number
        if with_table and i == 1:
            x0, y0, cw, rh = 72, 300, 100, 24
            for r in range(4):
                page.draw_line((x0, y0 + r * rh), (x0 + 3 * cw, y0 + r * rh))
            for c in range(4):
                page.draw_line((x0 + c * cw, y0), (x0 + c * cw, y0 + 3 * rh))
            for r in range(3):
                for c in range(3):
                    page.insert_text((x0 + c * cw + 5, y0 + r * rh + 16), f"r{r}c{c}", fontsize=10)
    doc.save(path)
    doc.close()


class StructuralParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        self.tmp.close()

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def _run(self, **make_kwargs):
        _make_pdf(self.tmp.name, **make_kwargs)
        with patch("pipeline.docling_parser.get_cached_docling_extraction", return_value=None), \
             patch("pipeline.docling_parser.save_cached_docling_extraction") as save:
            return extract_with_docling(self.tmp.name, "p.pdf"), save

    def test_labels_and_real_page_numbers(self):
        result, save = self._run()
        segs = result["text_segments"]

        headings = [s for s in segs if s["label"] == "section_header"]
        self.assertEqual([(h["text"], h["page"]) for h in headings],
                         [("Introduction", 1), ("Methods", 2), ("Introduction", 3)])

        self.assertTrue(any(s["label"] == "page_header" and s["page"] == 2 for s in segs))
        self.assertEqual(sorted(s["page"] for s in segs if s["label"] == "page_number"), [1, 2, 3])

        body = [s for s in segs if s["label"] == "text"]
        self.assertTrue(body)
        self.assertTrue(all(BODY[:30] in s["text"] for s in body))
        self.assertIn("(page 2)", next(s["text"] for s in body if s["page"] == 2 and "(page" in s["text"]))
        save.assert_called_once()

    def test_full_text_marks_headings_and_excludes_running_headers(self):
        result, _ = self._run()
        self.assertIn("## Methods", result["full_text"])
        self.assertNotIn("Journal of Testing", result["full_text"])
        self.assertEqual(result["char_count"], len(result["full_text"]))
        self.assertEqual(result["source"], "docling")
        self.assertFalse(result["from_cache"])

    def test_tables_extracted_and_cells_not_duplicated_as_prose(self):
        result, _ = self._run(with_table=True)
        self.assertEqual(len(result["tables"]), 1)
        t = result["tables"][0]
        self.assertEqual((t["page"], t["rows"], t["cols"]), (1, 3, 3))
        self.assertIn("r1c1", t["content"])
        # not duplicated as prose; the table itself is its own "table" segment
        self.assertFalse(any("r1c1" in s["text"] for s in result["text_segments"] if s["label"] != "table"))
        self.assertEqual(sum(1 for s in result["text_segments"] if s["label"] == "table"), 1)

    def test_cache_hit_skips_extraction(self):
        _make_pdf(self.tmp.name)
        cached = {"filename": "p.pdf", "source": "docling", "full_text": "cached text",
                  "char_count": 11, "tables": []}
        with patch("pipeline.docling_parser.get_cached_docling_extraction", return_value=cached), \
             patch("pipeline.docling_parser.pymupdf.open") as opener:
            result = extract_with_docling(self.tmp.name, "p.pdf")
        self.assertTrue(result["from_cache"])
        self.assertEqual(result["full_text"], "cached text")
        opener.assert_not_called()

    def test_same_content_same_cache_key_and_versioned(self):
        _make_pdf(self.tmp.name)
        with patch("pipeline.docling_parser.get_cached_docling_extraction", return_value=None), \
             patch("pipeline.docling_parser.save_cached_docling_extraction") as save:
            extract_with_docling(self.tmp.name, "p.pdf")
            extract_with_docling(self.tmp.name, "p_renamed.pdf")
        k1, k2 = (c[0][0] for c in save.call_args_list)
        self.assertEqual(k1, k2)
        self.assertTrue(k1.endswith(f":none:{DOCLING_STAGE_VERSION}"))
        self.assertGreaterEqual(DOCLING_STAGE_VERSION, 3)  # v2 rows hold Docling output

    def test_cache_write_failure_does_not_discard_result(self):
        _make_pdf(self.tmp.name)
        with patch("pipeline.docling_parser.get_cached_docling_extraction", return_value=None), \
             patch("pipeline.docling_parser.save_cached_docling_extraction", side_effect=Exception("db locked")):
            result = extract_with_docling(self.tmp.name, "p.pdf")
        self.assertFalse(result["from_cache"])
        self.assertIn("Introduction", result["full_text"])


if __name__ == "__main__":
    unittest.main()
