"""
Tests for pipeline/deterministic_gap_patterns.py (Clinova Phase 3, Epic 3.2 --
the deterministic-pattern-library signal source of the Hybrid Gap Engine).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.deterministic_gap_patterns import detect_deterministic_gaps, PATTERNS


def _ev(evidence_type, text, paper_id="P1", confidence="medium"):
    return {"evidence_type": evidence_type, "text": text, "paper_id": paper_id, "confidence": confidence}


class DomainGateTests(unittest.TestCase):
    def test_non_healthcare_domain_returns_no_gaps(self):
        corpus = {"P1": [_ev("ComparatorBaseline", "compared against random baseline")]}
        self.assertEqual(detect_deterministic_gaps(corpus, "General AI/ML"), [])

    def test_empty_corpus_returns_no_gaps(self):
        self.assertEqual(detect_deterministic_gaps({}, "Healthcare AI"), [])


class AbsencePatternTests(unittest.TestCase):
    def test_missing_benchmark_comparison_fires_when_no_comparator_evidence_anywhere(self):
        corpus = {"P1": [_ev("Method", "we trained a CNN")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        ids = [g["pattern_id"] for g in gaps]
        self.assertIn("missing_benchmark_comparison", ids)

    def test_missing_benchmark_comparison_does_not_fire_when_comparator_evidence_exists(self):
        corpus = {"P1": [_ev("ComparatorBaseline", "compared against a random-forest baseline")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        ids = [g["pattern_id"] for g in gaps]
        self.assertNotIn("missing_benchmark_comparison", ids)

    def test_absence_pattern_gap_shape_matches_llm_gap_shape(self):
        corpus = {"P1": [_ev("Method", "we trained a CNN")]}
        gap = next(g for g in detect_deterministic_gaps(corpus, "Healthcare AI")
                    if g["pattern_id"] == "missing_benchmark_comparison")
        for key in ("title", "description", "gap_type", "confidence", "evidence",
                    "supporting_papers", "missing_connection", "why_important",
                    "validation_status", "existing_papers", "source"):
            self.assertIn(key, gap)
        self.assertEqual(gap["source"], "deterministic")
        self.assertEqual(gap["gap_type"], "benchmark")


class NoKeywordPatternTests(unittest.TestCase):
    def test_missing_calibration_fires_when_metrics_exist_without_calibration_keywords(self):
        corpus = {"P1": [_ev("Metric", "AUC of 0.89, sensitivity 0.81, specificity 0.76")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        ids = [g["pattern_id"] for g in gaps]
        self.assertIn("missing_calibration_assessment", ids)

    def test_missing_calibration_does_not_fire_when_calibration_keyword_present(self):
        corpus = {"P1": [_ev("Metric", "AUC 0.89; calibration assessed via Brier score of 0.11")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        ids = [g["pattern_id"] for g in gaps]
        self.assertNotIn("missing_calibration_assessment", ids)

    def test_missing_calibration_does_not_fire_when_no_metric_evidence_at_all(self):
        # requires_types guard: absence of Metric evidence entirely is an
        # extraction gap, not a reported-vs-not gap -- must not fire.
        corpus = {"P1": [_ev("Method", "we trained a CNN")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        ids = [g["pattern_id"] for g in gaps]
        self.assertNotIn("missing_calibration_assessment", ids)

    def test_keyword_match_in_one_paper_suppresses_corpus_wide_gap(self):
        # Corpus-level semantics: if ANY paper reports the positive signal,
        # the corpus doesn't have this specific gap, even if other papers
        # in the same corpus don't mention it.
        corpus = {
            "P1": [_ev("Metric", "AUC 0.90", paper_id="P1")],
            "P2": [_ev("Metric", "calibration curve showed good agreement", paper_id="P2")],
        }
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        ids = [g["pattern_id"] for g in gaps]
        self.assertNotIn("missing_calibration_assessment", ids)


class KeywordPresentPatternTests(unittest.TestCase):
    def test_single_center_fires_on_explicit_single_site_language(self):
        corpus = {"P1": [_ev("DatasetPopulation", "data collected from a single-center cohort of 400 patients")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        ids = [g["pattern_id"] for g in gaps]
        self.assertIn("single_center_study", ids)

    def test_single_center_does_not_fire_without_the_phrase(self):
        corpus = {"P1": [_ev("DatasetPopulation", "data collected from three academic medical centers")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        ids = [g["pattern_id"] for g in gaps]
        self.assertNotIn("single_center_study", ids)

    def test_retrospective_only_fires_without_prospective_counter_keyword(self):
        corpus = {"P1": [_ev("StudyDesign", "a retrospective cohort study")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        ids = [g["pattern_id"] for g in gaps]
        self.assertIn("retrospective_only_design", ids)

    def test_retrospective_does_not_fire_when_prospective_also_mentioned(self):
        corpus = {"P1": [_ev("StudyDesign", "retrospective training cohort with prospective external validation")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        ids = [g["pattern_id"] for g in gaps]
        self.assertNotIn("retrospective_only_design", ids)


class NamedLimitationTests(unittest.TestCase):
    def test_each_distinct_limitation_becomes_its_own_gap(self):
        corpus = {
            "P1": [_ev("Limitation", "Small sample size limits generalizability", paper_id="P1")],
            "P2": [_ev("Limitation", "No external validation was performed", paper_id="P2")],
        }
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        limitation_gaps = [g for g in gaps if g["pattern_id"] == "named_limitation_self_reported"]
        self.assertEqual(len(limitation_gaps), 2)
        self.assertEqual(limitation_gaps[0]["source"], "deterministic")

    def test_identical_limitation_text_across_papers_is_deduped(self):
        corpus = {
            "P1": [_ev("Limitation", "Small sample size limits generalizability", paper_id="P1")],
            "P2": [_ev("Limitation", "Small sample size limits generalizability", paper_id="P2")],
        }
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        limitation_gaps = [g for g in gaps if g["pattern_id"] == "named_limitation_self_reported"]
        self.assertEqual(len(limitation_gaps), 1)

    def test_no_limitation_evidence_produces_no_limitation_gaps(self):
        corpus = {"P1": [_ev("Method", "we trained a CNN")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        limitation_gaps = [g for g in gaps if g["pattern_id"] == "named_limitation_self_reported"]
        self.assertEqual(limitation_gaps, [])


class FutureWorkNotCountedAsDoneTests(unittest.TestCase):
    """Real-data regression (found validating against AuDHD_2.pdf's actual
    evidence, 2026-08-21): a FutureWork recommendation to do X is not
    evidence that X already happened -- must not suppress a no_keyword gap
    about whether X was reported as done."""

    def test_futurework_recommending_prospective_study_does_not_suppress_the_gap(self):
        corpus = {
            "P1": [
                _ev("StudyDesign", "a retrospective cohort study"),
                _ev("FutureWork", "Perform prospective longitudinal studies to corroborate these findings"),
            ],
        }
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        ids = [g["pattern_id"] for g in gaps]
        self.assertIn("no_prospective_deployment_evidence", ids)

    def test_actual_prospective_evidence_outside_futurework_still_suppresses_the_gap(self):
        corpus = {
            "P1": [
                _ev("StudyDesign", "a prospective clinical trial"),
                _ev("FutureWork", "Extend to a larger prospective cohort"),
            ],
        }
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        ids = [g["pattern_id"] for g in gaps]
        self.assertNotIn("no_prospective_deployment_evidence", ids)


class AvailabilityNegationGuardTests(unittest.TestCase):
    """A paper stating its data/code is NOT available affirms the
    no_data_code_availability gap -- the negated statement still contains
    the positive keyword ("not publicly available" contains "publicly
    available") and must not suppress it."""

    def test_negated_availability_statement_still_fires_the_gap(self):
        corpus = {"P1": [_ev("Method",
                             "the source data is not publicly available and no repository is provided")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        self.assertIn("no_data_code_availability", [g["pattern_id"] for g in gaps])

    def test_positive_availability_statement_still_suppresses_the_gap(self):
        corpus = {"P1": [_ev("Method", "our code is available on github.com")]}
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        self.assertNotIn("no_data_code_availability", [g["pattern_id"] for g in gaps])

    def test_positive_availability_in_another_paper_still_suppresses_corpus_wide(self):
        # Corpus-level semantics unchanged: a genuinely positive statement
        # anywhere suppresses the gap, even next to a negated one.
        corpus = {
            "P1": [_ev("Method", "the clinical data is not publicly available", paper_id="P1")],
            "P2": [_ev("Method", "code available on github.com", paper_id="P2")],
        }
        gaps = detect_deterministic_gaps(corpus, "Healthcare AI")
        self.assertNotIn("no_data_code_availability", [g["pattern_id"] for g in gaps])


class PatternLibraryIntegrityTests(unittest.TestCase):
    def test_every_pattern_has_a_unique_id(self):
        ids = [p["id"] for p in PATTERNS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_pattern_gap_type_is_in_the_existing_ui_enum(self):
        valid = {"methodology", "application", "dataset", "evaluation", "theory", "benchmark"}
        for p in PATTERNS:
            self.assertIn(p["gap_type"], valid, msg=f"pattern {p['id']} has invalid gap_type {p['gap_type']!r}")

    def test_every_pattern_has_a_recognized_mode(self):
        for p in PATTERNS:
            self.assertIn(p["mode"], ("absence", "no_keyword", "keyword_present"))


if __name__ == "__main__":
    unittest.main()
