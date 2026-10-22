"""The graph vocabulary must fit the corpus: the Healthcare-AI one (model_architecture, predicts,
diagnoses...) only for ML/simulation studies, a general biomedical-science one otherwise."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.graph_builder import _vocabulary_prompt
from domain_config import get_domain_config


def studies(*types):
    return {f"p{i}.pdf": [{"evidence_type": "StudyDesign", "text": f"[study_type: {t}] x"}] for i, t in enumerate(types)}


BASE = "BASE PROMPT"
DOMAIN = get_domain_config("Healthcare AI")


class VocabularyTests(unittest.TestCase):
    def test_a_lab_review_survey_corpus_gets_the_science_vocabulary(self):
        out = _vocabulary_prompt(BASE, DOMAIN, studies("in_vitro_or_lab", "systematic_or_narrative_review",
                                                       "survey_or_questionnaire"))
        self.assertIn("model_system", out)
        self.assertIn("never a task", out)
        self.assertNotIn("DOMAIN-SPECIFIC ENTITY TYPES", out)

    def test_an_ml_study_keeps_the_configured_domain_vocabulary(self):
        out = _vocabulary_prompt(BASE, DOMAIN, studies("ml_prediction_model", "in_vitro_or_lab"))
        self.assertIn("DOMAIN-SPECIFIC ENTITY TYPES", out)
        self.assertNotIn("model_system", out)

    def test_a_simulation_study_also_keeps_it(self):
        self.assertIn("DOMAIN-SPECIFIC ENTITY TYPES", _vocabulary_prompt(BASE, DOMAIN, studies("computational_simulation")))

    def test_unknown_study_types_keep_the_configured_vocabulary(self):
        self.assertIn("DOMAIN-SPECIFIC ENTITY TYPES", _vocabulary_prompt(BASE, DOMAIN, {}))
        self.assertIn("DOMAIN-SPECIFIC ENTITY TYPES", _vocabulary_prompt(BASE, DOMAIN, None))

    def test_the_base_prompt_is_always_kept(self):
        self.assertTrue(_vocabulary_prompt(BASE, DOMAIN, studies("in_vitro_or_lab")).startswith(BASE))
        self.assertTrue(_vocabulary_prompt(BASE, DOMAIN, None).startswith(BASE))


if __name__ == "__main__":
    unittest.main()
