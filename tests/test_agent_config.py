"""
Tests for pipeline/agent_config.py (Clinova Phase 3, Epic 3.6 -- the
budgets/timeouts half of PRD FR-19).
"""
import unittest

from pipeline.agent_config import (
    AgentConfig, EVIDENCE_EXTRACTOR, GAP_GENERATOR, GAP_CHALLENGER,
    check_spawn_depth, SpawnDepthExceededError,
)


class AgentConfigShapeTests(unittest.TestCase):
    def test_is_frozen(self):
        with self.assertRaises(Exception):
            EVIDENCE_EXTRACTOR.max_tokens = 999

    def test_schema_fields_are_honestly_none(self):
        # See module docstring: not faked, genuinely unenforced today.
        for cfg in (EVIDENCE_EXTRACTOR, GAP_GENERATOR, GAP_CHALLENGER):
            self.assertIsNone(cfg.input_schema)
            self.assertIsNone(cfg.output_schema)

    def test_all_three_real_roles_have_positive_budgets(self):
        for cfg in (EVIDENCE_EXTRACTOR, GAP_GENERATOR, GAP_CHALLENGER):
            self.assertGreater(cfg.max_tokens, 0)
            self.assertGreater(cfg.timeout_seconds, 0)
            self.assertGreaterEqual(cfg.max_retries, 0)

    def test_roles_are_distinct(self):
        roles = {EVIDENCE_EXTRACTOR.role, GAP_GENERATOR.role, GAP_CHALLENGER.role}
        self.assertEqual(len(roles), 3)

    def test_default_construction_matches_documented_defaults(self):
        cfg = AgentConfig(role="Test Role", max_tokens=100, timeout_seconds=30)
        self.assertEqual(cfg.max_retries, 2)
        self.assertEqual(cfg.max_requests, 1)
        self.assertEqual(cfg.max_tool_calls, 0)
        self.assertEqual(cfg.max_search_calls, 0)
        self.assertEqual(cfg.allowed_tools, ())
        self.assertEqual(cfg.prompt_version, "1")


class SpawnDepthTests(unittest.TestCase):
    def test_depth_at_limit_is_allowed(self):
        check_spawn_depth(1)  # should not raise

    def test_depth_below_limit_is_allowed(self):
        check_spawn_depth(0)  # should not raise

    def test_depth_exceeding_limit_raises(self):
        with self.assertRaises(SpawnDepthExceededError):
            check_spawn_depth(2)

    def test_exception_message_names_the_depth(self):
        try:
            check_spawn_depth(5)
            self.fail("expected SpawnDepthExceededError")
        except SpawnDepthExceededError as e:
            self.assertEqual(e.depth, 5)
            self.assertIn("5", str(e))


if __name__ == "__main__":
    unittest.main()
