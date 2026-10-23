"""
Figure analysis must never freeze a run. Measured 2026-10-20: NVIDIA's vision
model took 764 s (then failed) for ONE page, so a 15-page run sat at "Stage 1"
for hours.
"""
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import figures as figure_reader
from utils.azure_client import AzureOpenAIClient, ErrorInfo, Failure, Success
from utils.model_router import ModelConfig, ModelRouter, ModelSpec


class HardTimeoutTests(unittest.TestCase):
    @patch("utils.azure_client.OpenAI")
    def _client(self, _mock):
        return AzureOpenAIClient(api_key="k", base_url="https://example.test/v1", model="m", vision_model="vlm")

    def test_a_hung_call_returns_a_timeout_failure_at_the_limit(self):
        c = self._client()
        c.VISION_HARD_TIMEOUT = 0.3
        with patch.object(c, "_vision_call", side_effect=lambda *a, **k: time.sleep(5)):
            t = time.monotonic()
            result = c.vision("s", "u", b"img")
        self.assertLess(time.monotonic() - t, 2)
        self.assertIsInstance(result, Failure)
        self.assertEqual(result.error.kind, "timeout")

    def test_a_fast_call_returns_its_result_unchanged(self):
        c = self._client()
        with patch.object(c, "_vision_call", return_value=Success("a chart")):
            self.assertEqual(c.vision("s", "u", b"img"), Success("a chart"))

    def test_an_exception_inside_the_call_becomes_a_failure(self):
        c = self._client()
        with patch.object(c, "_vision_call", side_effect=RuntimeError("boom")):
            result = c.vision("s", "u", b"img")
        self.assertIsInstance(result, Failure)
        self.assertIn("boom", result.error.detail)

    @patch("time.sleep", return_value=None)
    @patch("utils.azure_client._collect_stream", side_effect=TimeoutError("timed out"))
    @patch("utils.azure_client.OpenAI")
    def test_a_timeout_is_not_retried(self, mock_openai, _collect, _sleep):
        c = AzureOpenAIClient(api_key="k", base_url="https://example.test/v1", model="m", vision_model="vlm")
        result = c.vision("s", "u", b"img")
        self.assertEqual(result.error.kind, "timeout")
        self.assertEqual(mock_openai.return_value.chat.completions.create.call_count, 1)


def _figure_pdf(n_pages: int) -> str:
    import tempfile
    import fitz
    doc = fitz.open()
    for i in range(n_pages):
        doc.new_page().insert_text((50, 100), f"Figure {i + 1}. A chart with values 12 and 40.", fontsize=11)
    path = tempfile.mktemp(suffix=".pdf")
    doc.save(path)
    doc.close()
    return path


def _figs(n):
    return [{"label": f"Figure {i + 1}", "page": i + 1, "caption": f"Figure {i + 1}. A chart with values 12 and 40.",
             "bbox": (0, 0, 100, 100), "kind": "raster"} for i in range(n)]


class FigureLoopTests(unittest.TestCase):
    def _run(self, results, **kw):
        client = MagicMock()
        client.vision.side_effect = results
        path = _figure_pdf(len(results))
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))
        with patch.object(figure_reader, "render_figure", return_value=b"img"):
            return figure_reader.analyze_figures(path, client, _figs(len(results)), **kw), client

    def test_stops_after_two_failures_in_a_row(self):
        fail = Failure(ErrorInfo(kind="timeout", detail="slow"))
        out, client = self._run([fail, fail, fail, fail, fail])
        self.assertEqual(client.vision.call_count, 2)
        self.assertEqual(len(out), 5)                                  # every figure still accounted for
        self.assertTrue(all(d["description"] == "" and d["error"] for d in out))   # a failure is never a description
        self.assertIn("skipped", out[-1]["error"])

    def test_a_success_resets_the_failure_count(self):
        fail = Failure(ErrorInfo(kind="timeout", detail="slow"))
        out, client = self._run([fail, Success("fig"), fail, Success("fig2")])
        self.assertEqual(client.vision.call_count, 4)
        self.assertEqual([d["description"] for d in out if d["description"]], ["fig", "fig2"])

    def test_stops_once_the_time_budget_is_used(self):
        client = MagicMock()
        client.vision.return_value = Success("fig")
        path = _figure_pdf(4)
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))
        clock = iter([0, 1, 2, 999, 999, 999])
        with patch.object(figure_reader, "render_figure", return_value=b"img"), \
             patch("time.monotonic", side_effect=lambda: next(clock)):
            out = figure_reader.analyze_figures(path, client, _figs(4))
        self.assertLess(client.vision.call_count, 4)
        self.assertIn("skipped", out[-1]["error"])

    def test_progress_is_reported_per_figure(self):
        seen = []
        self._run([Success("a"), Success("b")], on_progress=seen.append)
        self.assertEqual(seen, ["Figure 1 (1/2)", "Figure 2 (2/2)"])


