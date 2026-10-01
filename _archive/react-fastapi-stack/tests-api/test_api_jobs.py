"""
Tests for the run-creation API (Clinova Phase 5, Epic 5.6).

Deliberately exercises only the pre-flight paths -- unknown provider, missing
API key, too few PDFs, unknown job id. Actually starting a run would make
real, paid LLM calls and take minutes, which has no place in a test suite;
the orchestration it would invoke is already covered by
test_run_pipeline_extraction.py's contract tests.
"""
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.jobs_service import TERMINAL_STATES, RunJob, _JOBS
from pipeline.run_pipeline import MAX_PAPERS, MIN_PAPERS

client = TestClient(app)

_FAKE_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def _files(n: int):
    return [("files", (f"p{i}.pdf", io.BytesIO(_FAKE_PDF), "application/pdf")) for i in range(n)]


class NewRunConfigTests(unittest.TestCase):
    def test_reports_real_providers_and_whether_each_key_is_present(self):
        r = client.get("/api/runs/new/config")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreaterEqual(len(body["providers"]), 1)
        for p in body["providers"]:
            self.assertTrue(p["key"] and p["label"] and p["default_model"])
            self.assertIsInstance(p["models"], list)
            # Honest, not optimistic: the UI disables providers without a key
            # rather than letting a run start and die minutes later.
            self.assertIsInstance(p["api_key_present"], bool)
        self.assertEqual(body["min_papers"], MIN_PAPERS)
        self.assertEqual(body["max_papers"], MAX_PAPERS)

    def test_states_plainly_that_jobs_are_in_process(self):
        body = client.get("/api/runs/new/config").json()
        self.assertTrue(body["jobs_are_in_process"])
        self.assertIn("restart", body["jobs_note"].lower())


class CreateRunValidationTests(unittest.TestCase):
    def test_too_few_papers_is_400_with_a_real_reason(self):
        r = client.post("/api/runs/new", files=_files(1))
        self.assertEqual(r.status_code, 400)
        self.assertIn("at least", r.json()["detail"].lower())

    def test_unknown_provider_is_404(self):
        r = client.post("/api/runs/new", files=_files(MIN_PAPERS),
                        data={"provider_key": "no-such-provider"})
        self.assertEqual(r.status_code, 404)

    def test_provider_without_a_configured_key_is_400_naming_the_env_var(self):
        # 'openai' has no key configured in this environment; the error must
        # name the exact variable to set rather than failing generically.
        r = client.post("/api/runs/new", files=_files(MIN_PAPERS),
                        data={"provider_key": "openai"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("OPENAI_API_KEY", r.json()["detail"])

    def test_pipeline_input_error_is_400_not_the_valueerror_404(self):
        """PipelineInputError subclasses ValueError, and this app already has
        a ValueError->404 handler. Starlette resolves handlers by walking the
        exception MRO, so the specific 400 must win -- a bad upload is not a
        'not found'."""
        r = client.post("/api/runs/new", files=_files(1))
        self.assertEqual(r.status_code, 400)


class JobStatusTests(unittest.TestCase):
    def test_unknown_job_is_404_and_explains_that_progress_is_ephemeral(self):
        r = client.get("/api/jobs/does-not-exist")
        self.assertEqual(r.status_code, 404)
        self.assertIn("restart", r.json()["detail"].lower())

    def test_job_listing_and_status_render_a_registered_job(self):
        job = RunJob(job_id="pytest_fake_job", name="fake", project_id="Healthcare AI")
        job.trace.append({"stage": "Stage 1", "inputs": "2 PDFs", "outputs": "ok"})
        _JOBS[job.job_id] = job
        try:
            r = client.get(f"/api/jobs/{job.job_id}")
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(body["job_id"], job.job_id)
            self.assertEqual(body["state"], "queued")
            self.assertEqual(body["trace"][0]["stage"], "Stage 1")

            listing = client.get("/api/jobs").json()
            self.assertIn(job.job_id, [j["job_id"] for j in listing])
        finally:
            _JOBS.pop(job.job_id, None)

    def test_terminal_states_are_the_two_the_ui_polls_on(self):
        self.assertEqual(set(TERMINAL_STATES), {"succeeded", "failed"})


if __name__ == "__main__":
    unittest.main()
