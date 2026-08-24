"""Epic 4.3: Corpus Contamination Rate metric, computed against the real
evals/benchmarks/v1 contamination fixture. No mocks -- filter_and_dedupe_
references() is pure (no API calls), so this runs the real function
against real fixture data.

This test documents a known, honest limitation: canonical_resolver.py
does not do relevance/off-topic filtering by design, so the contaminated
reference is currently ALWAYS retained. If this test ever starts failing
because the reference is no longer retained, that means relevance
filtering was added -- a deliberate signal to update this test and the
metric's known_limitation_note, not a regression to chase.
"""
from evals.regression.case_registry import CASE_TYPE_INDEX
from evals.regression.metrics import compute_corpus_contamination_rate


def test_contaminated_reference_is_currently_retained_as_verified():
    report = compute_corpus_contamination_rate()

    assert report["n_cases_evaluated"] == 1
    assert report["corpus_contamination_rate"] == 1.0
    assert report["n_retained_contaminated"] == 1
    assert report["case_results"][0]["retained"] is True
    assert "known_limitation_note" in report
    assert "does not perform relevance" in report["known_limitation_note"]


def test_case_registry_records_the_known_contaminated_doi():
    entry = CASE_TYPE_INDEX["v1"]["corpus-reference-contamination-espanol"]
    assert entry["contaminated_doi"] == "10.1353/hpn.2017.0025"
    assert "corpus_contamination_rate" in entry["feeds"]


def test_tie_against_equally_bad_champion_still_passes_the_hard_gate():
    """The promotion rule is 'no worse than' -- since this metric can't
    yet discriminate between pipeline versions, two runs reporting the
    same contamination rate must not permanently block promotion."""
    from evals.regression.promotion_gate import evaluate_promotion

    report = compute_corpus_contamination_rate()
    rate = report["corpus_contamination_rate"]
    result = evaluate_promotion(
        {"corpus_contamination_rate": rate}, {"corpus_contamination_rate": rate}
    )
    assert result["eligible"] is True
    assert result["hard_gate_failures"] == []