class RouterVisionFallThroughTests(unittest.TestCase):
    def _router(self, keys, vision_by_provider):
        from utils.model_router import (ROLE_ANALYSIS, ROLE_COUNCIL_A, ROLE_COUNCIL_B, ROLE_COUNCIL_C,
                                        ROLE_COUNCIL_CHAIR, ROLE_EXTRACTION, ROLE_WIKI)
        nv = ModelSpec("nvidia", "openai/gpt-oss-20b")        # everything on NVIDIA, as in the stuck run
        cfg = ModelConfig({r: nv for r in (ROLE_EXTRACTION, ROLE_WIKI, ROLE_ANALYSIS, ROLE_COUNCIL_A,
                                           ROLE_COUNCIL_B, ROLE_COUNCIL_C, ROLE_COUNCIL_CHAIR)}, nv)
        clients = {}

        def factory(spec, key, meter):
            c = MagicMock()
            c.vision_model = "vlm"
            c.vision.return_value = vision_by_provider[spec.provider]
            clients[spec.provider] = c
            return c
        return ModelRouter(cfg, keys, factory=factory), clients

    def test_moves_on_to_gemini_when_the_selected_provider_fails(self):
        router, clients = self._router(
            {"nvidia": "k", "gemini": "g"},
            {"nvidia": Failure(ErrorInfo(kind="timeout", detail="hung")), "gemini": Success("described")})
        result = router.vision("s", "u", b"img")
        self.assertEqual(result, Success("described"))
        clients["nvidia"].vision.assert_called_once()

    def test_returns_the_failure_when_every_provider_fails(self):
        router, _ = self._router(
            {"nvidia": "k", "gemini": "g"},
            {"nvidia": Failure(ErrorInfo(kind="timeout", detail="hung")),
             "gemini": Failure(ErrorInfo(kind="rate_limit", detail="429"))})
        self.assertIsInstance(router.vision("s", "u", b"img"), Failure)

    def test_a_provider_that_timed_out_is_skipped_on_later_pages(self):
        router, clients = self._router(
            {"nvidia": "k", "gemini": "g"},
            {"nvidia": Failure(ErrorInfo(kind="timeout", detail="hung")), "gemini": Success("described")})
        router.vision("s", "u", b"page1")
        router.vision("s", "u", b"page2")
        router.vision("s", "u", b"page3")
        self.assertEqual(clients["nvidia"].vision.call_count, 1)      # only the first page paid the wait
        self.assertEqual(clients["gemini"].vision.call_count, 3)

    def test_a_rate_limited_provider_is_not_written_off(self):
        router, clients = self._router(
            {"nvidia": "k", "gemini": "g"},
            {"nvidia": Failure(ErrorInfo(kind="rate_limit", detail="429")), "gemini": Success("described")})
        router.vision("s", "u", b"page1")
        router.vision("s", "u", b"page2")
        self.assertEqual(clients["nvidia"].vision.call_count, 2)

    def test_each_provider_is_tried_once(self):
        router, clients = self._router(
            {"nvidia": "k"}, {"nvidia": Failure(ErrorInfo(kind="timeout", detail="hung"))})
        router.vision("s", "u", b"img")
        self.assertEqual(clients["nvidia"].vision.call_count, 1)


if __name__ == "__main__":
    unittest.main()
