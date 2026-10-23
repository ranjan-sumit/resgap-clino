"""PR-22e: the custom OpenAI-compatible endpoint, against a real local server (the real client and SDK, no mocks), and the
deployment's provider policy."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from utils import azure_client
from utils.azure_client import ErrorInfo
from utils.model_router import (CUSTOM_PROVIDER, ModelSpec, _test_one, build_spec_client, fetch_models, friendly_error)
from utils.provider_policy import ProviderNotAllowed, check_endpoint, endpoint_problem, provider_allowed


class _Server:
    """A tiny OpenAI-compatible server. `strict=True` behaves like OpenAI's newer models: no `max_tokens`, only the default
    temperature."""

    def __init__(self, strict=False, key="secret-key"):
        self.strict, self.key, self.requests = strict, key, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _auth(self):
                return self.headers.get("Authorization") == f"Bearer {outer.key}"

            def _json(self, code, payload):
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if not self._auth():
                    return self._json(401, {"error": {"message": "Incorrect API key provided"}})
                outer.requests.append(("GET", self.path, None))
                self._json(200, {"data": [{"id": "llama3.1"}, {"id": "text-embedding-3-small"}, {"id": "whisper-1"}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(("POST", self.path, body))
                if not self._auth():
                    return self._json(401, {"error": {"message": "Incorrect API key provided"}})
                if outer.strict and "max_tokens" in body:
                    return self._json(400, {"error": {"message": "Unsupported parameter: 'max_tokens' is not supported with "
                                                                 "this model. Use 'max_completion_tokens' instead."}})
                if outer.strict and body.get("temperature", 1) != 1:
                    return self._json(400, {"error": {"message": f"Unsupported value: 'temperature' does not support "
                                                                 f"{body['temperature']} with this model. Only the default (1) value is supported."}})
                if outer.strict and body.get("top_p", 1) != 1:
                    return self._json(400, {"error": {"message": "Unsupported value: 'top_p' does not support 0.95 with this model."}})
                text = '{"ok": true}' if "JSON" in json.dumps(body["messages"]) else "pong"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for piece, finish in ((text, None), ("", "stop")):
                    chunk = {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": body["model"],
                             "choices": [{"index": 0, "delta": {"content": piece} if piece else {}, "finish_reason": finish}]}
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = _Server()
    yield s
    s.close()


@pytest.fixture
def strict_server():
    s = _Server(strict=True)
    azure_client._PARAM_COMPAT.clear()
    yield s
    s.close()
    azure_client._PARAM_COMPAT.clear()


def _client(server, model="local-model", key="secret-key"):
    return build_spec_client(ModelSpec(CUSTOM_PROVIDER, model, server.base), key)


# ── the real client against a real server ────────────────────────────────────────────────────
def test_a_custom_endpoint_answers_chat_and_strict_json_with_the_key_in_the_header(server):
    client = _client(server)
    assert client.chat("You are terse.", "say pong", max_tokens=50, max_retries=0).value == "pong"
    assert client.chat_json("Return a JSON object.", "go", max_tokens=50, max_retries=0).value == '{"ok": true}'
    posts = [r for r in server.requests if r[0] == "POST"]
    assert len(posts) == 2 and all(r[1] == "/v1/chat/completions" for r in posts)
    assert posts[0][2]["model"] == "local-model" and posts[0][2]["max_tokens"] == 50


def test_a_wrong_key_is_reported_as_an_api_error(server):
    result = _client(server, key="wrong").chat("s", "u", max_tokens=20, max_retries=0)
    assert result.error.kind == "api_error" and "401" in result.error.detail
    assert "did not accept the API key" in friendly_error(result.error)


def test_the_models_list_keeps_chat_models_only_and_sends_the_key(server):
    assert fetch_models(CUSTOM_PROVIDER, "secret-key", server.base) == ["llama3.1"]
    assert fetch_models(CUSTOM_PROVIDER, "wrong", server.base) == []
    assert fetch_models(CUSTOM_PROVIDER, "", server.base) == []


def test_the_settings_test_reports_ok_latency_and_json_for_a_custom_model(server):
    out = _test_one(ModelSpec(CUSTOM_PROVIDER, "local-model", server.base), {CUSTOM_PROVIDER: "secret-key"},
                    ["Analysis"], build_spec_client, 20)
    assert out["ok"] and out["json_ok"] is True and out["error"] == ""


def test_a_timeout_is_not_silently_tripled_by_the_sdks_own_retries():
    from unittest.mock import patch
    with patch("utils.azure_client.OpenAI") as sdk:
        build_spec_client(ModelSpec("gemini", "gemini-3.5-flash-lite"), "k")
        build_spec_client(ModelSpec("nvidia", "openai/gpt-oss-20b"), "k")
        build_spec_client(ModelSpec(CUSTOM_PROVIDER, "m", "https://llm.example.com/v1"), "k")
    assert sdk.call_count == 3 and all(c.kwargs.get("max_retries") == 0 for c in sdk.call_args_list)


def test_a_slow_endpoint_fails_at_the_requested_limit_not_three_times_later():
    import time
    slow = _Server()
    orig = slow.httpd.RequestHandlerClass.do_POST

    def hang(self):
        time.sleep(6)
        orig(self)
    slow.httpd.RequestHandlerClass.do_POST = hang
    try:
        t0 = time.time()
        r = _client(slow).chat("s", "u", max_tokens=10, timeout_seconds=2, max_retries=0)
        elapsed = time.time() - t0
    finally:
        slow.close()
    assert r.error.kind == "timeout" and elapsed < 5.5                     # one 2 s attempt, not three


# ── models that refuse max_tokens and a custom temperature (OpenAI's newer models) ───────────
def test_a_model_that_wants_max_completion_tokens_and_the_default_temperature_is_learned_and_then_used(strict_server):
    client = _client(strict_server, "strict-model")
    first = client.chat("system", "say pong", temperature=0.3, max_tokens=64, max_retries=0)
    assert first.value == "pong"
    posts = [r[2] for r in strict_server.requests if r[0] == "POST"]
    assert len(posts) == 3                                              # max_tokens refused, temperature refused, then accepted
    assert "max_tokens" in posts[0] and "max_tokens" not in posts[-1] and posts[-1]["max_completion_tokens"] == 64
    assert "temperature" not in posts[-1] and posts[-1].get("top_p", 1) == 1      # only what was refused is dropped
    strict_server.requests.clear()
    assert client.chat("system", "again", temperature=0.1, max_tokens=64, max_retries=0).value == "pong"
    assert len([r for r in strict_server.requests if r[0] == "POST"]) == 1   # remembered: no more refused requests


def test_what_one_model_refuses_is_not_applied_to_another_model_or_provider(strict_server):
    _client(strict_server, "strict-model").chat("s", "u", max_tokens=10, max_retries=0)
    other_model = azure_client._apply_compat({"max_tokens": 5, "temperature": 0.3}, strict_server.base, "another-model")
    assert other_model == {"max_tokens": 5, "temperature": 0.3}
    other_host = azure_client._apply_compat({"max_tokens": 5}, "https://api.groq.com/openai/v1", "strict-model")
    assert other_host == {"max_tokens": 5}


def test_an_unrelated_error_is_not_mistaken_for_a_refused_parameter():
    assert azure_client._learn_compat("Error code: 500 - internal error", "http://x/v1", "m") is False
    assert azure_client._learn_compat("Rate limit reached for requests", "http://x/v1", "m") is False
    assert azure_client._PARAM_COMPAT.get(("http://x/v1", "m")) is None


def test_learning_stops_when_there_is_nothing_new_so_a_retry_cannot_loop():
    azure_client._PARAM_COMPAT.clear()
    err = "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."
    assert azure_client._learn_compat(err, "http://x/v1", "m") is True
    assert azure_client._learn_compat(err, "http://x/v1", "m") is False
    azure_client._PARAM_COMPAT.clear()


# ── the deployment's policy ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("url,fragment", [
    ("", "needs a base URL"),
    ("ftp://llm.example.com/v1", "https://"),
    ("http://llm.example.com/v1", "https://"),
    ("https://user:pass@llm.example.com/v1", "user name or password"),
    ("http://169.254.169.254/latest/meta-data", "https://"),
    ("https://169.254.169.254/v1", "metadata"),
    ("https://metadata.google.internal/v1", "metadata"),
    ("https://[fe80::1]/v1", "link-local"),
    ("not a url", "https://"),
])
def test_unsafe_custom_addresses_are_refused_with_a_reason(url, fragment):
    assert fragment in endpoint_problem(url)
    with pytest.raises(ProviderNotAllowed):
        check_endpoint(url)


@pytest.mark.parametrize("url", ["https://api.example.com/v1", "http://localhost:11434/v1", "http://127.0.0.1:8000/v1",
                                 "https://10.0.0.5:8443/v1", "https://llm.corp.internal/v1"])
def test_ordinary_endpoints_pass(url):
    assert endpoint_problem(url) is None


def test_the_allowed_hosts_list_limits_where_the_key_can_go(monkeypatch):
    monkeypatch.setenv("RESGAP_ALLOWED_HOSTS", "llm.corp.example, .internal.example")
    assert endpoint_problem("https://llm.corp.example/v1") is None
    assert endpoint_problem("https://gpu1.internal.example/v1") is None
    assert "not on this deployment's list" in endpoint_problem("https://api.example.com/v1")
    assert endpoint_problem("https://evilinternal.example/v1")                 # suffix match needs the dot boundary


def test_the_allowed_providers_list_removes_the_others_everywhere(monkeypatch):
    monkeypatch.setenv("RESGAP_ALLOWED_PROVIDERS", "gemini,custom")
    assert provider_allowed("gemini") and provider_allowed("CUSTOM") and not provider_allowed("groq")
    with pytest.raises(ProviderNotAllowed, match="groq"):
        build_spec_client(ModelSpec("groq", "llama-3.3-70b-versatile"), "k")
    assert fetch_models("groq", "k") == []
    out = _test_one(ModelSpec("openai", "gpt-x"), {"openai": "k"}, ["Analysis"], build_spec_client, 5)
    assert "not allowed" in out["error"]


def test_a_refused_custom_address_never_receives_the_key(monkeypatch):
    sent = []
    monkeypatch.setattr("utils.model_router.requests.get", lambda *a, **k: sent.append((a, k)))
    assert fetch_models(CUSTOM_PROVIDER, "secret", "http://169.254.169.254/v1") == []
    assert fetch_models(CUSTOM_PROVIDER, "secret", "http://llm.example.com/v1") == []
    assert sent == []
    with pytest.raises(ProviderNotAllowed):
        build_spec_client(ModelSpec(CUSTOM_PROVIDER, "m", "http://llm.example.com/v1"), "secret")


def test_settings_do_not_offer_a_custom_endpoint_whose_address_is_refused(monkeypatch):
    from ui import settings_state as ss
    from utils.model_providers import PROVIDER_REGISTRY
    settings = {"typed_keys": {}, "custom_base": "http://llm.example.com/v1", "custom_key": "k"}
    out = ss.resolve_keys(settings, PROVIDER_REGISTRY, CUSTOM_PROVIDER, env={})
    assert CUSTOM_PROVIDER not in out["available"] and "https://" in out["custom_base_problem"]
    good = ss.resolve_keys({**settings, "custom_base": "https://llm.example.com/v1"}, PROVIDER_REGISTRY, CUSTOM_PROVIDER, env={})
    assert CUSTOM_PROVIDER in good["available"] and good["custom_base_problem"] is None
    monkeypatch.setenv("RESGAP_ALLOWED_PROVIDERS", "gemini")
    limited = ss.resolve_keys({"typed_keys": {"groq": "g", "gemini": "k"}}, PROVIDER_REGISTRY, CUSTOM_PROVIDER, env={})
    assert limited["available"] == {"gemini"}


def test_the_model_picker_offers_only_allowed_providers(app_test, isolated_env, monkeypatch):
    monkeypatch.setenv("RESGAP_ALLOWED_PROVIDERS", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 30)
    at = app_test(timeout=90)
    at.button(key="settings_btn").click().run()
    providers = [s for s in at.selectbox if s.key and s.key.startswith("mp_")]
    assert providers and all(set(s.options) <= {"Google Gemini", "No fallback"} for s in providers)
    assert {o for s in providers for o in s.options} == {"Google Gemini", "No fallback"}
