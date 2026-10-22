"""
Evidence Reader agent: passages, quote verification, number checks, part-wise reading.
A model reply is never trusted: its quotes are matched against the paper's own text.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import evidence_reader as er
from pipeline.evidence_reader import (
    _numbers_supported, _split_parts, build_passages, locate_quote, read_paper, study_type_of,
)
from utils.azure_client import Failure, ErrorInfo, Success


def seg(text, page=1, label="text"):
    return {"text": text, "page": page, "label": label}


def long_text(tag, n=40):
    return " ".join(f"{tag} sentence number {i} about cystic fibrosis airway epithelium." for i in range(n))


class BuildPassagesTests(unittest.TestCase):
    def test_sections_pages_and_ids(self):
        ps = build_passages([seg("Intro", 1, "section_header"), seg("First block.", 1), seg("Second block.", 1),
                             seg("Results", 2, "section_header"), seg("A result.", 2)])
        self.assertEqual([(p["id"], p["page"], p["section"]) for p in ps],
                         [("P1", 1, "Intro"), ("P2", 2, "Results")])
        self.assertIn("Second block.", ps[0]["text"])

    def test_page_furniture_is_excluded(self):
        ps = build_passages([seg("Body", 1), seg("Journal of X 12", 1, "page_header"), seg("42", 1, "page_number")])
        self.assertEqual(len(ps), 1)
        self.assertNotIn("Journal", ps[0]["text"])

    def test_the_reference_list_is_excluded(self):
        ps = build_passages([seg("Methods", 1, "section_header"), seg("We did x.", 1),
                             seg("References", 5, "section_header"), seg("SMITH J 2020", 5)])
        self.assertEqual(len(ps), 1)
        self.assertNotIn("SMITH", " ".join(p["text"] for p in ps))

    def test_a_new_page_starts_a_new_passage(self):
        ps = build_passages([seg("Same section", 1), seg("continues here", 2)])
        self.assertEqual([p["page"] for p in ps], [1, 2])

    def test_long_sections_are_split_into_passages(self):
        ps = build_passages([seg("Results", 1, "section_header")] + [seg("x" * 400, 1) for _ in range(6)])
        self.assertGreater(len(ps), 1)
        self.assertTrue(all(len(p["text"]) <= 1500 for p in ps))


class LocateQuoteTests(unittest.TestCase):
    PS = [{"id": "P1", "page": 1, "section": "Intro", "text": "Cystic ﬁbrosis is a lethal genetic disease."},
          {"id": "P2", "page": 4, "section": "Results", "text": "The in- creased rate was 73.2 % in children and 80.1 % in adults."}]

    def test_ligatures_and_line_break_hyphens_do_not_break_matching(self):
        p, exact = locate_quote("Cystic fibrosis is a lethal genetic disease", self.PS)
        self.assertEqual((p["id"], exact), ("P1", True))
        p, exact = locate_quote("the increased rate was 73.2% in children", self.PS)
        self.assertEqual((p["id"], exact), ("P2", True))

    def test_the_cited_passage_is_preferred_but_not_required(self):
        p, _ = locate_quote("The in- creased rate was 73.2 % in children", self.PS, hint_id="P1")
        self.assertEqual(p["id"], "P2")

    def test_a_fabricated_quote_is_not_found(self):
        self.assertIsNone(locate_quote("Gene therapy cured every patient in the trial within a week", self.PS))

    def test_a_slightly_mangled_quote_matches_fuzzily(self):
        p, exact = locate_quote("The increased rate was 73.2 % in children and 80.1 % in adults, as shown", self.PS)
        self.assertEqual(p["id"], "P2")
        self.assertFalse(exact)

    def test_too_short_a_quote_is_rejected(self):
        self.assertIsNone(locate_quote("disease", self.PS))

    def test_no_passages(self):
        self.assertIsNone(locate_quote("a quote that is long enough to count", []))


class NumberTests(unittest.TestCase):
    def test_numbers_present_in_the_source_pass(self):
        self.assertTrue(_numbers_supported("Rate was 73.2 percent in 2018", "The rate was 73,2 % in 2018."))

    def test_a_number_the_source_never_gives_fails(self):
        self.assertFalse(_numbers_supported("FEV1 improved by 10 percent", "Ivacaftor improved lung function markedly."))

    def test_single_digits_are_ignored(self):
        self.assertTrue(_numbers_supported("three arms, 3 sites", "three arms at several sites"))

    def test_no_numbers_passes(self):
        self.assertTrue(_numbers_supported("Researchers favoured modulators", "anything"))


class SplitPartsTests(unittest.TestCase):
    def test_a_short_paper_is_one_part(self):
        self.assertEqual(len(_split_parts([{"id": "P1", "text": "x" * 500}])), 1)

    def test_a_long_paper_is_split_and_loses_nothing(self):
        ps = [{"id": f"P{i}", "text": "x" * 1000} for i in range(60)]
        parts = _split_parts(ps)
        self.assertGreater(len(parts), 1)
        self.assertEqual([p["id"] for part in parts for p in part], [p["id"] for p in ps])
        self.assertTrue(all(sum(len(p["text"]) for p in part) <= er._MAX_CHARS_PER_READ * 1.3 for part in parts))

    def test_a_tiny_last_part_is_folded_into_the_previous(self):
        ps = [{"id": f"P{i}", "text": "x" * 1000} for i in range(19)]      # 19k: would be 18k + a 1k stub
        parts = _split_parts(ps)
        self.assertEqual(len(parts), 1)
        self.assertEqual(len(parts[0]), 19)


def _segments():
    blocks = [seg("Abstract", 1, "section_header"),
              seg("We surveyed 524 researchers about the future of cystic fibrosis treatment over fifteen years.", 1),
              seg("Results", 2, "section_header"),
              seg("CFTR modulators were chosen by 73.85% of respondents as the most promising therapy class.", 2),
              seg("Limitations", 3, "section_header"),
              seg("The sample may not represent all researchers because participation was voluntary.", 3)]
    return blocks + [seg(long_text("filler"), 3)]


def _reply(items, study_type="survey_or_questionnaire"):
    return json.dumps({"study_type": study_type, "study_type_reason": "r", "evidence": items})


def _item(etype, statement, quote, passage="P1", conf="high"):
    return {"type": etype, "statement": statement, "quote": quote, "passage": passage, "confidence": conf}


GOOD = [
    _item("StudyDesign", "A survey of 524 researchers.", "We surveyed 524 researchers about the future of cystic fibrosis treatment"),
    _item("Result", "73.85% chose CFTR modulators.", "CFTR modulators were chosen by 73.85% of respondents as the most promising therapy class"),
    _item("Limitation", "Voluntary participation limits representativeness.", "The sample may not represent all researchers because participation was voluntary"),
    _item("Method", "Survey over fifteen years horizon.", "about the future of cystic fibrosis treatment over fifteen years"),
    _item("Finding", "Researchers favour modulators.", "chosen by 73.85% of respondents as the most promising therapy class"),
]


class ReadPaperTests(unittest.TestCase):
    def _client(self, *replies):
        c = MagicMock()
        c.chat_json.side_effect = [Success(r) for r in replies]
        return c

    def test_verified_items_carry_page_section_and_quote(self):
        objs, diag = read_paper("p.pdf", _segments(), self._client(_reply(GOOD)))
        self.assertTrue(diag["usable"])
        result = next(o for o in objs if o.evidence_type == "Result")
        self.assertEqual((result.provenance.page, result.provenance.section), (2, "Results"))
        self.assertIn("73.85%", result.provenance.quote)

    def test_a_fabricated_quote_is_dropped(self):
        bad = _item("Result", "Everyone was cured.", "Every single patient was completely cured within one week")
        objs, diag = read_paper("p.pdf", _segments(), self._client(_reply(GOOD + [bad])))
        self.assertEqual(diag["dropped_unverified"], 1)
        self.assertFalse(any("cured" in o.text for o in objs))

    def test_a_statement_with_an_unsupported_number_is_dropped(self):
        bad = _item("Result", "88.12% chose gene therapy.", "CFTR modulators were chosen by 73.85% of respondents")
        objs, diag = read_paper("p.pdf", _segments(), self._client(_reply(GOOD + [bad])))
        self.assertEqual(diag["dropped_number_mismatch"], 1)
        self.assertFalse(any("88.12" in o.text for o in objs))

    def test_study_type_is_recorded_and_survives_as_a_tag(self):
        objs, diag = read_paper("p.pdf", _segments(), self._client(_reply(GOOD)))
        self.assertEqual(diag["study_type"], "survey_or_questionnaire")
        self.assertEqual(study_type_of(objs), "survey_or_questionnaire")

    def test_an_unknown_study_type_becomes_other(self):
        objs, diag = read_paper("p.pdf", _segments(), self._client(_reply(GOOD, study_type="made up")))
        self.assertEqual(diag["study_type"], "other")

    def test_only_one_studydesign_item_is_kept(self):
        dup = _item("StudyDesign", "Another design statement.", "We surveyed 524 researchers about the future of cystic fibrosis")
        objs, _ = read_paper("p.pdf", _segments(), self._client(_reply(GOOD + [dup])))
        self.assertEqual(sum(o.evidence_type == "StudyDesign" for o in objs), 1)

    def test_too_few_verified_items_means_not_usable(self):
        _, diag = read_paper("p.pdf", _segments(), self._client(_reply(GOOD[:2])))
        self.assertFalse(diag["usable"])

    def test_a_model_failure_is_reported_not_raised(self):
        c = MagicMock()
        c.chat_json.return_value = Failure(ErrorInfo(kind="timeout", detail="slow"))
        objs, diag = read_paper("p.pdf", _segments(), c)
        self.assertEqual(objs, [])
        self.assertFalse(diag["usable"])
        self.assertIn("model call failed", diag["error"])

    def test_an_unreadable_reply_is_reported(self):
        _, diag = read_paper("p.pdf", _segments(), self._client("I am sorry, I cannot do that"))
        self.assertEqual(diag["error"], "reply could not be read")

    def test_a_paper_with_no_text_layer_is_not_sent_to_the_model(self):
        c = MagicMock()
        objs, diag = read_paper("scan.pdf", [seg("tiny", 1)], c)
        self.assertEqual(objs, [])
        self.assertIn("no usable text", diag["error"])
        c.chat_json.assert_not_called()

    def test_a_reply_wrapped_in_a_fence_is_read(self):
        objs, diag = read_paper("p.pdf", _segments(), self._client("```json\n" + _reply(GOOD) + "\n```"))
        self.assertTrue(diag["usable"])

    def test_a_long_paper_is_read_in_parts_and_merged(self):
        segs = [seg("Section", 1, "section_header")] + [seg(long_text(f"part{i}", 18), 1 + i // 6) for i in range(30)]
        segs += _segments()
        calls = []

        def chat_json(system, user, **kw):
            calls.append(user)
            return Success(_reply(GOOD))
        c = MagicMock()
        c.chat_json.side_effect = chat_json
        objs, diag = read_paper("p.pdf", segs, c)
        self.assertGreater(diag["parts"], 1)
        self.assertEqual(len(calls), diag["parts"])
        self.assertEqual(sum(o.evidence_type == "StudyDesign" for o in objs), 1)    # one per paper, not per part

    def test_a_failed_part_is_noted_but_the_rest_are_used(self):
        segs = [seg("Section", 1, "section_header")] + [seg(long_text(f"part{i}", 18), 1) for i in range(30)] + _segments()
        n = {"i": 0}

        def chat_json(system, user, **kw):
            n["i"] += 1
            return Failure(ErrorInfo(kind="timeout", detail="x")) if n["i"] == 1 else Success(_reply(GOOD))
        c = MagicMock()
        c.chat_json.side_effect = chat_json
        objs, diag = read_paper("p.pdf", segs, c)
        self.assertIn("could not be read", diag["error"] or "")


class StudyTypeOfTests(unittest.TestCase):
    def test_reads_the_tag_from_dicts(self):
        ev = [{"evidence_type": "Result", "text": "x"},
              {"evidence_type": "StudyDesign", "text": "[study_type: in_vitro_or_lab] a chip study"}]
        self.assertEqual(study_type_of(ev), "in_vitro_or_lab")

    def test_none_without_a_tag(self):
        self.assertIsNone(study_type_of([{"evidence_type": "StudyDesign", "text": "plain"}]))
        self.assertIsNone(study_type_of([]))


if __name__ == "__main__":
    unittest.main()
