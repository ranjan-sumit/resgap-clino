import threading
import time

import pytest

from tests.fakes import FakeClient
from utils import azure_client as ac
from utils.model_router import ModelRouter, token_boost
from utils.model_settings import recommend
from utils.rate_limiter import RateLimiter


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []
        self.lock = threading.Lock()

    def now(self):
        with self.lock:
            return self.t

    def sleep(self, s):
        with self.lock:
            self.sleeps.append(s)
            self.t += s


def _limiter(limits, clock):
    return RateLimiter(limits, clock=clock.now, sleep=clock.sleep)


def test_twenty_calls_on_a_5_rpm_model_never_exceed_the_limit():
    clock = Clock()
    lim = _limiter({("p", "m"): 5}, clock)
    starts = []
    for _ in range(20):
        lim.acquire("p", "m")
        starts.append(clock.now())
    for s in starts:
        assert len([x for x in starts if s - 60 < x <= s]) <= 5
    assert starts[-1] >= 180             # 20 calls at 5/min need at least three full minutes


def test_burst_from_threads_is_still_limited():
    lim = RateLimiter({("p", "m"): 5}, window=0.4)
    stamps, lock = [], threading.Lock()

    def worker():
        lim.acquire("p", "m")
        with lock:
            stamps.append(time.monotonic())

    ts = [threading.Thread(target=worker) for _ in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    stamps.sort()
    for s in stamps:
        assert len([x for x in stamps if s - 0.35 < x <= s]) <= 5 + 1   # +1: timer jitter


def test_unlisted_models_are_not_throttled():
    clock = Clock()
    lim = _limiter({("p", "m"): 1}, clock)
    for _ in range(10):
        lim.acquire("p", "other")
    assert clock.sleeps == []


def test_a_429_pauses_every_caller_for_that_model_only():
    clock = Clock()
    lim = _limiter({}, clock)
    lim.penalize("p", "m", 40)
    assert lim.acquire("p", "m") == pytest.approx(40)
    assert lim.acquire("p", "other") == 0


def test_router_penalises_the_model_after_a_rate_limit_failure():
    fake = FakeClient(["!rate_limit"])
    router = ModelRouter(recommend({"gemini"}), {"gemini": "k" * 12}, factory=lambda s, k, m: fake)
    router.config.fallback = None
    clock = Clock()
    router.limiter = _limiter({}, clock)
    router.set_stage("Stage 2 — LLM Wiki")
    router.chat("s", "u")
    spec = router.config.spec_for(router._role)
    assert router.limiter.acquire(spec.provider, spec.model) > 0


def test_router_acquires_a_slot_before_every_call():
    fake = FakeClient(default="ok")
    router = ModelRouter(recommend({"gemini"}), {"gemini": "k" * 12}, factory=lambda s, k, m: fake)
    seen = []
    router.limiter.acquire = lambda p, m: seen.append((p, m)) or 0
    router.set_stage("Stage 2 — LLM Wiki")
    router.chat("s", "u")
    assert len(seen) == 1 and seen[0][0] == "gemini"


def test_same_model_name_gets_different_options_per_provider():
    nemo = "nvidia/nemotron-3.5-super-vl-120b-a12b"
    assert ac.extra_body_for("https://integrate.api.nvidia.com/v1", nemo) == {
        "chat_template_kwargs": {"enable_thinking": False}}
    assert ac.extra_body_for("https://api.groq.com/openai/v1", nemo) is None
    assert ac.extra_body_for("https://generativelanguage.googleapis.com/v1beta/openai/",
                             "gemini-3.6-flash") == {"reasoning_effort": "low"}
    assert ac.extra_body_for("https://integrate.api.nvidia.com/v1", "gemini-3.6-flash") is None


def test_token_boost_is_provider_specific():
    assert token_boost("gemini-3.6-flash", "gemini") == 2.0
    assert token_boost("gemini-3.6-flash", "nvidia") == 1.0
    assert token_boost("openai/gpt-oss-20b", "groq") == 1.0
