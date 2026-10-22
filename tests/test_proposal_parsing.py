"""
Proposals must survive the reply shapes models really return. A real Gemini run
spent 4.5k tokens in Stage 6 and saved 0 proposals: the reply was unreadable to a
parser that only accepted a bare JSON list, and the trace still showed a tick.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.azure_client import Success
from pipeline.proposal_generator import _parse_proposals, generate_proposals

P1 = {"title": "Proposal one", "problem_statement": "p1"}
P2 = {"title": "Proposal two", "problem_statement": "p2"}


class ParseProposalsTests(unittest.TestCase):
    def test_bare_list(self):
        self.assertEqual(_parse_proposals(json.dumps([P1, P2])), [P1, P2])

    def test_json_fence(self):
        self.assertEqual(_parse_proposals("```json\n" + json.dumps([P1]) + "\n```"), [P1])

    def test_plain_fence_with_text_around_the_list(self):
        self.assertEqual(_parse_proposals("Here you go:\n" + json.dumps([P1, P2]) + "\nHope it helps"), [P1, P2])

    def test_object_wrapping_the_list(self):
        self.assertEqual(_parse_proposals(json.dumps({"proposals": [P1, P2]})), [P1, P2])

    def test_object_wrapping_the_list_under_another_key(self):
        self.assertEqual(_parse_proposals(json.dumps({"research_proposals": [P1]})), [P1])
        self.assertEqual(_parse_proposals(json.dumps({"anything": [P1, P2]})), [P1, P2])

    def test_a_single_proposal_returned_alone(self):
        self.assertEqual(_parse_proposals(json.dumps(P1)), [P1])

    def test_truncated_list_keeps_the_complete_objects(self):
        cut = json.dumps([P1, P2])[:-25]            # chopped inside the second object
        out = _parse_proposals(cut)
        self.assertEqual(out, [P1])

    def test_non_dict_items_are_dropped(self):
        self.assertEqual(_parse_proposals(json.dumps([P1, "noise", 3, None])), [P1])

    def test_garbage_and_empty_give_an_empty_list(self):
        for raw in ("", "   ", "no json at all", "{", "[", None):
            self.assertEqual(_parse_proposals(raw), [], repr(raw))

    def test_an_explicit_empty_list_is_empty(self):
        self.assertEqual(_parse_proposals("[]"), [])


class GenerateProposalsRetryTests(unittest.TestCase):
    GAPS = [{"title": "G", "description": "d", "validation_status": "open", "gap_id": "abc123abc123"}]
    WIKI = {"pages": [{"title": "T", "methods": [], "datasets": [], "contributions": []}]}

    def _run(self, replies):
        client = MagicMock()
        client.chat_json.side_effect = [Success(r) for r in replies]
        return generate_proposals(self.GAPS, self.WIKI, {"domain": "x"}, client), client

    def test_an_unreadable_reply_is_retried_once_and_recovers(self):
        out, client = self._run(["I could not produce JSON, sorry", json.dumps([P1])])
        self.assertEqual([p["title"] for p in out], ["Proposal one"])
        self.assertEqual(client.chat_json.call_count, 2)

    def test_a_good_first_reply_is_not_retried(self):
        out, client = self._run([json.dumps([P1, P2])])
        self.assertEqual(len(out), 2)
        self.assertEqual(client.chat_json.call_count, 1)

    def test_gives_up_after_two_attempts(self):
        out, client = self._run(["nope", "still nope"])
        self.assertEqual(out, [])
        self.assertEqual(client.chat_json.call_count, 2)

    def test_a_truly_empty_reply_is_not_retried(self):
        out, client = self._run([""])
        self.assertEqual(out, [])
        self.assertEqual(client.chat_json.call_count, 1)


if __name__ == "__main__":
    unittest.main()
