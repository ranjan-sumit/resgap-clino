"""
Tests for Story 2.1: the shared compute_cache_key() helper (AD-3) and the
wiki_pages cache table's read/write functions in utils/database.py.
"""
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db


class ComputeCacheKeyTests(unittest.TestCase):
    def test_same_content_domain_version_produce_same_key(self):
        k1, _, _ = db.compute_cache_key("hello", {"wiki_focus": "x"}, ["wiki_focus"], 1)
        k2, _, _ = db.compute_cache_key("hello", {"wiki_focus": "x"}, ["wiki_focus"], 1)
        self.assertEqual(k1, k2)

    def test_different_content_produces_different_key(self):
        k1, *_ = db.compute_cache_key("hello", None, [], 1)
        k2, *_ = db.compute_cache_key("world", None, [], 1)
        self.assertNotEqual(k1, k2)

    def test_different_domain_subset_produces_different_key(self):
        k1, *_ = db.compute_cache_key("hello", {"wiki_focus": "x"}, ["wiki_focus"], 1)
        k2, *_ = db.compute_cache_key("hello", {"wiki_focus": "y"}, ["wiki_focus"], 1)
        self.assertNotEqual(k1, k2)

    def test_unrelated_domain_keys_do_not_affect_key(self):
        # Only the relevant_domain_keys subset matters -- an unrelated key
        # changing (e.g. gap_priorities, irrelevant to wiki compilation)
        # must not cause a cache miss.
        domain_a = {"wiki_focus": "x", "gap_priorities": ["a"]}
        domain_b = {"wiki_focus": "x", "gap_priorities": ["b"]}
        k1, *_ = db.compute_cache_key("hello", domain_a, ["wiki_focus"], 1)
        k2, *_ = db.compute_cache_key("hello", domain_b, ["wiki_focus"], 1)
        self.assertEqual(k1, k2)

    def test_different_stage_logic_version_produces_different_key(self):
        k1, *_ = db.compute_cache_key("hello", None, [], 1)
        k2, *_ = db.compute_cache_key("hello", None, [], 2)
        self.assertNotEqual(k1, k2)

    def test_none_domain_config_gives_literal_none_domain_hash(self):
        key, content_hash, domain_hash = db.compute_cache_key("hello", None, [], 1)
        self.assertEqual(domain_hash, "none")
        self.assertEqual(key, f"{content_hash}:none:1")

    def test_empty_relevant_keys_gives_none_domain_hash_even_with_real_domain_config(self):
        # AD-3: "none" means the STAGE is domain-invariant (empty
        # relevant_domain_keys), regardless of whether a domain_config
        # object happens to be passed in.
        _, _, domain_hash = db.compute_cache_key("hello", {"wiki_focus": "x"}, [], 1)
        self.assertEqual(domain_hash, "none")

    def test_none_content_does_not_crash(self):
        # A caller passing content=None (e.g. paper.get("full_text") without
        # a default) must not crash on .encode().
        key, content_hash, _ = db.compute_cache_key(None, None, [], 1)
        self.assertEqual(content_hash, hashlib.sha256(b"").hexdigest())


class WikiPagesCacheTests(unittest.TestCase):
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

    def test_cache_miss_returns_none(self):
        self.assertIsNone(db.get_cached_wiki_page("does-not-exist"))

    def test_save_then_get_round_trips(self):
        db.save_cached_wiki_page("key1", "ch1", "dh1", 1, {"title": "Test Paper", "contributions": ["a"]})
        result = db.get_cached_wiki_page("key1")
        self.assertEqual(result, {"title": "Test Paper", "contributions": ["a"]})

    def test_insert_or_replace_overwrites_existing_entry(self):
        db.save_cached_wiki_page("key1", "ch1", "dh1", 1, {"title": "First"})
        db.save_cached_wiki_page("key1", "ch1", "dh1", 1, {"title": "Second"})
        result = db.get_cached_wiki_page("key1")
        self.assertEqual(result["title"], "Second")

    def test_corrupted_row_is_treated_as_a_miss_not_a_crash(self):
        # A storage-layer problem (partial write, manual edit, future
        # migration bug) must degrade to "cache miss", not crash the caller.
        conn = db._get_conn()
        conn.execute(
            "INSERT INTO wiki_pages (cache_key, content_hash, domain_hash, "
            "stage_logic_version, wiki_json) VALUES (?,?,?,?,?)",
            ("corrupt-key", "ch", "dh", 1, "{not valid json"),
        )
        conn.commit()
        conn.close()
        self.assertIsNone(db.get_cached_wiki_page("corrupt-key"))


class ParametersCacheTests(unittest.TestCase):
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

    def test_cache_miss_returns_none(self):
        self.assertIsNone(db.get_cached_parameters("does-not-exist"))

    def test_save_then_get_round_trips(self):
        params = [{"name": "prevalence", "value": 12.5, "category": "prevalence"}]
        db.save_cached_parameters("key1", "ch1", 1, params)
        result = db.get_cached_parameters("key1")
        self.assertEqual(result, params)

    def test_insert_or_replace_overwrites_existing_entry(self):
        db.save_cached_parameters("key1", "ch1", 1, [{"name": "first"}])
        db.save_cached_parameters("key1", "ch1", 1, [{"name": "second"}])
        result = db.get_cached_parameters("key1")
        self.assertEqual(result, [{"name": "second"}])

    def test_corrupted_row_is_treated_as_a_miss_not_a_crash(self):
        conn = db._get_conn()
        conn.execute(
            "INSERT INTO parameters (cache_key, content_hash, stage_logic_version, params_json) "
            "VALUES (?,?,?,?)",
            ("corrupt-key", "ch", 1, "[not valid json"),
        )
        conn.commit()
        conn.close()
        self.assertIsNone(db.get_cached_parameters("corrupt-key"))


