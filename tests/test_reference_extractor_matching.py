"""
Regression tests for pipeline/reference_extractor.py's matching and
dedupe discipline:

- _ss_search_by_title used to return the FIRST Semantic Scholar hit that
  had an abstract, with no title check -- a related paper's metadata got
  returned (and cached) under the queried title when the true match had
  no abstract.
- _entry_to_reference used to take the last pre-year segment as the
  title, citing the journal name for Vancouver-style entries.
- dedupe keys used to come from the INPUT reference, so two entries
  resolving to the same DOI via different titles were both emitted.
- _crossref_search used to take items[0] with no title verification.
- the corpus-quality funnel's `unresolved` count used to be derived as
  structured_entries - resolved, mixing pre-cap/pre-dedup and
  post-cap/post-dedup units; it now comes from the enrichment loop's own
  per-entry outcomes.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import reference_extractor
from pipeline.corpus_quality import compute_corpus_quality


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


def _enriched(doi="10.1/shared"):
    return {
        "title": "Resolved Title", "year": 2020, "abstract": "An abstract.",
        "doi": doi, "arxiv_id": None, "authors": [], "venue": "",
        "citations": 1, "ss_paper_id": "", "openalex_id": "", "url": "",
        "open_access_url": None, "tier": 2, "source": "api_lookup",
    }


class SsTitleMatchTests(unittest.TestCase):
    def test_first_hit_with_abstract_but_wrong_title_is_not_accepted(self):
        queried = "Deep learning for autism spectrum detection"
        wrong = {"title": "A broad survey of machine learning methods", "year": 2021,
                 "abstract": "An abstract.", "authors": [], "externalIds": {},
                 "citationCount": 0}
        right = {"title": queried, "year": 2020, "abstract": "",
                 "authors": [], "externalIds": {}, "citationCount": 3}
        with patch("pipeline.reference_extractor.requests.get") as mock_get:
            mock_get.return_value = _FakeResponse(200, {"data": [wrong, right]})
            result = reference_extractor._ss_search_by_title(queried)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], queried)

    def test_true_match_without_abstract_beats_related_match_with_abstract(self):
        queried = "Normative modelling of brain charts"
        related = {"title": "Normative modelling for clinical neuroscience", "year": 2019,
                   "abstract": "An abstract.", "authors": [], "externalIds": {},
                   "citationCount": 9}
        exact = {"title": queried, "year": 2022, "abstract": "",
                 "authors": [], "externalIds": {}, "citationCount": 1}
        with patch("pipeline.reference_extractor.requests.get") as mock_get:
            mock_get.return_value = _FakeResponse(200, {"data": [related, exact]})
            result = reference_extractor._ss_search_by_title(queried)
        self.assertEqual(result["title"], queried)

    def test_nothing_above_threshold_returns_none(self):
        queried = "Hippocampal volume decline in early dementia"
        hits = [
            {"title": "Cardiac outcomes in intensive care", "year": 2018,
             "abstract": "An abstract.", "authors": [], "externalIds": {}, "citationCount": 0},
            {"title": "Pediatric asthma management review", "year": 2020,
             "abstract": "An abstract.", "authors": [], "externalIds": {}, "citationCount": 0},
        ]
        with patch("pipeline.reference_extractor.requests.get") as mock_get:
            mock_get.return_value = _FakeResponse(200, {"data": hits})
            self.assertIsNone(reference_extractor._ss_search_by_title(queried))


class CrossrefTitleVerificationTests(unittest.TestCase):
    def test_fuzzy_mismatch_is_rejected(self):
        queried = "Hippocampal volume in early dementia"
        item = {"DOI": "10.1/whatever",
                "title": ["Completely different topic in cardiology"],
                "author": [], "container-title": ["J Cardiol"],
                "published": {"date-parts": [[2019]]},
                "abstract": "", "URL": "https://doi.org/10.1/whatever",
                "is-referenced-by-count": 2}
        with patch("pipeline.reference_extractor.requests.get") as mock_get:
            mock_get.return_value = _FakeResponse(200, {"message": {"items": [item]}})
            self.assertIsNone(reference_extractor._crossref_search(queried))

    def test_exact_match_is_accepted(self):
        queried = "Hippocampal volume in early dementia"
        item = {"DOI": "10.1/hippocampal",
                "title": [queried],
                "author": [{"given": "A", "family": "Author"}],
                "container-title": ["NeuroImage"],
                "published": {"date-parts": [[2019]]},
                "abstract": "", "URL": "https://doi.org/10.1/hippocampal",
                "is-referenced-by-count": 2}
        with patch("pipeline.reference_extractor.requests.get") as mock_get:
            mock_get.return_value = _FakeResponse(200, {"message": {"items": [item]}})
            result = reference_extractor._crossref_search(queried)
        self.assertIsNotNone(result)
        self.assertEqual(result["doi"], "10.1/hippocampal")


class FallbackCitationParserTests(unittest.TestCase):
    def test_vancouver_entry_does_not_cite_journal_as_title(self):
        entry = "Smith J, Jones K. Title of study. NeuroImage. 2020;54:12-20."
        ref = reference_extractor._entry_to_reference(entry)
        self.assertEqual(ref["title"], "Title of study")
        self.assertEqual(ref["year"], 2020)


class ResolvedIdentityDedupeTests(unittest.TestCase):
    def _paper(self):
        return {"filename": "p.pdf", "sections": {"References":
            "[1] Smith J, Jones K. Alpha study of cognition. NeuroImage. 2020;54:12-20. "
            "[2] Brown T, Lee P. Beta analysis of memory. JAMA. 2019;2:100-8. "
            "[3] Kim R. Gamma review of attention. Lancet. 2021;5:44-51."}}

    def test_two_title_variants_resolving_to_one_doi_are_emitted_once(self):
        with patch("pipeline.reference_extractor.enrich_reference") as mock_enrich:
            mock_enrich.side_effect = lambda ref, delay=0.3: _enriched("10.1/shared")
            refs, diag = reference_extractor.extract_and_enrich_references(
                [self._paper()], client=None, return_diagnostics=True,
            )
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["doi"], "10.1/shared")
        self.assertEqual(diag["duplicates_skipped"], 2)

    def test_failed_enrichment_counts_each_input_entry_once_as_unresolved(self):
        state = {"calls": 0}

        def flaky_enrich(ref, delay=0.3):
            state["calls"] += 1
            if state["calls"] == 2:
                raise Exception("api down")
            return _enriched("10.1/shared")

        with patch("pipeline.reference_extractor.enrich_reference") as mock_enrich:
            mock_enrich.side_effect = flaky_enrich
            refs, diag = reference_extractor.extract_and_enrich_references(
                [self._paper()], client=None, return_diagnostics=True,
            )

        # entry 1 enriched, entry 2 enrichment failed, entry 3 deduped
        # against entry 1's resolved DOI -- each input entry counted once.
        self.assertEqual(diag["unresolved"], 1)
        self.assertEqual(diag["duplicates_skipped"], 1)
        self.assertEqual(len(refs), 2)

        metrics = compute_corpus_quality([{"completeness_score": 0.6}], diag)
        self.assertEqual(metrics["reference_funnel"]["unresolved"], 1)


if __name__ == "__main__":
    unittest.main()
