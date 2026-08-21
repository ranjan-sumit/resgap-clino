"""
Tests for Clinova Phase 1 Epic 1.3: pipeline/canonical_resolver.py resolves
references to a canonical identity via the DOI -> PMID -> OpenAlex ID ->
Semantic Scholar ID -> normalized(title+author+year) priority chain, merges
multi-provider records, and assigns the VERIFIED/ACCEPTED/QUARANTINED/
UNRESOLVED/REJECTED status model (05-data-architecture.md §5-6, ADR-007).

Story 1.3.4's regression cases load Benchmark v1's real fixtures (extracted
from the actual Data-17072026/ AuDHD corpus in Phase 0, not synthetic).
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.canonical_resolver import (
    resolve_canonical_identity, resolve_status, merge_canonical_references,
)

BENCHMARK_V1 = Path(__file__).resolve().parent.parent / "evals" / "benchmarks" / "v1"


class PriorityChainTests(unittest.TestCase):
    def test_doi_is_highest_priority(self):
        ref = {"doi": "10.1038/s41598-026-35440-6", "title": "Some Title", "year": 2026, "authors": ["Smith J"]}
        result = resolve_canonical_identity(ref)
        self.assertEqual(result["identity_level"], "doi")

    def test_pmid_used_when_no_doi_but_pubmed_source(self):
        ref = {"doi": "", "source_api": "pubmed", "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/"}
        result = resolve_canonical_identity(ref)
        self.assertEqual(result["identity_level"], "pmid")

    def test_pmid_not_used_for_non_pubmed_source(self):
        # A URL that happens to look like a pubmed link but isn't the
        # actual enrichment source must not be trusted as a PMID signal.
        ref = {"doi": "", "source_api": "crossref", "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
               "title": "X", "year": 2020, "authors": ["Doe J"]}
        result = resolve_canonical_identity(ref)
        self.assertNotEqual(result["identity_level"], "pmid")

    def test_ss_paper_id_used_when_no_doi_or_pmid(self):
        ref = {"doi": "", "ss_paper_id": "abc123"}
        result = resolve_canonical_identity(ref)
        self.assertEqual(result["identity_level"], "ss_paper_id")

    def test_arxiv_id_used_when_no_higher_priority_id(self):
        ref = {"doi": "", "ss_paper_id": "", "arxiv_id": "2301.12345"}
        result = resolve_canonical_identity(ref)
        self.assertEqual(result["identity_level"], "arxiv_id")

    def test_full_title_author_year_match_used_as_fallback(self):
        ref = {"title": "Some Real Paper Title", "authors": ["Smith J"], "year": 2023}
        result = resolve_canonical_identity(ref)
        self.assertEqual(result["identity_level"], "title_author_year")

    def test_title_only_partial_match_when_author_or_year_missing(self):
        # Missing year -- this is exactly the fallback-resolution shape
        # that must be quarantined, not treated as a confident match.
        ref = {"title": "Some Real Paper Title", "authors": ["Smith J"], "year": None}
        result = resolve_canonical_identity(ref)
        self.assertEqual(result["identity_level"], "title_only_partial")

    def test_nothing_usable_returns_none_level(self):
        ref = {"title": "", "authors": [], "year": None}
        result = resolve_canonical_identity(ref)
        self.assertEqual(result["identity_level"], "none")
        self.assertIsNone(result["identity_key"])

    def test_same_doi_different_case_produces_same_identity(self):
        r1 = resolve_canonical_identity({"doi": "10.1038/S41598-026-35440-6"})
        r2 = resolve_canonical_identity({"doi": "10.1038/s41598-026-35440-6"})
        self.assertEqual(r1["identity_key"], r2["identity_key"])


class ResolveStatusTests(unittest.TestCase):
    def test_status_mapping(self):
        self.assertEqual(resolve_status("doi"), "VERIFIED")
        self.assertEqual(resolve_status("pmid"), "VERIFIED")
        self.assertEqual(resolve_status("openalex_id"), "ACCEPTED")
        self.assertEqual(resolve_status("ss_paper_id"), "ACCEPTED")
        self.assertEqual(resolve_status("title_author_year"), "ACCEPTED")
        self.assertEqual(resolve_status("title_only_partial"), "QUARANTINED")
        self.assertEqual(resolve_status("none"), "UNRESOLVED")


class MergeCanonicalReferencesTests(unittest.TestCase):
    def test_two_records_with_same_doi_merge_into_one_canonical_entry(self):
        refs = [
            {"doi": "10.1/a", "title": "Paper A", "found_in_paper": "p1.pdf"},
            {"doi": "10.1/a", "title": "Paper A", "found_in_paper": "p2.pdf"},
        ]
        canonical = merge_canonical_references(refs)
        self.assertEqual(len(canonical), 1)
        self.assertEqual(len(canonical[0]["provider_records"]), 2)
        self.assertEqual(canonical[0]["resolution_status"], "VERIFIED")

    def test_different_dois_stay_separate(self):
        refs = [{"doi": "10.1/a"}, {"doi": "10.1/b"}]
        canonical = merge_canonical_references(refs)
        self.assertEqual(len(canonical), 2)

    def test_unresolved_references_kept_not_dropped(self):
        refs = [{"doi": "", "title": "", "authors": []}]
        canonical = merge_canonical_references(refs)
        self.assertEqual(len(canonical), 1)
        self.assertEqual(canonical[0]["resolution_status"], "UNRESOLVED")

    def test_provider_specific_metadata_preserved_separately(self):
        refs = [
            {"doi": "10.1/a", "title": "Title from provider 1", "source_api": "crossref"},
            {"doi": "10.1/a", "title": "Title from provider 2", "source_api": "openalex"},
        ]
        canonical = merge_canonical_references(refs)
        sources = {r["source_api"] for r in canonical[0]["provider_records"]}
        self.assertEqual(sources, {"crossref", "openalex"})


class BenchmarkV1RegressionTests(unittest.TestCase):
    """Story 1.3.4: regression tests against Benchmark v1's real fixtures
    (extracted from the actual Data-17072026/ AuDHD corpus in Phase 0)."""

    def test_duplicate_doi_case_merges_correctly(self):
        case = json.loads((BENCHMARK_V1 / "case-reference-duplicate-doi.json").read_text(encoding="utf-8"))
        groups = case["fixture_duplicate_groups"]
        self.assertEqual(len(groups), 3)  # 3 real duplicate-DOI pairs found in Phase 0

        for group in groups:
            canonical = merge_canonical_references(group)
            self.assertEqual(
                len(canonical), 1,
                f"expected the {len(group)} duplicate-DOI records for "
                f"{group[0].get('title')!r} to merge into 1 canonical reference, got {len(canonical)}",
            )
            self.assertEqual(len(canonical[0]["provider_records"]), len(group))
            self.assertIn(canonical[0]["resolution_status"], ("VERIFIED", "ACCEPTED"))

    def test_espanol_contamination_case_merges_but_relevance_filtering_is_out_of_scope(self):
        # This case has a real, valid, shared DOI -- canonical resolution
        # correctly identifies it as ONE reference (not 3 separate ones),
        # and a real DOI legitimately resolves VERIFIED. Whether this
        # reference actually belongs in an AuDHD-neuroimaging corpus is a
        # relevance-filtering question, a distinct pipeline stage not yet
        # built (05-data-architecture.md §1) -- this module intentionally
        # does not claim to reject it, and this test documents that
        # boundary rather than asserting a REJECTED status this module
        # cannot yet produce.
        case = json.loads((BENCHMARK_V1 / "case-reference-contamination-espanol.json").read_text(encoding="utf-8"))
        refs = case["fixture_references"]
        self.assertEqual(len(refs), 3)

        canonical = merge_canonical_references(refs)
        self.assertEqual(len(canonical), 1, "3 duplicate contamination records should still merge into 1")
        self.assertEqual(len(canonical[0]["provider_records"]), 3)
        self.assertEqual(canonical[0]["resolution_status"], "VERIFIED")  # real DOI -- correct per this module's scope

    def test_truncated_doi_case_does_not_crash_resolution(self):
        case = json.loads((BENCHMARK_V1 / "case-truncated-doi.json").read_text(encoding="utf-8"))
        refs = case["fixture_references"]
        canonical = merge_canonical_references(refs)
        # Each has a distinct truncated DOI -- they must not spuriously
        # merge with each other or crash, even though the underlying DOIs
        # are known-malformed (that's Story 1.1.3/1.1.4's problem to fix
        # upstream, not this module's).
        self.assertEqual(len(canonical), len(refs))


if __name__ == "__main__":
    unittest.main()
