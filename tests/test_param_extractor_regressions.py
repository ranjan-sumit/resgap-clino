"""
Regression tests for pipeline/param_extractor.py input handling:

- extract_parameters padded the wiki["pages"] list IN PLACE when a paper
  had no compiled wiki page, leaking stub pages into the live wiki dict
  also consumed by graph_builder, gap_detector and evidence_linker.
- a table dict without a "page" key raised KeyError inside the context
  building, losing the whole paper's parameter extraction.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from utils.azure_client import Success
from pipeline.param_extractor import extract_parameters
from tests.pg_test_utils import new_test_schema, drop_test_schema


def _page(title="Paper One"):
    return {
        "title": title, "source_file": f"{title}.pdf",
        "key_findings": [], "limitations": [], "methods": [],
        "datasets": [], "contributions": [],
    }


class ParamExtractorInputHandlingTests(unittest.TestCase):
    def setUp(self):
        self.schema = new_test_schema()
        self.patcher = patch.object(db, "_SCHEMA", self.schema)
        self.patcher.start()
        db.init_db()

    def tearDown(self):
        self.patcher.stop()
        drop_test_schema(self.schema)

    def test_stub_padding_does_not_mutate_caller_wiki_pages(self):
        client = MagicMock()
        client.chat_json.return_value = Success("[]")
        wiki = {"pages": []}
        papers = [
            {"filename": "a.pdf", "sections": {}, "tables": []},
            {"filename": "b.pdf", "sections": {}, "tables": []},
        ]

        result = extract_parameters(wiki, papers, client)

        self.assertEqual(wiki["pages"], [])  # no stub leaked into the live dict
        self.assertEqual(client.chat_json.call_count, 2)  # every paper still processed
        self.assertEqual(result, [])

    def test_table_without_page_key_does_not_crash_extraction(self):
        client = MagicMock()
        client.chat_json.return_value = Success("[]")
        wiki = {"pages": [_page()]}
        papers = [{
            "filename": "Paper One.pdf", "sections": {},
            "tables": [{"content": "a | b", "rows": 2, "cols": 2}],  # no "page" key
        }]

        result = extract_parameters(wiki, papers, client)

        self.assertEqual(client.chat_json.call_count, 1)  # the paper was processed
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
