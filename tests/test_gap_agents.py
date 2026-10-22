"""
Agentic gap detection: finders cite evidence handles, grounding is enforced in code, a critic
scores/merges/drops, and the main list stays short and ranked.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import gap_agents as ga
from pipeline.gap_agents import _dedupe, _ground, _parse_list, build_brief, find_gaps
from utils.azure_client import ErrorInfo, Failure, Success


def ev(eid, etype, text, page=2, section="Results", quote=None):
    return {"evidence_id": eid * 8 if len(eid) == 1 else eid, "evidence_type": etype, "text": text,
            "provenance": {"page": page, "section": section, "quote": quote or text}}


EVIDENCE = {
    "a.pdf": [ev("a", "Limitation", "Static culture lacks flow", quote="static culture lacks any shear flow"),
              ev("b", "Result", "IL-8 rose in CF chips", quote="IL-8 was higher in CF chips than healthy chips"),
              ev("c", "StudyDesign", "[study_type: in_vitro_or_lab] an organ chip study", quote="we built an airway chip")],
    "b.pdf": [ev("d", "FutureWork", "Test gene therapy delivery", quote="future work will test mRNA delivery"),
              ev("e", "Method", "Survey of 524 researchers", quote="a global survey of 524 researchers")],
}
PROFILES = {"a.pdf": {"study_type": "in_vitro_or_lab"}, "b.pdf": {"study_type": "survey_or_questionnaire"}}
WIKI = {"pages": [{"source_file": "a.pdf", "title": "Airway chip paper"}, {"source_file": "b.pdf", "title": "Survey paper"}],
        "cross_links": {"shared_concepts": [{"concept": "CF"}]}}
GRAPH = {"communities": [{"theme": "CF therapy", "summary": "s"}]}
CONTEXT = {"domain": "Healthcare AI", "interest": "General research", "gap_type": "Any"}
H = {k: "E" + v[0]["evidence_id"][:8] for k, v in {"a": EVIDENCE["a.pdf"], "d": EVIDENCE["b.pdf"]}.items()}


def handle(paper, idx):
    return "E" + EVIDENCE[paper][idx]["evidence_id"][:8]


def gap(title, refs, desc="A specific missing piece and why it matters in practice.", **kw):
    return {"title": title, "description": desc, "gap_type": "methodology", "confidence": "high",
            "evidence_refs": refs, "supporting_papers": [], "missing_connection": "x", "why_important": "y", **kw}


class FakeClient:
    """Answers by the agent named in the system prompt."""
    def __init__(self, lens_replies=None, critic=None, fail=()):
        self.lens_replies, self.critic, self.fail = lens_replies or {}, critic, set(fail)
        self.calls, self.stage = [], None

    def set_stage(self, s):
        self.stage = s

    def chat_json(self, system, user, **kw):
        if "Methodology Critic" in system:
            self.calls.append("critic")
            if "critic" in self.fail:
                return Failure(ErrorInfo(kind="timeout", detail="x"))
            cands = json.loads(user.split("Candidate gaps:\n", 1)[1])
            return Success(json.dumps({"reviews": self.critic(cands) if callable(self.critic) else self.critic or []}))
        for lens in ("Limitation Miner", "Cross-Paper Synthesizer", "Methodology Auditor"):
            if lens in system:
                key = lens.lower().replace("-", "_").replace(" ", "_")
                self.calls.append(key)
                if key in self.fail:
                    return Failure(ErrorInfo(kind="timeout", detail="x"))
                rep = self.lens_replies.get(key, [])
                rep = rep(user) if callable(rep) else rep
                return Success(json.dumps({"gaps": rep}))
        raise AssertionError("unknown agent")


class BriefTests(unittest.TestCase):
    def test_handles_titles_study_types_and_quotes_are_shown(self):
        titles = {"a.pdf": "Airway chip paper", "b.pdf": "Survey paper"}
        text, by_handle = build_brief(EVIDENCE, PROFILES, titles)
        self.assertIn("Airway chip paper", text)
        self.assertIn("study type: in_vitro_or_lab", text)
        self.assertIn(handle("a.pdf", 0), by_handle)
        self.assertIn('quote: "static culture lacks any shear flow"', text)
        self.assertNotIn("[study_type:", text)                         # the tag is bookkeeping, not content


class GroundingTests(unittest.TestCase):
    def setUp(self):
        self.titles = {"a.pdf": "Airway chip paper", "b.pdf": "Survey paper"}
        _, self.by_handle = build_brief(EVIDENCE, PROFILES, self.titles)

    def test_valid_handles_rebuild_evidence_from_real_quotes(self):
        g = gap("t", [handle("a.pdf", 0)])
        self.assertTrue(_ground(g, self.by_handle, self.titles, "limitation_miner", None))
        self.assertEqual(g["motivating_evidence_ids"], [EVIDENCE["a.pdf"][0]["evidence_id"]])
        self.assertIn("static culture lacks any shear flow", g["evidence"][0])
        self.assertEqual(g["supporting_papers"], ["Airway chip paper"])
        self.assertEqual(g["evidence_basis"], "positive_evidence")

    def test_invented_handles_are_discarded(self):
        g = gap("t", ["Edeadbeef", handle("a.pdf", 1)])
        self.assertTrue(_ground(g, self.by_handle, self.titles, "limitation_miner", None))
        self.assertEqual(len(g["motivating_evidence_ids"]), 1)

    def test_a_gap_with_no_valid_handle_is_dropped_for_normal_lenses(self):
        g = gap("t", ["Edeadbeef"], supporting_papers=["Airway chip paper"])
        self.assertFalse(_ground(g, self.by_handle, self.titles, "cross_paper_synthesizer", None))

    def test_the_auditor_may_name_something_a_paper_omits(self):
        g = gap("No donor replication", [])
        self.assertTrue(_ground(g, self.by_handle, self.titles, "methodology_auditor", "a.pdf"))
        self.assertEqual(g["evidence_basis"], "absence_of_evidence")
        self.assertIn("Airway chip paper", g["supporting_papers"])

    def test_models_own_supporting_papers_are_not_trusted_when_handles_exist(self):
        g = gap("t", [handle("a.pdf", 0)], supporting_papers=["A paper that does not exist"])
        _ground(g, self.by_handle, self.titles, "limitation_miner", None)
        self.assertEqual(g["supporting_papers"], ["Airway chip paper"])

    def test_duplicate_handles_count_once(self):
        g = gap("t", [handle("a.pdf", 0)] * 3)
        _ground(g, self.by_handle, self.titles, "limitation_miner", None)
        self.assertEqual(len(g["motivating_evidence_ids"]), 1)


class RequireQuoteTests(unittest.TestCase):
    def setUp(self):
        self.titles = {"a.pdf": "Airway chip paper"}
        unquoted = {"evidence_id": "u" * 8, "evidence_type": "StudyDesign", "text": "[study_type: x] a chip",
                    "provenance": {"page": None, "section": None, "quote": None}}
        quoted = ev("q", "Limitation", "No flow", quote="static culture lacks any shear flow")
        _, self.by_handle = build_brief({"a.pdf": [unquoted, quoted]}, {}, self.titles)

    def test_an_unquoted_item_is_context_not_grounding_when_quoted_evidence_exists(self):
        g = gap("t", ["Euuuuuuuu", "Eqqqqqqqq"])
        self.assertTrue(_ground(g, self.by_handle, self.titles, "limitation_miner", None, require_quote=True))
        self.assertEqual(g["motivating_evidence_ids"], ["q" * 8])
        self.assertNotIn("location unknown", " ".join(g["evidence"]))

    def test_citing_only_an_unquoted_item_drops_the_gap(self):
        g = gap("t", ["Euuuuuuuu"])
        self.assertFalse(_ground(g, self.by_handle, self.titles, "limitation_miner", None, require_quote=True))

    def test_without_any_quotes_in_the_corpus_unquoted_items_still_ground(self):
        g = gap("t", ["Euuuuuuuu"])
        self.assertTrue(_ground(g, self.by_handle, self.titles, "limitation_miner", None, require_quote=False))


class ParseTests(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(_parse_list('{"gaps": [{"a": 1}]}', "gaps"), [{"a": 1}])
        self.assertEqual(_parse_list('```json\n[{"a": 1}]\n```', "gaps"), [{"a": 1}])
        self.assertEqual(_parse_list('Sure! {"gaps": [{"a": 1}]} done', "gaps"), [{"a": 1}])
        self.assertEqual(_parse_list('{"gaps": []}', "gaps"), [])
        self.assertIsNone(_parse_list("not json", "gaps"))
        self.assertIsNone(_parse_list("", "gaps"))


class DedupeTests(unittest.TestCase):
    def test_near_identical_titles_keep_the_better_grounded(self):
        a = {"title": "Predictive modelling of inhaled drug delivery", "motivating_evidence_ids": ["1"], "lens": "limitation_miner"}
        b = {"title": "Predictive modeling of inhaled drug delivery", "motivating_evidence_ids": ["1", "2"], "lens": "cross_paper_synthesizer"}
        c = {"title": "Donor diversity in organ chips", "motivating_evidence_ids": [], "lens": "methodology_auditor"}
        out = _dedupe([a, b, c])
        self.assertEqual(len(out), 2)
        self.assertIn(b, out)


class FindGapsTests(unittest.TestCase):
    def _lens(self, *gaps):
        return list(gaps)

    def _replies(self):
        return {
            "limitation_miner": self._lens(gap("Add flow to static culture models", [handle("a.pdf", 0)])),
            "cross_paper_synthesizer": self._lens(
                gap("Test mRNA delivery in infected CF chips", [handle("b.pdf", 0), handle("a.pdf", 1)])),
            "methodology_auditor": lambda user: self._lens(
                gap("Single cell source in the chip study", [])) if "Airway chip paper" in user else [],
        }

    def _run(self, client, **kw):
        return find_gaps(WIKI, GRAPH, CONTEXT, client, EVIDENCE, PROFILES, **kw)

    def test_happy_path_keeps_ranked_grounded_gaps(self):
        def critic(cands):
            return [{"id": c["id"], "novelty": 5 if "mRNA" in c["title"] else 3, "importance": 4, "feasibility": 4,
                     "verdict": "keep", "critique": "ok"} for c in cands]
        out = self._run(FakeClient(self._replies(), critic))
        titles = [g["title"] for g in out["gaps"]]
        self.assertEqual(len(titles), 3)
        self.assertEqual(titles[0], "Test mRNA delivery in infected CF chips")           # highest scores first
        self.assertEqual([g["rank"] for g in out["gaps"]], [1, 2, 3])
        for g in out["gaps"]:
            self.assertTrue(g["gap_id"])
            self.assertEqual(g["validation_status"], "pending")
            self.assertTrue(g["source"].startswith("agent:"))
            self.assertIn("scores", g)
            self.assertNotIn("_cid", g)
            self.assertNotIn("evidence_refs", g)

    def test_a_dropped_verdict_moves_the_gap_to_rejected_with_a_reason(self):
        def critic(cands):
            return [{"id": c["id"], "novelty": 1, "importance": 1, "feasibility": 1,
                     "verdict": "drop" if "static" in c["title"].lower() else "keep", "reason": "generic"} for c in cands]
        out = self._run(FakeClient(self._replies(), critic))
        self.assertFalse(any("static" in g["title"].lower() for g in out["gaps"]))
        rej = [g for g in out["rejected"] if "static" in g["title"].lower()]
        self.assertEqual(rej[0]["rejected_reason"], "generic")

    def test_a_merge_verdict_folds_evidence_into_the_target(self):
        def critic(cands):
            by = {c["title"]: c["id"] for c in cands}
            out = []
            for c in cands:
                if c["title"].startswith("Add flow"):
                    out.append({"id": c["id"], "verdict": "merge", "merge_into": by["Test mRNA delivery in infected CF chips"]})
                else:
                    out.append({"id": c["id"], "novelty": 4, "importance": 4, "feasibility": 4, "verdict": "keep"})
            return out
        out = self._run(FakeClient(self._replies(), critic))
        target = next(g for g in out["gaps"] if g["title"].startswith("Test mRNA"))
        self.assertIn(EVIDENCE["a.pdf"][0]["evidence_id"], target["motivating_evidence_ids"])
        self.assertTrue(any(r["rejected_reason"].startswith("merged into") for r in out["rejected"]))

    def test_max_gaps_caps_the_main_list(self):
        def critic(cands):
            return [{"id": c["id"], "novelty": 4, "importance": 4, "feasibility": 4, "verdict": "keep"} for c in cands]
        out = self._run(FakeClient(self._replies(), critic), max_gaps=2)
        self.assertEqual(len(out["gaps"]), 2)
        self.assertTrue(any("ranked below" in r["rejected_reason"] for r in out["rejected"]))

    def test_the_critic_failing_still_returns_gaps_ranked_by_grounding(self):
        out = self._run(FakeClient(self._replies(), fail={"critic"}))
        self.assertEqual(len(out["gaps"]), 3)
        self.assertIn("model call failed", out["diagnostics"]["critic_error"])
        self.assertEqual(out["gaps"][0]["title"], "Test mRNA delivery in infected CF chips")   # 2 quotes beat 1 or 0

    def test_a_failed_finder_is_recorded_and_the_others_carry_on(self):
        out = self._run(FakeClient(self._replies(), fail={"limitation_miner"}))
        errs = [d for d in out["diagnostics"]["finders"] if d["error"]]
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["lens"], "limitation_miner")
        self.assertGreaterEqual(len(out["gaps"]), 2)

    def test_ungrounded_gaps_never_reach_the_critic(self):
        replies = {"limitation_miner": [gap("Ungrounded idea", ["Enope"])], "cross_paper_synthesizer": [],
                   "methodology_auditor": []}
        client = FakeClient(replies, [])
        out = self._run(client)
        self.assertEqual(out["gaps"], [])
        self.assertNotIn("critic", client.calls)

    def test_one_auditor_call_per_paper_with_its_study_type(self):
        seen = []
        client = FakeClient({"methodology_auditor": lambda user: seen.append(user) or []}, [])
        self._run(client)
        self.assertEqual(client.calls.count("methodology_auditor"), 2)

    def test_the_auditor_gets_the_checklist_for_its_papers_study_type(self):
        systems = []

        class Spy(FakeClient):
            def chat_json(self, system, user, **kw):
                systems.append(system)
                return super().chat_json(system, user, **kw)
        self._run(Spy({}, []))
        audit = [s for s in systems if "Methodology Auditor" in s]
        self.assertTrue(any("in_vitro_or_lab" in s and "biological replicates" in s for s in audit))
        self.assertTrue(any("survey_or_questionnaire" in s and "response bias" in s for s in audit))
        self.assertFalse(any("events-per-variable" in s for s in audit))   # not an ML paper: no model checklist

    def test_no_evidence_gives_no_gaps_and_no_crash(self):
        out = find_gaps(WIKI, GRAPH, CONTEXT, FakeClient({}, []), {}, {})
        self.assertEqual(out["gaps"], [])


if __name__ == "__main__":
    unittest.main()
