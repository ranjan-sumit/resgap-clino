"""
Tests for utils/token_meter.py (Clinova Phase 4, Epic 4.3 token
instrumentation). Pure, no DB/API dependency.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.token_meter import TokenMeter


class TokenMeterTests(unittest.TestCase):
    def test_no_records_returns_none_not_a_fabricated_zero(self):
        meter = TokenMeter()
        self.assertIsNone(meter.to_manifest_dict())

    def test_single_record_totals_correctly(self):
        meter = TokenMeter()
        meter.record(model="m1", usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, stage="Stage 2")
        result = meter.to_manifest_dict()
        self.assertEqual(result["total"], 15)
        self.assertEqual(result["by_stage"], {"Stage 2": 15})
        self.assertEqual(result["by_model"], {"m1": 15})
        self.assertEqual(result["n_calls_recorded"], 1)

    def test_multiple_records_accumulate_by_bucket(self):
        meter = TokenMeter()
        meter.record(model="m1", usage={"total_tokens": 10}, stage="Stage A")
        meter.record(model="m1", usage={"total_tokens": 20}, stage="Stage A")
        meter.record(model="m2", usage={"total_tokens": 5}, stage="Stage B")
        result = meter.to_manifest_dict()
        self.assertEqual(result["total"], 35)
        self.assertEqual(result["by_stage"], {"Stage A": 30, "Stage B": 5})
        self.assertEqual(result["by_model"], {"m1": 30, "m2": 5})

    def test_missing_usage_is_not_recorded(self):
        meter = TokenMeter()
        meter.record(model="m1", usage=None, stage="Stage A")
        meter.record(model="m1", usage={}, stage="Stage A")
        meter.record(model="m1", usage={"total_tokens": None}, stage="Stage A")
        self.assertIsNone(meter.to_manifest_dict())

    def test_agent_is_only_bucketed_when_explicitly_supplied(self):
        meter = TokenMeter()
        meter.record(model="m1", usage={"total_tokens": 10}, stage="Stage A")  # no agent
        meter.record(model="m1", usage={"total_tokens": 5}, agent="Gap Generator")
        result = meter.to_manifest_dict()
        self.assertEqual(result["by_agent"], {"Gap Generator": 5})

    def test_stage_none_is_excluded_from_by_stage(self):
        meter = TokenMeter()
        meter.record(model="m1", usage={"total_tokens": 10})
        result = meter.to_manifest_dict()
        self.assertEqual(result["by_stage"], {})
        self.assertEqual(result["total"], 10)


if __name__ == "__main__":
    unittest.main()
