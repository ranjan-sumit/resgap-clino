"""
Tests for the Research Artifact Registry and Run Manifest recorder
(Clinova Phase 4, Epic 4.1/4.2, FR-22/FR-23) added to utils/database.py.
Runs against a real, isolated Postgres schema per test class (see
tests/pg_test_utils.py), same convention as the rest of this file's
sibling cache-table tests.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from tests.pg_test_utils import new_test_schema, drop_test_schema


class _IsolatedSchemaTestCase(unittest.TestCase):
    def setUp(self):
        self.schema = new_test_schema()
        self.patcher = patch.object(db, "_SCHEMA", self.schema)
        self.patcher.start()
        db.init_db()

    def tearDown(self):
        self.patcher.stop()
        drop_test_schema(self.schema)


class RecordArtifactTests(_IsolatedSchemaTestCase):
    def test_record_then_get_round_trips(self):
        db.record_artifact(
            artifact_id="corpus:abc", artifact_type="corpus", artifact_version="corpus:v1",
            project_id="proj1", content_hash="h1", metadata={"n_papers": 3},
        )
        a = db.get_artifact("corpus:abc")
        self.assertEqual(a["artifact_type"], "corpus")
        self.assertEqual(a["metadata"], {"n_papers": 3})

    def test_default_status_is_experimental(self):
        db.record_artifact(
            artifact_id="graph:x", artifact_type="graph", artifact_version="graph:v1",
            project_id="proj1", content_hash="h2",
        )
        self.assertEqual(db.get_artifact("graph:x")["status"], "EXPERIMENTAL")

    def test_get_unknown_artifact_returns_none(self):
        self.assertIsNone(db.get_artifact("does-not-exist"))

    def test_reinserting_same_artifact_id_updates_not_duplicates(self):
        db.record_artifact(
            artifact_id="gapset:x", artifact_type="gap_set", artifact_version="gapset:v1",
            project_id="proj1", content_hash="h3", metadata={"n": 1},
        )
        db.record_artifact(
            artifact_id="gapset:x", artifact_type="gap_set", artifact_version="gapset:v2",
            project_id="proj1", content_hash="h4", metadata={"n": 2},
        )
        results = db.list_artifacts(artifact_type="gap_set")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata"], {"n": 2})

    def test_parent_artifact_lineage_reference(self):
        db.record_artifact(
            artifact_id="corpus:parent", artifact_type="corpus", artifact_version="corpus:v1",
            project_id="proj1", content_hash="h5",
        )
        db.record_artifact(
            artifact_id="extraction:child", artifact_type="paper_extraction",
            artifact_version="extraction:v1", project_id="proj1", content_hash="h6",
            parent_artifact="corpus:parent",
        )
        child = db.get_artifact("extraction:child")
        self.assertEqual(child["parent_artifact"], "corpus:parent")


class ListArtifactsTests(_IsolatedSchemaTestCase):
    def setUp(self):
        super().setUp()
        db.record_artifact(artifact_id="c1", artifact_type="corpus", artifact_version="v1",
                            project_id="proj1", content_hash="h1")
        db.record_artifact(artifact_id="c2", artifact_type="corpus", artifact_version="v2",
                            project_id="proj2", content_hash="h2")
        db.record_artifact(artifact_id="g1", artifact_type="graph", artifact_version="v1",
                            project_id="proj1", content_hash="h3", run_id="run1")

    def test_filters_by_artifact_type(self):
        results = db.list_artifacts(artifact_type="corpus")
        self.assertEqual({r["artifact_id"] for r in results}, {"c1", "c2"})

    def test_filters_by_project_id(self):
        results = db.list_artifacts(project_id="proj1")
        self.assertEqual({r["artifact_id"] for r in results}, {"c1", "g1"})

    def test_no_filters_returns_everything(self):
        self.assertEqual(len(db.list_artifacts()), 3)

    def test_combined_filters(self):
        results = db.list_artifacts(artifact_type="corpus", project_id="proj2")
        self.assertEqual([r["artifact_id"] for r in results], ["c2"])


class PromoteArtifactTests(_IsolatedSchemaTestCase):
    def setUp(self):
        super().setUp()
        db.record_artifact(artifact_id="a1", artifact_type="pipeline", artifact_version="v1",
                            project_id="proj1", content_hash="h1")

    def test_experimental_to_candidate_is_legal(self):
        result = db.promote_artifact("a1", "CANDIDATE")
        self.assertEqual(result["status"], "CANDIDATE")

    def test_candidate_to_champion_is_legal(self):
        db.promote_artifact("a1", "CANDIDATE")
        result = db.promote_artifact("a1", "CHAMPION")
        self.assertEqual(result["status"], "CHAMPION")

    def test_candidate_to_archived_is_legal(self):
        db.promote_artifact("a1", "CANDIDATE")
        result = db.promote_artifact("a1", "ARCHIVED")
        self.assertEqual(result["status"], "ARCHIVED")

    def test_champion_to_archived_is_legal(self):
        db.promote_artifact("a1", "CANDIDATE")
        db.promote_artifact("a1", "CHAMPION")
        result = db.promote_artifact("a1", "ARCHIVED")
        self.assertEqual(result["status"], "ARCHIVED")

    def test_experimental_to_champion_skips_a_step_and_is_illegal(self):
        with self.assertRaises(db.InvalidArtifactTransitionError):
            db.promote_artifact("a1", "CHAMPION")

    def test_champion_back_to_candidate_is_illegal(self):
        db.promote_artifact("a1", "CANDIDATE")
        db.promote_artifact("a1", "CHAMPION")
        with self.assertRaises(db.InvalidArtifactTransitionError):
            db.promote_artifact("a1", "CANDIDATE")

    def test_archived_is_terminal(self):
        db.promote_artifact("a1", "CANDIDATE")
        db.promote_artifact("a1", "ARCHIVED")
        with self.assertRaises(db.InvalidArtifactTransitionError):
            db.promote_artifact("a1", "CHAMPION")

    def test_unknown_status_value_raises_value_error(self):
        with self.assertRaises(ValueError):
            db.promote_artifact("a1", "NOT_A_REAL_STATUS")

    def test_unknown_artifact_id_raises_value_error(self):
        with self.assertRaises(ValueError):
            db.promote_artifact("does-not-exist", "CANDIDATE")

    def test_illegal_transition_does_not_change_stored_status(self):
        try:
            db.promote_artifact("a1", "CHAMPION")
        except db.InvalidArtifactTransitionError:
            pass
        self.assertEqual(db.get_artifact("a1")["status"], "EXPERIMENTAL")


class RunManifestTests(_IsolatedSchemaTestCase):
    def test_record_then_get_round_trips(self):
        db.record_run_manifest(
            run_id="run1", project_id="proj1", pipeline_version="1.0",
            git_commit="abc123", parser_versions={"pymupdf": "1.24", "docling": "2.x"},
            run_duration_seconds=42.5,
        )
        m = db.get_run_manifest("run1")
        self.assertEqual(m["git_commit"], "abc123")
        self.assertEqual(m["parser_versions"], {"pymupdf": "1.24", "docling": "2.x"})
        self.assertEqual(m["run_duration_seconds"], 42.5)

    def test_token_usage_is_honestly_none_when_not_provided(self):
        # No instrumentation exists yet for per-call token counting anywhere
        # in this pipeline -- must be a real NULL, never a fabricated 0/{}.
        db.record_run_manifest(run_id="run2", project_id="proj1")
        m = db.get_run_manifest("run2")
        self.assertIsNone(m["token_usage"])

    def test_get_unknown_manifest_returns_none(self):
        self.assertIsNone(db.get_run_manifest("does-not-exist"))

    def test_reinserting_same_run_id_updates_not_duplicates(self):
        db.record_run_manifest(run_id="run3", project_id="proj1", pipeline_version="1.0")
        db.record_run_manifest(run_id="run3", project_id="proj1", pipeline_version="2.0")
        m = db.get_run_manifest("run3")
        self.assertEqual(m["pipeline_version"], "2.0")

    def test_list_and_jsonb_array_fields_round_trip(self):
        db.record_run_manifest(
            run_id="run4", project_id="proj1",
            search_providers=["semantic_scholar", "arxiv"],
            output_artifacts=["gapset:v1", "proposalset:v1"],
            warnings=["low coverage on query family 2"],
        )
        m = db.get_run_manifest("run4")
        self.assertEqual(m["search_providers"], ["semantic_scholar", "arxiv"])
        self.assertEqual(m["output_artifacts"], ["gapset:v1", "proposalset:v1"])
        self.assertEqual(m["warnings"], ["low coverage on query family 2"])


if __name__ == "__main__":
    unittest.main()
