"""
Regression tests for pipeline/llm_council.py fixes:
  - a failed agent call no longer feeds "[model failed: ...]" error text into
    the chair's debate prompt as if it were an opinion; failures are carried
    as explicitly-marked context the chair is told to ignore as opinion.
  - the trailing-comma JSON repair only runs after strict parsing and
    brace-extraction have failed, so string values containing ",}" survive
    parsing intact.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.llm_council import (
    _robust_parse,
    run_council,
    MODEL_SELECTION_AGENTS,
    MODEL_COUNCIL_FINAL_PROMPT,
)

_AGENT_ERROR = "rate limit exceeded"


class RobustParseTests(unittest.TestCase):
    def test_string_value_containing_comma_brace_survives_intact(self):
        raw = '{"note": "group A,} then B", "x": 1}'
        result = _robust_parse(raw, dict)
        self.assertEqual(result["note"], "group A,} then B")
        self.assertEqual(result["x"], 1)

    def test_trailing_comma_repair_still_works_as_last_resort(self):
        # Malformed LLM output with a real trailing comma must still parse
        # once strict attempts have failed.
        result = _robust_parse('{"a": 1,}', dict)
        self.assertEqual(result, {"a": 1})


def _fake_call_factory(calls):
    def _fake(api_key, model_key, system, user):
        calls.append({"model_key": model_key, "system": system, "user": user})
        if model_key == "llama_3b":
            return {"_failed": True, "error": _AGENT_ERROR,
                    "model": "meta/llama-3.2-3b-instruct"}
        if model_key == "gpt_120b":
            return json.dumps({
                "consensus": "agreed", "key_points": ["p1"],
                "disagreements": [], "confidence": "high", "caveats": [],
            })
        return "I recommend the monte carlo model because the data supports it."
    return _fake


class FailedAgentTests(unittest.TestCase):
    def test_failed_agent_contributes_no_opinion_text_to_chair(self):
        calls = []
        with patch("pipeline.llm_council._call_model", side_effect=_fake_call_factory(calls)):
            result = run_council(
                MODEL_SELECTION_AGENTS, "ctx", MODEL_COUNCIL_FINAL_PROMPT, "key"
            )

        # The failed agent is flagged, with no opinion text.
        failed = [a for a in result["agents"] if a.get("failed")]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["agent"], "Dr. Epidemiologist")
        self.assertEqual(failed[0]["response"], "")

        chair_calls = [c for c in calls if c["model_key"] == "gpt_120b"]
        self.assertEqual(len(chair_calls), 2)  # consensus + final
        for call in chair_calls:
            # The failure may be reported in the explicit, marked failures
            # section -- but never as debate/opinion text.
            debate_part = call["user"].split(
                "The following council member(s) could not be reached"
            )[0]
            self.assertNotIn(_AGENT_ERROR, debate_part)
            self.assertNotIn("failed:", debate_part)
            self.assertIn("no opinion", call["user"].lower())
            self.assertIn("Dr. Epidemiologist", call["user"])
        # The successful agent's opinion still reaches the chair.
        self.assertIn("monte carlo", chair_calls[0]["user"])

    def test_transcript_marks_failure_without_error_text_as_opinion(self):
        calls = []
        with patch("pipeline.llm_council._call_model", side_effect=_fake_call_factory(calls)):
            result = run_council(
                MODEL_SELECTION_AGENTS, "ctx", MODEL_COUNCIL_FINAL_PROMPT, "key"
            )
        self.assertIn("CALL FAILED", result["transcript"])
        self.assertNotIn(_AGENT_ERROR, result["transcript"])


if __name__ == "__main__":
    unittest.main()
