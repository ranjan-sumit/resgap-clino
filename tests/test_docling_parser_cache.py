"""
Tests for Clinova Phase 1 Story 1.1.1a/1.1.2: pipeline/docling_parser.py
checks the docling_extractions cache before running a real conversion, and
saves a genuine result after one. Docling conversion itself is mocked --
it is measured at ~1.1GB RSS / ~86s/paper on CPU
(evals/benchmarks/baseline/docling-resource-measurement.md), which is why
caching is a binding requirement this test suite must enforce, not just
document.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.docling_parser import extract_with_docling, DOCLING_STAGE_VERSION


class DoclingCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        self.tmp.write(b"%PDF-1.4 fake content for hashing purposes")
        self.tmp.close()

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    @patch("pipeline.docling_parser.get_cached_docling_extraction")
    def test_cache_hit_never_imports_or_runs_docling(self, mock_get_cached):
        mock_get_cached.return_value = {
            "filename": "p.pdf", "source": "docling", "full_text": "cached text",
            "char_count": 11, "tables": [],
        }

        with patch.dict("sys.modules", {"docling.document_converter": MagicMock()}):
            result = extract_with_docling(self.tmp.name, "p.pdf")

        self.assertTrue(result["from_cache"])
        self.assertEqual(result["full_text"], "cached text")

    @patch("pipeline.docling_parser.save_cached_docling_extraction")
    @patch("pipeline.docling_parser.get_cached_docling_extraction")
    def test_cache_miss_runs_conversion_and_saves_result(self, mock_get_cached, mock_save_cached):
        mock_get_cached.return_value = None

        fake_doc = MagicMock()
        fake_doc.export_to_markdown.return_value = "extracted markdown text"
        fake_doc.tables = []
        fake_converter = MagicMock()
        fake_converter.convert.return_value = MagicMock(document=fake_doc)

        fake_module = MagicMock()
        fake_module.DocumentConverter.return_value = fake_converter

        with patch.dict("sys.modules", {"docling.document_converter": fake_module}):
            result = extract_with_docling(self.tmp.name, "p.pdf")

        self.assertFalse(result["from_cache"])
        self.assertEqual(result["full_text"], "extracted markdown text")
        self.assertEqual(result["char_count"], len("extracted markdown text"))
        mock_save_cached.assert_called_once()
        # cache_key format: content_hash:none:stage_version (domain-invariant, AD-3)
        saved_cache_key = mock_save_cached.call_args[0][0]
        self.assertTrue(saved_cache_key.endswith(f":none:{DOCLING_STAGE_VERSION}"))

    @patch("pipeline.docling_parser.save_cached_docling_extraction")
    @patch("pipeline.docling_parser.get_cached_docling_extraction")
    def test_same_file_content_produces_same_cache_key(self, mock_get_cached, mock_save_cached):
        mock_get_cached.return_value = None
        fake_doc = MagicMock()
        fake_doc.export_to_markdown.return_value = "text"
        fake_doc.tables = []
        fake_module = MagicMock()
        fake_module.DocumentConverter.return_value.convert.return_value = MagicMock(document=fake_doc)

        with patch.dict("sys.modules", {"docling.document_converter": fake_module}):
            extract_with_docling(self.tmp.name, "p.pdf")
            extract_with_docling(self.tmp.name, "p_renamed.pdf")  # same bytes, different filename

        key1 = mock_save_cached.call_args_list[0][0][0]
        key2 = mock_save_cached.call_args_list[1][0][0]
        self.assertEqual(key1, key2)  # content-addressed, not filename-addressed


if __name__ == "__main__":
    unittest.main()
