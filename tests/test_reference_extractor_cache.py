"""
Tests for Story 2.3: enrich_reference checks the references cache (keyed on
a single identity computed once from the input ref -- DOI, else arXiv ID,
else normalized title) before calling any external API, and only writes
back on a genuine Tier-2 metadata hit -- never on the Tier-3 "parsed_only"
fallback.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from pipeline import reference_extractor
from pipeline.reference_extractor import enrich_reference
from tests.pg_test_utils import new_test_schema, drop_test_schema


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


# Semantic Scholar-shaped hit. Deliberately carries a resolvable DOI in
# externalIds so DOI-based/arXiv-based tests also exercise the existing
# open-access lookup path (an extra requests.get call every successful
# DOI-bearing enrichment already made before this story -- unrelated to
# caching, just something the call-count assertions below must account for).
_SS_HIT = {
    "title": "A Cached Paper", "year": 2020, "abstract": "An abstract.",
    "authors": [{"name": "A Author"}], "externalIds": {"DOI": "10.1/resolved"},
    "citationCount": 5, "paperId": "ss123",
}

# OpenAlex-shaped hit with NO resolvable doi, so title-only tests exercise
# exactly one requests.get call per successful enrichment (no open-access
# follow-up call), keeping those assertions simple.
_OPENALEX_HIT = {
    "results": [{
        "title": "A Cached Paper", "publication_year": 2020,
        "abstract_inverted_index": {"An": [0], "abstract.": [1]},
        "doi": "",
    }]
}


class EnrichReferenceCacheTests(unittest.TestCase):
    def setUp(self):
        self.schema = new_test_schema()
        self.patcher = patch.object(db, "_SCHEMA", self.schema)
        self.patcher.start()
        db.init_db()

    def tearDown(self):
        self.patcher.stop()
        drop_test_schema(self.schema)

    def test_cache_miss_then_hit_skips_second_api_call(self):
        ref = {"doi": "10.1/abc", "title": "Original Title Here"}
        with patch("pipeline.reference_extractor.requests.get") as mock_get:
            mock_get.return_value = _FakeResponse(200, _SS_HIT)
            first = enrich_reference(ref, delay=0)
            self.assertEqual(first["tier"], 2)
            first_call_count = mock_get.call_count
            self.assertGreater(first_call_count, 0)

            second = enrich_reference(ref, delay=0)
            self.assertEqual(mock_get.call_count, first_call_count)  # not called again
            self.assertEqual(second, first)

    def test_title_only_ref_is_cached_under_title_identity(self):
        ref = {"title": "A Unique Title About Something"}
        with patch("pipeline.reference_extractor.requests.get") as mock_get:
            mock_get.return_value = _FakeResponse(200, _OPENALEX_HIT)
            first = enrich_reference(ref, delay=0)
            self.assertEqual(first["tier"], 2)
            first_call_count = mock_get.call_count
            self.assertGreater(first_call_count, 0)

            same_title_again = enrich_reference(dict(ref), delay=0)
            self.assertEqual(mock_get.call_count, first_call_count)  # cache hit
            self.assertEqual(same_title_again, first)

            different_ref = {"title": "A Completely Different Title Here"}
            enrich_reference(different_ref, delay=0)
            second_call_count = mock_get.call_count
            self.assertGreater(second_call_count, first_call_count)  # different identity -> real miss

            # The distinct title must have populated its OWN cache entry too.
            enrich_reference(dict(different_ref), delay=0)
            self.assertEqual(mock_get.call_count, second_call_count)  # cache hit

    def test_tier3_fallback_is_never_cached(self):
        ref = {"doi": "10.1/notfound", "title": "Unfindable Reference Title"}
        with patch("pipeline.reference_extractor.requests.get") as mock_get:
            mock_get.return_value = _FakeResponse(404, {})
            first = enrich_reference(ref, delay=0)
            self.assertEqual(first["tier"], 3)
            first_call_count = mock_get.call_count
            self.assertGreater(first_call_count, 0)

            enrich_reference(ref, delay=0)
            # Retried in full a second time -- proves the fallback wasn't cached.
            self.assertEqual(mock_get.call_count, first_call_count * 2)

    def test_doi_takes_priority_over_title(self):
        ref1 = {"doi": "10.1/priority", "title": "Original Title Here"}
        with patch("pipeline.reference_extractor.requests.get") as mock_get:
            mock_get.return_value = _FakeResponse(200, _SS_HIT)
            enrich_reference(ref1, delay=0)
            first_call_count = mock_get.call_count

            ref2 = {"doi": "10.1/priority", "title": "A Totally Different Title"}
            enrich_reference(ref2, delay=0)
            self.assertEqual(mock_get.call_count, first_call_count)  # same DOI -> still a hit

    def test_arxiv_id_takes_priority_over_title_when_no_doi(self):
        ref1 = {"arxiv_id": "1234.5678", "title": "Original Title Here"}
        with patch("pipeline.reference_extractor.requests.get") as mock_get:
            mock_get.return_value = _FakeResponse(200, _SS_HIT)
            enrich_reference(ref1, delay=0)
            first_call_count = mock_get.call_count

            ref2 = {"arxiv_id": "1234.5678", "title": "A Totally Different Title"}
            enrich_reference(ref2, delay=0)
            self.assertEqual(mock_get.call_count, first_call_count)  # same arXiv id -> still a hit

    def test_empty_identity_ref_is_never_cached_and_makes_no_api_calls(self):
        ref = {"doi": "", "arxiv_id": "", "title": ""}
        with patch("pipeline.reference_extractor.requests.get") as mock_get, \
             patch("pipeline.reference_extractor.get_cached_reference") as mock_get_cached, \
             patch("pipeline.reference_extractor.save_cached_reference") as mock_save_cached:
            enrich_reference(ref, delay=0)
            enrich_reference(ref, delay=0)
            self.assertEqual(mock_get.call_count, 0)
            mock_get_cached.assert_not_called()
            mock_save_cached.assert_not_called()

    def test_stage_version_bump_bypasses_a_previously_cached_entry(self):
        ref = {"doi": "10.1/versiontest", "title": "Original Title Here"}
        with patch("pipeline.reference_extractor.requests.get") as mock_get:
            mock_get.return_value = _FakeResponse(200, _SS_HIT)
            enrich_reference(ref, delay=0)
            first_call_count = mock_get.call_count

            with patch.object(reference_extractor, "REFERENCE_STAGE_VERSION", 2):
                enrich_reference(ref, delay=0)
                second_call_count = mock_get.call_count
                self.assertGreater(second_call_count, first_call_count)  # version bump -> real cache miss

                # The bumped-version entry must itself now be a hit.
                enrich_reference(ref, delay=0)
                self.assertEqual(mock_get.call_count, second_call_count)

    def test_identity_type_prefix_prevents_title_doi_collision(self):
        # A title that happens to equal another reference's raw DOI string
        # must NOT collide with it on the same cache_key (review finding).
        doi_ref = {"doi": "10.1/collide", "title": "Original Title Here"}
        title_ref = {"title": "10.1/collide"}
        with patch("pipeline.reference_extractor.requests.get") as mock_get:
            mock_get.return_value = _FakeResponse(200, _SS_HIT)
            enrich_reference(doi_ref, delay=0)
            first_call_count = mock_get.call_count
            self.assertGreater(first_call_count, 0)

            mock_get.return_value = _FakeResponse(200, _OPENALEX_HIT)
            enrich_reference(title_ref, delay=0)
            self.assertGreater(mock_get.call_count, first_call_count)  # real second lookup, not a false hit

    def test_cache_read_failure_does_not_abort_enrichment(self):
        ref = {"doi": "10.1/readfail", "title": "Original Title Here"}
        with patch("pipeline.reference_extractor.requests.get") as mock_get, \
             patch("pipeline.reference_extractor.get_cached_reference", side_effect=Exception("db locked")):
            mock_get.return_value = _FakeResponse(200, _SS_HIT)
            result = enrich_reference(ref, delay=0)
        self.assertEqual(result["tier"], 2)  # real lookup still ran despite the broken cache read

    def test_cache_write_failure_does_not_discard_successful_enrichment(self):
        ref = {"doi": "10.1/writefail", "title": "Original Title Here"}
        with patch("pipeline.reference_extractor.requests.get") as mock_get, \
             patch("pipeline.reference_extractor.save_cached_reference", side_effect=Exception("db locked")):
            mock_get.return_value = _FakeResponse(200, _SS_HIT)
            result = enrich_reference(ref, delay=0)
        self.assertEqual(result["tier"], 2)  # real result returned, not swallowed by the write failure


if __name__ == "__main__":
    unittest.main()