class ReferencesCacheTests(unittest.TestCase):
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

    def test_cache_miss_returns_none(self):
        self.assertIsNone(db.get_cached_reference("does-not-exist"))

    def test_save_then_get_round_trips(self):
        ref = {"title": "A Paper", "doi": "10.1/abc", "tier": 2, "source": "crossref"}
        db.save_cached_reference("key1", "ch1", 1, ref)
        result = db.get_cached_reference("key1")
        self.assertEqual(result, ref)

    def test_insert_or_replace_overwrites_existing_entry(self):
        db.save_cached_reference("key1", "ch1", 1, {"title": "First"})
        db.save_cached_reference("key1", "ch1", 1, {"title": "Second"})
        result = db.get_cached_reference("key1")
        self.assertEqual(result, {"title": "Second"})

    def test_corrupted_row_is_treated_as_a_miss_not_a_crash(self):
        conn = db._get_conn()
        conn.execute(
            'INSERT INTO "references" (cache_key, doi_or_title_hash, stage_logic_version, enriched_json) '
            "VALUES (?,?,?,?)",
            ("corrupt-key", "ch", 1, "{not valid json"),
        )
        conn.commit()
        conn.close()
        self.assertIsNone(db.get_cached_reference("corrupt-key"))

    def test_null_row_is_treated_as_a_miss_not_a_crash(self):
        conn = db._get_conn()
        conn.execute(
            'INSERT INTO "references" (cache_key, doi_or_title_hash, stage_logic_version, enriched_json) '
            "VALUES (?,?,?,?)",
            ("null-key", "ch", 1, None),
        )
        conn.commit()
        conn.close()
        self.assertIsNone(db.get_cached_reference("null-key"))

    def test_non_dict_json_is_treated_as_a_miss_not_a_crash(self):
        conn = db._get_conn()
        conn.execute(
            'INSERT INTO "references" (cache_key, doi_or_title_hash, stage_logic_version, enriched_json) '
            "VALUES (?,?,?,?)",
            ("list-key", "ch", 1, "[1, 2, 3]"),
        )
        conn.commit()
        conn.close()
        self.assertIsNone(db.get_cached_reference("list-key"))


class GapValidationsCacheTests(unittest.TestCase):
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

    def test_cache_miss_returns_none(self):
        self.assertIsNone(db.get_cached_gap_validation("does-not-exist"))

    def test_save_then_get_round_trips(self):
        validation = {"validation_status": "open", "validation_reasoning": "no papers", "existing_papers": [], "search_query_used": "q"}
        db.save_cached_gap_validation("key1", "gh1", "dh1", 1, validation)
        result = db.get_cached_gap_validation("key1")
        self.assertEqual(result, validation)

    def test_insert_or_replace_overwrites_existing_entry(self):
        first = {"validation_status": "open", "validation_reasoning": "r1", "existing_papers": [], "search_query_used": "q1"}
        second = {"validation_status": "solved", "validation_reasoning": "r2", "existing_papers": [], "search_query_used": "q2"}
        db.save_cached_gap_validation("key1", "gh1", "dh1", 1, first)
        db.save_cached_gap_validation("key1", "gh1", "dh1", 1, second)
        result = db.get_cached_gap_validation("key1")
        self.assertEqual(result, second)

    def test_row_missing_a_required_key_is_treated_as_a_miss_not_a_crash(self):
        conn = db._get_conn()
        conn.execute(
            "INSERT INTO gap_validations (cache_key, gap_hash, domain_hash, "
            "stage_logic_version, validation_json) VALUES (?,?,?,?,?)",
            ("incomplete-key", "gh", "dh", 1, json.dumps({"validation_status": "open"})),
        )
        conn.commit()
        conn.close()
        self.assertIsNone(db.get_cached_gap_validation("incomplete-key"))

    def test_corrupted_row_is_treated_as_a_miss_not_a_crash(self):
        conn = db._get_conn()
        conn.execute(
            "INSERT INTO gap_validations (cache_key, gap_hash, domain_hash, "
            "stage_logic_version, validation_json) VALUES (?,?,?,?,?)",
            ("corrupt-key", "gh", "dh", 1, "{not valid json"),
        )
        conn.commit()
        conn.close()
        self.assertIsNone(db.get_cached_gap_validation("corrupt-key"))

    def test_null_row_is_treated_as_a_miss_not_a_crash(self):
        conn = db._get_conn()
        conn.execute(
            "INSERT INTO gap_validations (cache_key, gap_hash, domain_hash, "
            "stage_logic_version, validation_json) VALUES (?,?,?,?,?)",
            ("null-key", "gh", "dh", 1, None),
        )
        conn.commit()
        conn.close()
        self.assertIsNone(db.get_cached_gap_validation("null-key"))

    def test_non_dict_json_is_treated_as_a_miss_not_a_crash(self):
        conn = db._get_conn()
        conn.execute(
            "INSERT INTO gap_validations (cache_key, gap_hash, domain_hash, "
            "stage_logic_version, validation_json) VALUES (?,?,?,?,?)",
            ("list-key", "gh", "dh", 1, "[1, 2, 3]"),
        )
        conn.commit()
        conn.close()
        self.assertIsNone(db.get_cached_gap_validation("list-key"))


if __name__ == "__main__":
    unittest.main()
