"""
Tests for Story 2.1 Task 3: compile_wiki_page checks the wiki_pages cache
before calling the LLM, and only writes back on a genuine, cleanly-parsed
success -- never on an LLMCallError fallback or a malformed-JSON stub.
Also covers the two bugs found during code review: empty-content cache-key
collisions across unrelated papers, and stale filename/char_count on a
legitimate cache hit for a renamed re-upload of the same content.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from utils.azure_client import Success, Failure, ErrorInfo
from pipeline import wiki_compiler
from pipeline.wiki_compiler import compile_wiki_page
from pipeline.page_index import build_tree


def _paper(text="Some paper full text about a novel method.", filename="paper.pdf"):
    return {"filename": filename, "full_text": text, "char_count": len(text), "sections": {}}


def _tree(paper=None):
    return build_tree(paper or _paper())


class CompileWikiPageCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.dir_patcher = patch.object(db, "DB_DIR", self.tmpdir)
        self.path_patcher = patch.object(db, "DB_PATH", self.tmpdir / "test.db")
        self.dir_patcher.start()
        self.path_patcher.start()
        db.init_db()

    def tearDown(self):
        self.dir_patcher.stop()
        self.path_patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cache_miss_then_hit_skips_second_llm_call_and_returns_full_dict(self):
        client = MagicMock()
        wiki_response = {"title": "A Paper", "contributions": ["x"], "year": "2024", "key_concepts": ["y"]}
        client.chat_json.return_value = Success(json.dumps(wiki_response))
        paper, tree = _paper(), _tree()

        first = compile_wiki_page(paper, tree, client, domain_config={"wiki_focus": "clinical"})
        self.assertEqual(client.chat_json.call_count, 1)

        second = compile_wiki_page(paper, tree, client, domain_config={"wiki_focus": "clinical"})
        self.assertEqual(client.chat_json.call_count, 1)  # not called again
        self.assertEqual(first, second)  # full dict equality, not just one field

    def test_different_domain_config_is_a_cache_miss(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"title": "A Paper", "contributions": []}))
        paper, tree = _paper(), _tree()

        compile_wiki_page(paper, tree, client, domain_config={"wiki_focus": "clinical"})
        compile_wiki_page(paper, tree, client, domain_config={"wiki_focus": "nlp"})

        self.assertEqual(client.chat_json.call_count, 2)  # different domain -> different key -> both call the LLM

    def test_stage_version_bump_bypasses_a_previously_cached_entry(self):
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"title": "A Paper", "contributions": []}))
        paper, tree = _paper(), _tree()

        compile_wiki_page(paper, tree, client, domain_config=None)
        self.assertEqual(client.chat_json.call_count, 1)

        with patch.object(wiki_compiler, "WIKI_STAGE_VERSION", 2):
            compile_wiki_page(paper, tree, client, domain_config=None)
        self.assertEqual(client.chat_json.call_count, 2)  # version bump -> real cache miss, LLM called again

    def test_llm_call_error_is_never_cached(self):
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="rate_limit", detail="429"))
        paper, tree = _paper(), _tree()

        result = compile_wiki_page(paper, tree, client, domain_config=None)
        self.assertIn("raw_response", result)  # fallback stub, existing Story 1.2 shape

        cache_key, _, _ = db.compute_cache_key(paper["full_text"], None, [], wiki_compiler.WIKI_STAGE_VERSION)
        self.assertIsNone(db.get_cached_wiki_page(cache_key))  # direct lookup, not just call-count inference

        client.chat_json.return_value = Success(json.dumps({"title": "Recovered", "contributions": []}))
        result2 = compile_wiki_page(paper, tree, client, domain_config=None)
        self.assertEqual(client.chat_json.call_count, 2)
        self.assertEqual(result2["title"], "Recovered")

    def test_llm_call_error_is_never_cached_with_a_real_domain_config(self):
        # The failure/malformed-response tests above all use domain_config=None;
        # this covers the domain-conditioned path too, since domain_hash
        # computation sits in the same code path.
        client = MagicMock()
        client.chat_json.return_value = Failure(ErrorInfo(kind="api_error", detail="down"))
        paper, tree = _paper(), _tree()
        domain_config = {"wiki_focus": "clinical"}

        compile_wiki_page(paper, tree, client, domain_config=domain_config)
        cache_key, _, _ = db.compute_cache_key(
            paper["full_text"], domain_config, wiki_compiler.WIKI_DOMAIN_KEYS, wiki_compiler.WIKI_STAGE_VERSION
        )
        self.assertIsNone(db.get_cached_wiki_page(cache_key))

    def test_malformed_json_response_is_never_cached(self):
        client = MagicMock()
        client.chat_json.return_value = Success("not valid json at all")
        paper, tree = _paper(), _tree()

        result = compile_wiki_page(paper, tree, client, domain_config=None)
        self.assertIn("raw_response", result)  # malformed stub

        cache_key, _, _ = db.compute_cache_key(paper["full_text"], None, [], wiki_compiler.WIKI_STAGE_VERSION)
        self.assertIsNone(db.get_cached_wiki_page(cache_key))  # direct lookup

        client.chat_json.return_value = Success(json.dumps({"title": "Recovered", "contributions": []}))
        result2 = compile_wiki_page(paper, tree, client, domain_config=None)
        self.assertEqual(client.chat_json.call_count, 2)
        self.assertEqual(result2["title"], "Recovered")

    def test_empty_full_text_is_never_cached_and_does_not_collide_across_papers(self):
        # Review finding: two DIFFERENT papers with no extractable text (e.g.
        # scanned/image-only PDFs) must not silently share a cache entry.
        client = MagicMock()
        client.chat_json.side_effect = [
            Success(json.dumps({"title": "Scanned Paper One", "contributions": []})),
            Success(json.dumps({"title": "Scanned Paper Two", "contributions": []})),
        ]
        paper_a = _paper(text="", filename="scan_a.pdf")
        paper_b = _paper(text="   ", filename="scan_b.pdf")  # whitespace-only counts as empty too

        result_a = compile_wiki_page(paper_a, _tree(paper_a), client, domain_config=None)
        result_b = compile_wiki_page(paper_b, _tree(paper_b), client, domain_config=None)

        self.assertEqual(client.chat_json.call_count, 2)  # never served from a shared empty-content cache entry
        self.assertEqual(result_a["title"], "Scanned Paper One")
        self.assertEqual(result_b["title"], "Scanned Paper Two")

    def test_cache_hit_re_stamps_filename_for_a_renamed_reupload(self):
        # Review finding: re-uploading identical content under a different
        # filename must still be attributed to the CURRENT filename, not
        # whichever paper first populated this cache entry.
        client = MagicMock()
        client.chat_json.return_value = Success(json.dumps({"title": "Shared Content", "contributions": []}))
        text = "Identical full text shared by two uploads."
        paper_v1 = _paper(text=text, filename="original_name.pdf")
        paper_v2 = _paper(text=text, filename="renamed_copy.pdf")

        first = compile_wiki_page(paper_v1, _tree(paper_v1), client, domain_config=None)
        second = compile_wiki_page(paper_v2, _tree(paper_v2), client, domain_config=None)

        self.assertEqual(client.chat_json.call_count, 1)  # genuine cache hit on the second call
        self.assertEqual(first["source_file"], "original_name.pdf")
        self.assertEqual(second["source_file"], "renamed_copy.pdf")  # re-stamped, not stale


if __name__ == "__main__":
    unittest.main()
