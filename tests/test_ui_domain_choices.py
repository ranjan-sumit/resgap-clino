"""
The sidebar offers two domains -- Healthcare and General -- while the other
DOMAINS entries stay defined for saved runs and existing callers.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from domain_config import DOMAINS, get_ui_domain_choices, get_domain_config
from pipeline.deterministic_gap_patterns import detect_deterministic_gaps


class UiDomainChoiceTests(unittest.TestCase):
    def test_exactly_two_choices_healthcare_first(self):
        self.assertEqual([label for label, _ in get_ui_domain_choices()], ["Healthcare", "General"])

    def test_every_choice_maps_to_a_real_domain_config(self):
        for label, key in get_ui_domain_choices():
            self.assertIn(key, DOMAINS, f"{label} -> {key} is not a defined domain")
            self.assertTrue(get_domain_config(key)["description"])

    def test_healthcare_choice_keeps_the_healthcare_only_gap_patterns_active(self):
        # The deterministic pattern library only applies to the "Healthcare AI"
        # key, so the Healthcare choice must map to exactly that key.
        key = dict(get_ui_domain_choices())["Healthcare"]
        self.assertEqual(key, "Healthcare AI")
        self.assertEqual(detect_deterministic_gaps({}, dict(get_ui_domain_choices())["General"]), [])

    def test_other_domains_remain_defined_for_saved_runs(self):
        for legacy in ("NLP / LLMs", "Computer Vision", "Cybersecurity AI"):
            self.assertIn(legacy, DOMAINS)


if __name__ == "__main__":
    unittest.main()
