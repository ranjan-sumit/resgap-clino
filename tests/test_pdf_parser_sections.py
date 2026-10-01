"""
Regression tests for pipeline/pdf_parser.py's section-header detection.

An earlier implementation tested each line with an unanchored re.search
over the section keywords, so ANY short body sentence merely containing a
keyword ("We took an approach based on...", "The results are shown in...")
was treated as a section header. A pseudo-"references" header then swallowed
the rest of the paper, and reference_extractor parsed body text as
citations -- fabricated references in the corpus. Detection is now
anchored: the stripped line must BE the keyword (optionally numbered /
punctuated / plural), not merely contain it.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.pdf_parser import _detect_section


class BodySentenceNotAHeaderTests(unittest.TestCase):
    def test_sentence_containing_reference_is_not_a_header(self):
        self.assertIsNone(_detect_section("We reference three datasets below."))

    def test_sentence_containing_approach_is_not_a_header(self):
        self.assertIsNone(_detect_section("We took an approach based on transfer learning."))

    def test_sentence_containing_results_is_not_a_header(self):
        self.assertIsNone(_detect_section("The results are summarized in Table 3."))

    def test_sentence_containing_methods_is_not_a_header(self):
        self.assertIsNone(_detect_section("Our methods are described elsewhere [4]."))

    def test_sentence_starting_with_keyword_is_not_a_header(self):
        self.assertIsNone(_detect_section("Methods for robust estimation are reviewed."))


class RealHeaderStillDetectedTests(unittest.TestCase):
    def test_plain_keywords(self):
        for line in ("Abstract", "Introduction", "Methods", "Results",
                     "Discussion", "Conclusion", "References"):
            self.assertEqual(_detect_section(line), line)

    def test_case_insensitive(self):
        self.assertEqual(_detect_section("REFERENCES"), "REFERENCES")
        self.assertEqual(_detect_section("abstract"), "abstract")

    def test_trailing_punctuation(self):
        self.assertEqual(_detect_section("REFERENCES:"), "REFERENCES:")

    def test_leading_numbering(self):
        self.assertEqual(_detect_section("3. Methods"), "3. Methods")
        self.assertEqual(_detect_section("1. Introduction"), "1. Introduction")
        self.assertEqual(_detect_section("2.3 Methodology"), "2.3 Methodology")
        self.assertEqual(_detect_section("4 Results"), "4 Results")

    def test_plural_headers(self):
        self.assertEqual(_detect_section("Limitations"), "Limitations")
        self.assertEqual(_detect_section("Conclusions"), "Conclusions")

    def test_multi_word_headers(self):
        self.assertEqual(_detect_section("Related Work"), "Related Work")
        self.assertEqual(_detect_section("Literature Review"), "Literature Review")
        self.assertEqual(_detect_section("Future Work"), "Future Work")

    def test_length_bounds_still_apply(self):
        self.assertIsNone(_detect_section("A"))
        self.assertIsNone(_detect_section("x" * 81))


if __name__ == "__main__":
    unittest.main()
