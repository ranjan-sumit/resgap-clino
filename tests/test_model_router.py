"""
utils/model_router.py and utils/model_settings.py: per-role model routing,
cross-provider fallback, the model tester, discovery, and the recommendations.
No network: clients are fakes injected through the router's factory.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.database as db
from utils.azure_client import ErrorInfo, Failure, Success
from utils.model_router import (
    ALL_ROLES, CUSTOM_PROVIDER, MAIN_ROLES, ROLE_ANALYSIS, ROLE_COUNCIL_A, ROLE_COUNCIL_B, ROLE_COUNCIL_C,
    ROLE_COUNCIL_CHAIR, ROLE_EXTRACTION, ROLE_WIKI, ModelConfig, ModelRouter, ModelSpec, build_spec_client,
    fetch_models, role_for_stage, run_model_tests, token_boost,
)
from utils.model_settings import load_config, recommend, save_config, settings_path
from pipeline.llm_council import run_council, MODEL_SELECTION_AGENTS

FAST = ModelSpec("gemini", "gemini-3.5-flash-lite")
STRONG = ModelSpec("gemini", "gemini-3.6-flash")
NV = ModelSpec("nvidia", "openai/gpt-oss-20b")


class FakeClient:
    """Stands in for AzureOpenAIClient. `behaviour` is a Success/Failure, or a callable returning one."""
    def __init__(self, spec, behaviour=None, vision_model=None):
        self.spec, self.vision_model = spec, vision_model
        self.behaviour = behaviour if behaviour is not None else Success(f"ok from {spec.model}")
        self.calls, self.stages = [], []

    def set_stage(self, stage): self.stages.append(stage)

    def _result(self):
        return self.behaviour() if callable(self.behaviour) else self.behaviour

    def chat(self, system, user, temperature=0.3, max_tokens=4096, timeout_seconds=None, max_retries=None):
        self.calls.append(("chat", max_tokens, timeout_seconds, max_retries)); return self._result()

    def chat_json(self, system, user, max_tokens=4096, timeout_seconds=None, max_retries=None):
        self.calls.append(("chat_json", max_tokens, timeout_seconds, max_retries)); return self._result()

    def vision(self, system, user_text, image_bytes, max_tokens=2048):
        self.calls.append(("vision", max_tokens)); return Success("a chart")


def config(**over):
    roles = {ROLE_EXTRACTION: FAST, ROLE_WIKI: FAST, ROLE_ANALYSIS: STRONG,
             ROLE_COUNCIL_A: NV, ROLE_COUNCIL_B: FAST, ROLE_COUNCIL_C: STRONG, ROLE_COUNCIL_CHAIR: STRONG}
    roles.update(over.pop("roles", {}))
    return ModelConfig(roles, over.pop("fallback", NV))


def router(cfg=None, behaviours=None, vision=()):
    clients = {}
    behaviours = behaviours or {}

    def factory(spec, key, meter):
        clients.setdefault(spec, FakeClient(spec, behaviours.get(spec), vision_model="vlm" if spec in vision else None))
        return clients[spec]

    r = ModelRouter(cfg or config(), {"gemini": "g", "nvidia": "n"}, factory=factory)
    return r, clients


class StageRoleTests(unittest.TestCase):
    def test_every_pipeline_stage_maps_to_the_intended_role(self):
        expected = {
            "Stage 1B — Reference Extraction": ROLE_EXTRACTION,
            "Stage 2C — Evidence Extraction": ROLE_EXTRACTION,
            "Stage 2 — LLM Wiki": ROLE_WIKI,
            "Stage 3 — Knowledge Graph": ROLE_WIKI,
            "Stage 4 — Gap Detection": ROLE_ANALYSIS,
            "Stage 5 — Gap Validation": ROLE_ANALYSIS,
            "Stage 5b — Gap Challenger": ROLE_ANALYSIS,
            "Stage 6 — Proposals": ROLE_ANALYSIS,
            "Lab — Parameter extraction": ROLE_EXTRACTION,
            "Lab — Discovery": ROLE_ANALYSIS,
            "": ROLE_ANALYSIS, None: ROLE_ANALYSIS, "something new": ROLE_ANALYSIS,
        }
        for stage, role in expected.items():
            self.assertEqual(role_for_stage(stage), role, stage)


class RoutingTests(unittest.TestCase):
    def test_calls_go_to_the_model_chosen_for_the_current_stage(self):
        cfg = config(roles={ROLE_EXTRACTION: ModelSpec("groq", "llama-3.1-8b-instant")})
        r, clients = router(cfg)
        r.set_stage("Stage 1B — Reference Extraction"); r.chat_json("s", "u")
        r.set_stage("Stage 2 — LLM Wiki"); r.chat_json("s", "u")
        r.set_stage("Stage 4 — Gap Detection"); r.chat_json("s", "u")
        self.assertEqual(len(clients[ModelSpec("groq", "llama-3.1-8b-instant")].calls), 1)
        self.assertEqual(len(clients[FAST].calls), 1)
        self.assertEqual(len(clients[STRONG].calls), 1)
        self.assertEqual(clients[FAST].stages[-1], "Stage 2 — LLM Wiki")

    def test_stage_name_reaches_the_underlying_client_for_token_attribution(self):
        r, clients = router()
        r.set_stage("Stage 6 — Proposals"); r.chat("s", "u")
        self.assertEqual(clients[STRONG].stages[-1], "Stage 6 — Proposals")

    def test_thinking_models_get_token_headroom_and_plain_models_do_not(self):
        r, clients = router()
        r.set_stage("Stage 4 — Gap Detection"); r.chat_json("s", "u", max_tokens=2500)     # gemini-3.6-flash
        r.set_stage("Stage 2 — LLM Wiki"); r.chat_json("s", "u", max_tokens=2500)          # flash-lite
        self.assertEqual(clients[STRONG].calls[0][1], 5000)
        self.assertEqual(clients[FAST].calls[0][1], 2500)
        self.assertEqual(token_boost("gemini-3.6-flash"), 2.0)
        self.assertEqual(token_boost("anything-else"), 1.0)

    def test_pipeline_attributes_the_old_client_exposed(self):
        r, _ = router()
        self.assertEqual(r.api_key, "g")
        r.set_stage("Stage 2 — LLM Wiki")
        self.assertEqual(r.model, FAST.model)

    def test_client_per_spec_is_created_once(self):
        built = []
        r = ModelRouter(config(), {}, factory=lambda s, k, m: built.append(s) or FakeClient(s))
        for _ in range(3):
            r.set_stage("Stage 2 — LLM Wiki"); r.chat("s", "u")
        self.assertEqual(built.count(FAST), 1)


class FallbackTests(unittest.TestCase):
    fail = Failure(ErrorInfo("api_error", "Error code: 503 high demand"))

    def test_primary_failure_falls_back_to_the_other_provider_and_is_recorded(self):
        r, clients = router(behaviours={STRONG: self.fail})
        r.set_stage("Stage 4 — Gap Detection")
        res = r.chat_json("s", "u")
        self.assertIsInstance(res, Success)
        self.assertEqual(res.value, f"ok from {NV.model}")
        ev = r.fallback_events[0]
        self.assertEqual((ev["stage"], ev["from"], ev["to"], ev["fallback_ok"]),
                         ("Stage 4 — Gap Detection", STRONG.label, NV.label, True))
        self.assertIn("503", ev["error"])

    def test_both_failing_reports_both_errors(self):
        r, _ = router(behaviours={STRONG: self.fail, NV: Failure(ErrorInfo("timeout", "timed out"))})
        r.set_stage("Stage 4 — Gap Detection")
        res = r.chat_json("s", "u")
        self.assertIsInstance(res, Failure)
        self.assertIn("503", res.error.detail)
        self.assertIn("timed out", res.error.detail)
        self.assertIn("fallback", res.error.detail)

    def test_no_fallback_configured_returns_the_original_failure(self):
        r, clients = router(config(fallback=None), behaviours={STRONG: self.fail})
        r.set_stage("Stage 4 — Gap Detection")
        self.assertIs(r.chat_json("s", "u"), self.fail)
        self.assertNotIn(NV, clients)

    def test_fallback_equal_to_primary_is_not_retried(self):
        r, clients = router(config(fallback=STRONG), behaviours={STRONG: self.fail})
        r.set_stage("Stage 4 — Gap Detection"); r.chat_json("s", "u")
        self.assertEqual(len(clients[STRONG].calls), 1)
        self.assertEqual(r.fallback_events, [])

    def test_when_the_fallback_is_the_failing_model_the_analysis_model_takes_over(self):
        # all-Gemini: the council's strong model IS the configured fallback; a quota error on it
        # used to leave the call unanswered. The Analysis-role model is the next link.
        cfg = config(roles={ROLE_ANALYSIS: FAST, ROLE_COUNCIL_CHAIR: STRONG}, fallback=STRONG)
        r, clients = router(cfg, behaviours={STRONG: self.fail})
        res = r._call(ROLE_COUNCIL_CHAIR, "chat", "s", "u", temperature=0.3, max_tokens=100,
                      timeout_seconds=None, max_retries=None)
        self.assertIsInstance(res, Success)
        self.assertEqual(res.value, f"ok from {FAST.model}")
        self.assertEqual(r.fallback_events[0]["to"], FAST.label)

    def test_the_chain_stops_at_the_first_fallback_that_answers(self):
        cfg = config(roles={ROLE_ANALYSIS: FAST}, fallback=NV)
        r, clients = router(cfg, behaviours={STRONG: self.fail})
        r.set_stage("Stage 4c — Gap Critic")
        r.chat_json("s", "u")
        self.assertEqual(len(r.fallback_events), 1)
        self.assertNotIn(FAST, clients)                                  # NV answered; FAST never needed

    def test_every_link_failing_reports_every_error(self):
        cfg = config(roles={ROLE_ANALYSIS: FAST}, fallback=NV)
        r, _ = router(cfg, behaviours={STRONG: self.fail, NV: Failure(ErrorInfo("timeout", "t1")),
                                       FAST: Failure(ErrorInfo("rate_limit", "429 quota"))})
        r.set_stage("Stage 4c — Gap Critic")
        res = r.chat_json("s", "u")
        self.assertIsInstance(res, Failure)
        for needle in ("503", "t1", "429 quota"):
            self.assertIn(needle, res.error.detail)
        self.assertEqual(len(r.fallback_events), 2)

    def test_an_explicit_no_fallback_is_still_respected(self):
        cfg = config(roles={ROLE_ANALYSIS: FAST}, fallback=None)
        r, clients = router(cfg, behaviours={STRONG: self.fail})
        r.set_stage("Stage 4c — Gap Critic")
        self.assertIs(r.chat_json("s", "u"), self.fail)
        self.assertNotIn(FAST, clients)

    def test_success_never_touches_the_fallback(self):
        r, clients = router()
        r.set_stage("Stage 4 — Gap Detection"); r.chat_json("s", "u")
        self.assertNotIn(NV, clients)

    def test_unsupported_is_not_a_reason_to_fall_back(self):
        unsupported = Failure(ErrorInfo("unsupported", "no images"))
        r, clients = router(behaviours={STRONG: unsupported})
        r.set_stage("Stage 4 — Gap Detection")
        self.assertIs(r.chat("s", "u"), unsupported)
        self.assertNotIn(NV, clients)


class VisionTests(unittest.TestCase):
    def test_uses_the_first_model_that_can_read_images(self):
        r, clients = router(vision={STRONG})
        r.set_stage("Stage 1 — Parsing")
        self.assertIsInstance(r.vision("s", "u", b"img"), Success)
        self.assertEqual(clients[STRONG].calls[-1][0], "vision")

    def test_clean_failure_when_no_selected_model_can_read_images(self):
        r, _ = router(vision=())
        res = r.vision("s", "u", b"img")
        self.assertIsInstance(res, Failure)
        self.assertEqual(res.error.kind, "unsupported")


class CouncilTests(unittest.TestCase):
    def test_each_seat_and_the_chair_use_their_own_configured_model(self):
        r, clients = router()
        backend = r.council_backend()
        self.assertEqual(backend.label("gpt_20b"), NV.label)
        self.assertEqual(backend.label("llama_3b"), FAST.label)
        self.assertEqual(backend.label("gpt_120b"), STRONG.label)
        self.assertEqual(backend.call("nemotron", "s", "u"), f"ok from {STRONG.model}")
        self.assertEqual(clients[STRONG].calls[-1][0], "chat")

    def test_failed_call_keeps_the_council_failure_contract(self):
        r, _ = router(config(fallback=None), behaviours={NV: Failure(ErrorInfo("api_error", "410 Gone"))})
        out = r.council_backend().call("gpt_20b", "s", "u")
        self.assertEqual(out["_failed"], True)
        self.assertIn("410", out["error"])

    def test_run_council_runs_on_the_router_and_names_the_real_models(self):
        r, _ = router(config(fallback=None))
        out = run_council(MODEL_SELECTION_AGENTS, "ctx", "final", backend=r.council_backend())
        self.assertEqual([a["model"] for a in out["agents"]], [NV.label, FAST.label, STRONG.label])
        self.assertNotIn("kimi", out["transcript"])
        self.assertTrue(all(a["response"] for a in out["agents"]))

    def test_run_council_without_a_backend_still_uses_the_legacy_table(self):
        with patch("pipeline.llm_council._call_model", return_value="legacy reply") as call:
            out = run_council(MODEL_SELECTION_AGENTS, "ctx", "final", api_key="k")
        self.assertTrue(call.called)
        self.assertEqual(out["agents"][0]["model"], "openai/gpt-oss-20b")


class ReasoningEffortTests(unittest.TestCase):
    """Gemini's thinking models need a low reasoning effort or their strict-JSON
    output is cut off / malformed and a single call can take minutes."""

    def _create_kwargs(self, model):
        from utils.azure_client import AzureOpenAIClient
        with patch("utils.azure_client.OpenAI") as openai_cls, \
                patch("utils.azure_client._collect_stream", return_value="{}"):
            c = AzureOpenAIClient(api_key="k", base_url="https://example.test/v1", model=model, fallback_model=None)
            c.chat("s", "u")
            return openai_cls.return_value.chat.completions.create.call_args.kwargs

    def test_thinking_models_are_sent_a_low_reasoning_effort(self):
        for model in ("gemini-3.6-flash", "gemini-3.7-flash"):
            self.assertEqual(self._create_kwargs(model)["extra_body"], {"reasoning_effort": "low"}, model)

    def test_other_models_are_sent_nothing_extra(self):
        for model in ("gemini-3.5-flash-lite", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"):
            self.assertNotIn("extra_body", self._create_kwargs(model), model)


_QUOTA_429 = (
    "Error code: 429 - [{'error': {'code': 429, 'message': 'You exceeded your current quota. "
    "* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, "
    "limit: 5, model: gemini-3.6-flash\\nPlease retry in 39.488792667s.', 'status': 'RESOURCE_EXHAUSTED', "
    "'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}}]")


class RetryAfterTests(unittest.TestCase):
    def test_reads_the_wait_from_each_provider_style(self):
        from utils.azure_client import _retry_after_seconds as ra
        self.assertAlmostEqual(ra("Please retry in 39.488792667s."), 40.4888, places=3)
        self.assertEqual(ra('"retryDelay": "39s"'), 40.0)
        self.assertAlmostEqual(ra("Rate limit reached. Please try again in 1.5s."), 2.5)
        self.assertAlmostEqual(ra("please try again in 250ms"), 1.25)
        self.assertEqual(ra("retry in 500s"), 65.0)                    # capped: not worth blocking a run
        self.assertIsNone(ra("something unrelated"))
        self.assertIsNone(ra(""))

    def _client(self):
        from utils.azure_client import AzureOpenAIClient
        return AzureOpenAIClient(api_key="k", base_url="https://example.test/v1", model="m", fallback_model=None)

    def test_a_rate_limited_call_waits_what_the_provider_asked_then_succeeds(self):
        with patch("utils.azure_client.OpenAI"), patch("time.sleep") as sleep, \
                patch("utils.azure_client._collect_stream",
                      side_effect=[Exception(_QUOTA_429), "the answer"]):
            result = self._client().chat("s", "u")
        self.assertIsInstance(result, Success)
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], 40.4888, places=3)     # not the old 1 s

    def test_a_timeout_still_uses_the_short_exponential_backoff(self):
        with patch("utils.azure_client.OpenAI"), patch("time.sleep") as sleep, \
                patch("utils.azure_client._collect_stream",
                      side_effect=[Exception("Request timed out"), "ok"]):
            self._client().chat("s", "u")
        self.assertEqual(sleep.call_args.args[0], 1)

    def test_a_rate_limit_without_a_stated_wait_falls_back_to_exponential_backoff(self):
        with patch("utils.azure_client.OpenAI"), patch("time.sleep") as sleep, \
                patch("utils.azure_client._collect_stream", side_effect=[Exception("429 Too Many Requests"), "ok"]):
            self._client().chat("s", "u")
        self.assertEqual(sleep.call_args.args[0], 1)


class FriendlyErrorTests(unittest.TestCase):
    def test_a_rate_limit_says_so_with_the_limit_and_the_wait(self):
        from utils.model_router import friendly_error
        msg = friendly_error(ErrorInfo("rate_limit", _QUOTA_429))
        self.assertIn("Rate limit reached", msg)
        self.assertIn("5 requests per minute", msg)
        self.assertIn("retry in about 40 s", msg)
        self.assertIn("not a problem with the model", msg)

    def test_other_errors_keep_their_own_text(self):
        from utils.model_router import friendly_error
        self.assertEqual(friendly_error(ErrorInfo("api_error", "Error code: 410 Gone")), "Error code: 410 Gone")


class SplitClient(FakeClient):
    """Plain chat works, strict-JSON chat is throttled."""
    def chat_json(self, *a, **k):
        return Failure(ErrorInfo("rate_limit", _QUOTA_429))


class RateLimitedTesterTests(unittest.TestCase):
    def test_a_throttled_plain_call_is_reported_as_rate_limited_not_as_a_broken_model(self):
        cfg = config(fallback=None)
        out = run_model_tests(cfg, {"gemini": "g", "nvidia": "n"},
                              factory=lambda s, k, m: FakeClient(s, Failure(ErrorInfo("rate_limit", _QUOTA_429))))
        for o in out:
            self.assertFalse(o["ok"])
            self.assertTrue(o["rate_limited"])
            self.assertIn("Rate limit reached", o["error"])

    def test_a_throttled_json_check_is_inconclusive_not_a_failure(self):
        out = run_model_tests(config(fallback=None), {"gemini": "g", "nvidia": "n"},
                              factory=lambda s, k, m: SplitClient(s, Success("pong")))
        for o in out:
            self.assertTrue(o["ok"])
            self.assertIsNone(o["json_ok"])
            self.assertIn("Rate limit reached", o["json_note"])


class ExplainTests(unittest.TestCase):
    def test_warns_about_the_5_per_minute_limit_only_where_it_matters(self):
        from utils.model_settings import explain
        notes = explain(config())          # analysis = gemini-3.6-flash, council chair = gemini-3.6-flash
        self.assertIn("5 requests/minute", notes[ROLE_ANALYSIS])
        self.assertNotIn("5 requests/minute", notes[ROLE_COUNCIL_CHAIR])
        self.assertEqual(notes[ROLE_EXTRACTION], "")

    def test_benchmark_table_lists_the_measured_limits(self):
        from utils.model_settings import BENCHMARK
        by_model = {r["model"]: r for r in BENCHMARK}
        self.assertEqual(by_model["Gemini · gemini-3.6-flash"]["limit"], "5 requests per minute")


class ConfigTests(unittest.TestCase):
    def test_round_trip(self):
        cfg = config(roles={ROLE_WIKI: ModelSpec(CUSTOM_PROVIDER, "my-model", "https://example.test/v1")})
        again = ModelConfig.from_dict(json.loads(json.dumps(cfg.to_dict())))
        self.assertEqual(again.roles, cfg.roles)
        self.assertEqual(again.fallback, cfg.fallback)

    def test_rejects_unknown_provider_missing_model_and_missing_main_roles(self):
        with self.assertRaises(ValueError):
            ModelSpec.from_dict({"provider": "nope", "model": "x"})
        with self.assertRaises(ValueError):
            ModelSpec.from_dict({"provider": "gemini", "model": "  "})
        with self.assertRaises(ValueError):
            ModelConfig.from_dict({"roles": {ROLE_EXTRACTION: {"provider": "gemini", "model": "m"}}})

    def test_unset_council_seats_follow_the_analysis_model(self):
        cfg = ModelConfig({r: FAST for r in MAIN_ROLES}, None)
        self.assertEqual(cfg.spec_for(ROLE_COUNCIL_B), FAST)

    def test_distinct_specs_lists_each_model_once_including_the_fallback(self):
        specs = config().distinct_specs()
        self.assertEqual(len(specs), len(set(specs)))
        self.assertIn(NV, specs)


class BuildClientTests(unittest.TestCase):
    @patch("utils.azure_client.OpenAI")
    def test_registry_provider_client_has_no_builtin_fallback_and_its_vision_model(self, _o):
        c = build_spec_client(STRONG, "k")
        self.assertIsNone(c.fallback_model)               # the router owns fallback
        self.assertEqual(c.vision_model, "gemini-3.6-flash")
        self.assertEqual(c.model, STRONG.model)

    @patch("utils.azure_client.OpenAI")
    def test_custom_endpoint_uses_its_own_base_url(self, openai_cls):
        build_spec_client(ModelSpec(CUSTOM_PROVIDER, "m", "https://example.test/v1"), "k")
        self.assertEqual(openai_cls.call_args.kwargs["base_url"], "https://example.test/v1")

    @patch("utils.azure_client.make_nvidia_client")
    def test_nvidia_client_drops_the_retired_kimi_fallback(self, _m):
        self.assertIsNone(build_spec_client(NV, "k").fallback_model)


class ModelTesterTests(unittest.TestCase):
    def _factory(self, results):
        def factory(spec, key, meter):
            return FakeClient(spec, results.get(spec))
        return factory

    def test_reports_ok_latency_and_json_for_each_distinct_model(self):
        cfg = config()
        out = run_model_tests(cfg, {"gemini": "g", "nvidia": "n"},
                          factory=self._factory({FAST: Success('{"ok": true}'), STRONG: Success('{"ok": true}'),
                                                 NV: Success('{"ok": true}')}))
        by_label = {o["label"]: o for o in out}
        self.assertEqual(len(out), 3)                                     # FAST, STRONG, NV
        self.assertTrue(all(o["ok"] and o["json_ok"] for o in out))
        self.assertIn("Extraction", by_label[FAST.label]["roles"])
        self.assertIn("Wiki & graph", by_label[FAST.label]["roles"])      # one test, both roles listed
        self.assertIn("Fallback", by_label[NV.label]["roles"])
        self.assertIsNotNone(by_label[FAST.label]["latency_s"])

    def test_missing_key_is_reported_without_a_call(self):
        out = run_model_tests(config(fallback=None), {"gemini": "g"}, factory=self._factory({}))
        nv = next(o for o in out if o["spec"] == NV)
        self.assertFalse(nv["ok"])
        self.assertIn("No API key", nv["error"])

    def test_api_error_text_is_shown_and_json_is_not_attempted(self):
        out = run_model_tests(config(fallback=None), {"gemini": "g", "nvidia": "n"},
                          factory=self._factory({NV: Failure(ErrorInfo("api_error", "Error code: 410 Gone"))}))
        nv = next(o for o in out if o["spec"] == NV)
        self.assertFalse(nv["ok"])
        self.assertIn("410", nv["error"])
        self.assertIsNone(nv["json_ok"])

    def test_non_json_reply_is_flagged(self):
        out = run_model_tests(config(fallback=None), {"gemini": "g", "nvidia": "n"},
                          factory=self._factory({FAST: Success("pong, definitely not json")}))
        f = next(o for o in out if o["spec"] == FAST)
        self.assertTrue(f["ok"])
        self.assertFalse(f["json_ok"])

    def test_json_in_code_fences_still_counts(self):
        out = run_model_tests(config(fallback=None), {"gemini": "g", "nvidia": "n"},
                          factory=self._factory({FAST: Success('```json\n{"ok": true}\n```')}))
        self.assertTrue(next(o for o in out if o["spec"] == FAST)["json_ok"])

    def test_empty_reply_is_a_failure(self):
        out = run_model_tests(config(fallback=None), {"gemini": "g", "nvidia": "n"},
                          factory=self._factory({FAST: Success("  ")}))
        self.assertFalse(next(o for o in out if o["spec"] == FAST)["ok"])

    def test_a_crashing_client_is_reported_not_raised(self):
        def boom(spec, key, meter):
            raise RuntimeError("cannot build")
        out = run_model_tests(config(fallback=None), {"gemini": "g", "nvidia": "n"}, factory=boom)
        self.assertTrue(all(not o["ok"] and "cannot build" in o["error"] for o in out))

    def test_uses_a_short_timeout_and_no_retries_so_testing_is_fast(self):
        seen = []
        def factory(spec, key, meter):
            c = FakeClient(spec, Success('{"ok": true}')); seen.append(c); return c
        run_model_tests(config(fallback=None), {"gemini": "g", "nvidia": "n"}, factory=factory, timeout=25)
        calls = [call for c in seen for call in c.calls]
        self.assertTrue(all(t == 25 and m == 0 for _kind, _tok, t, m in calls))

    def test_custom_endpoint_without_a_base_url_is_reported(self):
        cfg = config(roles={ROLE_WIKI: ModelSpec(CUSTOM_PROVIDER, "m", "")}, fallback=None)
        out = run_model_tests(cfg, {CUSTOM_PROVIDER: "k", "gemini": "g", "nvidia": "n"}, factory=self._factory({}))
        c = next(o for o in out if o["spec"].provider == CUSTOM_PROVIDER)
        self.assertIn("base URL", c["error"])


class FetchModelsTests(unittest.TestCase):
    def _resp(self, ids):
        m = MagicMock(); m.raise_for_status.return_value = None
        m.json.return_value = {"data": [{"id": i} for i in ids]}
        return m

    @patch("utils.model_router.requests.get")
    def test_lists_chat_models_only_and_strips_the_models_prefix(self, get):
        get.return_value = self._resp(["models/gemini-3.5-flash-lite", "gemini-embedding-001", "gemini-3.5-flash-tts",
                                       "gemini-3.6-flash", "whisper-large-v3"])
        self.assertEqual(fetch_models("gemini", "k"), ["gemini-3.5-flash-lite", "gemini-3.6-flash"])
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer k"})

    @patch("utils.model_router.requests.get")
    def test_groq_speech_and_safety_models_are_not_offered(self, get):
        get.return_value = self._resp([
            "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "whisper-large-v3-turbo",
            "canopylabs/orpheus-v1-english", "openai/gpt-oss-safeguard-20b",
            "meta-llama/llama-prompt-guard-2-22m", "llama-3.1-8b-instant"])
        self.assertEqual(fetch_models("groq", "k"),
                         ["llama-3.1-8b-instant", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"])

    @patch("utils.model_router.requests.get")
    def test_custom_endpoint_uses_the_given_base_url(self, get):
        get.return_value = self._resp(["m1"])
        fetch_models(CUSTOM_PROVIDER, "k", "https://example.test/v1/")
        self.assertEqual(get.call_args.args[0], "https://example.test/v1/models")

    @patch("utils.model_router.requests.get", side_effect=__import__("requests").ConnectionError("down"))
    def test_unreachable_provider_gives_an_empty_list_not_an_error(self, _g):
        self.assertEqual(fetch_models("groq", "k"), [])

    def test_no_key_or_no_base_url_makes_no_request(self):
        with patch("utils.model_router.requests.get") as get:
            self.assertEqual(fetch_models("groq", ""), [])
            self.assertEqual(fetch_models(CUSTOM_PROVIDER, "k", ""), [])
        get.assert_not_called()


class RecommendationTests(unittest.TestCase):
    def test_gemini_only_keeps_the_call_heavy_jobs_on_the_model_with_request_headroom(self):
        cfg = recommend({"gemini"})
        # extraction, wiki and analysis make dozens of calls in a row; gemini-3.6-flash's
        # free tier allows 5 requests/minute (measured), so it must NOT be their default.
        for role in (ROLE_EXTRACTION, ROLE_WIKI, ROLE_ANALYSIS):
            self.assertEqual(cfg.roles[role], FAST, role)
        # the council makes only a handful of calls, so the stronger model fits the chair
        self.assertEqual(cfg.roles[ROLE_COUNCIL_CHAIR], STRONG)
        self.assertNotEqual(cfg.fallback, cfg.roles[ROLE_ANALYSIS])
        self.assertEqual(cfg.fallback.provider, "gemini")

    def test_the_rate_limited_model_is_never_a_default_for_the_call_heavy_jobs(self):
        for avail in ({"gemini"}, {"gemini", "nvidia"}, {"gemini", "nvidia", "openai", "groq"}):
            cfg = recommend(avail)
            for role in (ROLE_EXTRACTION, ROLE_WIKI, ROLE_ANALYSIS):
                self.assertNotEqual(cfg.roles[role], STRONG, (avail, role))

    def test_with_two_providers_the_fallback_is_on_the_other_one_and_the_council_spans_both(self):
        cfg = recommend({"gemini", "nvidia"})
        self.assertEqual(cfg.fallback.provider, "nvidia")
        seats = {cfg.roles[r] for r in (ROLE_COUNCIL_A, ROLE_COUNCIL_B, ROLE_COUNCIL_C)}
        self.assertEqual(len(seats), 3)
        self.assertEqual({s.provider for s in seats}, {"gemini", "nvidia"})

    def test_nvidia_only_never_recommends_the_retired_kimi_models(self):
        cfg = recommend({"nvidia"})
        for spec in cfg.distinct_specs():
            self.assertNotIn("kimi", spec.model)
            self.assertNotIn("deepseek", spec.model)

    def test_never_recommends_the_slow_gemini_37(self):
        for avail in ({"gemini"}, {"gemini", "nvidia", "openai", "groq"}):
            self.assertNotIn("gemini-3.7-flash", {s.model for s in recommend(avail).distinct_specs()})

    def test_fastest_preset_uses_the_fast_model_for_everything(self):
        cfg = recommend({"gemini", "nvidia"}, preset="fastest")
        self.assertTrue(all(cfg.roles[r] == FAST for r in MAIN_ROLES))
        self.assertTrue(all(cfg.roles[r] == FAST for r in (ROLE_COUNCIL_A, ROLE_COUNCIL_B, ROLE_COUNCIL_C,
                                                           ROLE_COUNCIL_CHAIR)))

    def test_no_keys_at_all_still_returns_a_complete_config(self):
        cfg = recommend(set())
        self.assertTrue(all(r in cfg.roles for r in MAIN_ROLES))

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(ValueError):
            recommend({"gemini"}, preset="best")

    def test_every_recommended_spec_is_a_model_the_registry_knows(self):
        from utils.model_providers import PROVIDER_REGISTRY
        for avail in ({"gemini"}, {"nvidia"}, {"gemini", "nvidia", "groq", "openai"}):
            for spec in recommend(avail).distinct_specs():
                self.assertIn(spec.model, PROVIDER_REGISTRY[spec.provider].known_models, spec)


class SettingsFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="resgap_models_")
        self.patcher = patch.object(db, "_SCHEMA", str(Path(self.tmp) / "t.db"))
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_saved_choice_is_loaded_back(self):
        cfg = recommend({"gemini", "nvidia"})
        save_config(cfg)
        self.assertEqual(load_config({"gemini"}).to_dict(), cfg.to_dict())

    def test_no_file_means_the_recommendation(self):
        self.assertEqual(load_config({"gemini"}).to_dict(), recommend({"gemini"}).to_dict())

    def test_corrupt_file_falls_back_to_the_recommendation(self):
        settings_path().write_text("{not json", encoding="utf-8")
        self.assertEqual(load_config({"gemini"}).to_dict(), recommend({"gemini"}).to_dict())

    def test_saved_file_never_contains_keys(self):
        save_config(recommend({"gemini"}))
        text = settings_path().read_text(encoding="utf-8").lower()
        self.assertNotIn("api_key", text)
        self.assertNotIn("secret", text)


if __name__ == "__main__":
    unittest.main()
