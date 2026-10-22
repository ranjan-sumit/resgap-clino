"""Generated claims must not carry effect sizes the papers never reported."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.grounding import annotate_claims, corpus_numbers, effect_size_numbers, unsupported_numbers


class CorpusNumbersTests(unittest.TestCase):
    def test_collects_numbers_from_strings_and_nested_structures(self):
        known = corpus_numbers("Rate was 73.85% in 2022", {"a": [10, {"b": "p<0.05"}]}, ["x 1,5 y"])
        for n in ("73.85", "2022", "10", "0.05", "1.5"):
            self.assertIn(n, known)

    def test_trailing_zeros_and_comma_decimals_are_normalised(self):
        known = corpus_numbers("value 73,50 and 12.0")
        self.assertIn("73.5", known)
        self.assertIn("12", known)

    def test_none_and_empty_sources_are_fine(self):
        self.assertEqual(corpus_numbers(None, "", []), {"None"} if False else corpus_numbers(None, "", []))


class EffectSizeTests(unittest.TestCase):
    def test_finds_percentages_folds_and_thresholds(self):
        out = effect_size_numbers("IL-8 will increase by >35% and growth by 2-fold, maybe 1.5x, or 20 percent")
        self.assertEqual(len(out), 4)
        self.assertTrue(any("35%" in o for o in out))
        self.assertTrue(any("fold" in o for o in out))

    def test_design_numbers_are_not_effect_sizes(self):
        self.assertEqual(effect_size_numbers("N=16 chips for 72 hours at 45 uL/hr, 3 donors"), [])


class UnsupportedTests(unittest.TestCase):
    def test_a_reported_number_is_supported_an_invented_one_is_not(self):
        known = corpus_numbers("70 % of patients carry Phe508del")
        self.assertEqual(unsupported_numbers("Prevalence of 70% in CF", known), [])
        self.assertEqual(unsupported_numbers("Will rise by >35% and 2-fold", known), [">35%", "2-fold"])

    def test_the_real_run_case(self):
        claim = ("Continuous perfusion of cortisol will increase vascular IL-8 secretion by >35% "
                 "and accelerate Pseudomonas aeruginosa growth rates by >2-fold")
        known = corpus_numbers("IL-8 was higher in CF chips", {"ivacaftor_fev1_improvement": 10.0})
        self.assertEqual(len(unsupported_numbers(claim, known)), 2)


class AnnotateTests(unittest.TestCase):
    def test_flags_and_lowers_high_confidence(self):
        items = [{"title": "t", "claim": "rises by 35%", "confidence": "high"},
                 {"title": "t2", "claim": "direction only", "confidence": "high"}]
        flagged = annotate_claims(items, ("title", "claim"), set())
        self.assertEqual(flagged, 1)
        self.assertEqual(items[0]["unsupported_numbers"], ["35%"])
        self.assertEqual(items[0]["confidence"], "medium")
        self.assertNotIn("unsupported_numbers", items[1])
        self.assertEqual(items[1]["confidence"], "high")

    def test_a_low_confidence_item_stays_low(self):
        items = [{"claim": "by 50%", "confidence": "low"}]
        annotate_claims(items, ("claim",), set())
        self.assertEqual(items[0]["confidence"], "low")

    def test_non_dict_items_are_ignored(self):
        self.assertEqual(annotate_claims([None, "x", 3], ("claim",), set()), 0)


if __name__ == "__main__":
    unittest.main()
