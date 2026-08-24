"""
LLM Client — NVIDIA NIM, Master Model: openai/gpt-oss-20b
Used for all 7 main pipeline stages.
LLM Council uses separate per-agent models (see llm_council.py) -- that
file hardcodes its own model strings for each council seat independently
and is unaffected by which model this file calls "master".

All models share the same NVIDIA base URL and API key.
Streaming is used throughout — handles reasoning_content from thinking models.
"""
import base64
import re
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar
from openai import OpenAI

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
# B25 fix (2026-08-22): swapped master/fallback roles. Measured live,
# repeatedly, against this exact NVIDIA endpoint this session:
# gpt-oss-20b was faster than gpt-oss-120b on every single test run --
# from ~20-150x faster on trivial completions to ~1.5x faster on the
# heaviest real call in this pipeline (knowledge-graph extraction: 232s
# vs 344s for an equivalent, equally-successful real extraction against
# the same corpus, both non-fallback). gpt-oss-120b was never observed to
# be faster in any measurement. 20b is now the default MASTER_MODEL;
# 120b becomes the fallback -- a genuinely higher-capacity model to fall
# back to (rather than a smaller one), for the rare case 20b itself
# repeatedly fails on a rate_limit/timeout.
MASTER_MODEL    = "openai/gpt-oss-20b"
FALLBACK_MODEL  = "openai/gpt-oss-120b"
# B26 fix (2026-08-22): was "openai/gpt-oss-120b" -- live-tested with a
# real image and it explicitly replied "I can't see an image," not a wrong
# guess, an outright claim of receiving none. None of the gpt-oss models
# are actually vision-capable on NVIDIA NIM; pipeline/pdf_parser.py's own
# leftover "GPT-4o Vision" comment on the call site was the clue this had
# never been re-validated after moving off whatever provider that
# originally referred to. meta/llama-3.2-11b-vision-instruct is NVIDIA's
# actual hosted VLM on this same integrate.api.nvidia.com endpoint, same
# OpenAI-compatible image_url/base64-data-URI format this file already
# sends -- live-verified: correctly identified a real test image's color
# in 4.8s.
#
# B25 fix: vision() is deliberately NOT tied to MASTER_MODEL -- it's a
# separate capability decision (confirmed image-input support) from "which
# model is fastest at text reasoning," and coupling them meant a master-
# model swap for speed would silently change vision()'s model too.
VISION_MODEL    = "meta/llama-3.2-11b-vision-instruct"

T = TypeVar("T")


@dataclass(frozen=True)
class ErrorInfo:
    kind: Literal["timeout", "rate_limit", "api_error"]
    detail: str


@dataclass(frozen=True)
class Success(Generic[T]):
    value: T


@dataclass(frozen=True)
class Failure:
    error: ErrorInfo


# B11 fix: Result has exactly one free type parameter (Failure always wraps
# ErrorInfo, it isn't generic) — annotate as Result[str], never Result[str, ErrorInfo].
Result = Success[T] | Failure


class LLMCallError(Exception):
    """B12 fix: raised by unwrap() on a Failure so callers can no longer mistake
    a failed LLM call for real content (see Story 1.2 / AD-4)."""

    def __init__(self, error: ErrorInfo):
        self.error = error
        super().__init__(f"LLM call failed [{error.kind}]: {error.detail}")


def unwrap(result: "Result[T]") -> T:
    """Single, shared way to consume a Result: return the value on Success,
    raise LLMCallError on Failure. Avoids every caller re-implementing this
    isinstance check (see Story 1.1's review finding on duplicated logic)."""
    if isinstance(result, Success):
        return result.value
    raise LLMCallError(result.error)


def _classify_error(err: str) -> Literal["timeout", "rate_limit", "api_error"]:
    """Priority order: rate_limit, then timeout, then api_error — first match wins.
    Single source of truth for both chat()'s retry-eligibility check and error.kind
    labeling — do not reimplement this matching separately (review finding, 2026-08-01)."""
    low = err.lower()
    if "429" in err or re.search(r"rate.?limit", low):
        return "rate_limit"
    if "timeout" in low or "timed out" in low:
        return "timeout"
    return "api_error"


def _collect_stream(stream, deadline: float = None, usage_sink: dict = None) -> str:
    """
    Collect streaming response from NVIDIA NIM.
    Skips reasoning_content (chain-of-thought) and returns only final content.

    `deadline` (a time.monotonic() value, Epic 3.6) is checked between
    chunks and raises TimeoutError if exceeded. Real bug found live
    (2026-08-22): the openai SDK's `timeout=` kwarg passed to
    `.create()` does NOT reliably bound TOTAL streaming duration -- a
    real call made with `timeout_seconds=1` completed successfully in
    47.3s, because NVIDIA NIM keeps sending periodic chunks that each
    individually complete well under httpx's own per-read timeout, even
    though the cumulative stream takes far longer. This loop-level
    wall-clock check is what makes AgentConfig's `timeout_seconds`
    (pipeline/agent_config.py) a real, enforced bound instead of a
    parameter that gets silently ignored for streaming responses.

    `usage_sink` (Clinova Phase 4, Epic 4.3 token instrumentation,
    2026-08-24): an optional dict this function fills in place with
    {"prompt_tokens", "completion_tokens", "total_tokens"} if the stream
    carries a usage-bearing chunk (only sent when the caller requested
    stream_options={"include_usage": True} -- see chat()). That chunk is
    the OpenAI streaming protocol's terminal chunk and carries an empty
    `choices` list, so this check runs BEFORE the existing
    `if not chunk.choices: continue` skip below, which would otherwise
    silently discard it."""
    import time
    parts = []
    for chunk in stream:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("Stream exceeded its timeout mid-read (deadline check, not the SDK's own timeout=)")
        usage = getattr(chunk, "usage", None)
        if usage is not None and usage_sink is not None:
            usage_sink["prompt_tokens"] = getattr(usage, "prompt_tokens", None)
            usage_sink["completion_tokens"] = getattr(usage, "completion_tokens", None)
            usage_sink["total_tokens"] = getattr(usage, "total_tokens", None)
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        content = getattr(delta, "content", None)
        if content:
            parts.append(content)
    return "".join(parts).strip()


# Clinova Phase 4, Epic 4.3 token instrumentation (2026-08-24): per-base_url
# cache of whether stream_options={"include_usage": True} is actually
# accepted by that provider -- probed lazily, only when a caller supplies a
# TokenMeter (utils/token_meter.py), so this has zero effect on any
# existing caller. A provider that rejects it degrades to token_usage=None
# for that call, never a fabricated/estimated count, matching this
# codebase's existing honest-None convention (see app.py's own comment on
# why token_usage was NULL before this instrumentation existed).
_STREAM_OPTIONS_SUPPORT: dict = {}


def _stream_options_error(err: str) -> bool:
    low = err.lower()
    return "stream_options" in low or "include_usage" in low


def make_nvidia_client(api_key: str) -> OpenAI:
    return OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key)


class AzureOpenAIClient:
    """
    Master pipeline client, defaulting to openai/gpt-oss-20b via NVIDIA NIM
    with openai/gpt-oss-120b as the one-shot fallback on a retryable
    failure (see MASTER_MODEL/FALLBACK_MODEL above -- B25 swapped which
    model plays which role, 2026-08-22).
    Name kept for backward compatibility — all pipeline imports unchanged.

    Model-selector feature (2026-08-23): `base_url`/`model` are now real
    constructor overrides, not hardcoded -- every provider in
    utils/model_providers.py's registry speaks the same OpenAI-API-
    compatible /chat/completions shape (confirmed per-provider, not
    assumed), so this one class covers all of them. Omitting both keeps
    the exact prior NVIDIA defaults -- every existing caller's behavior is
    unchanged."""

    # Sentinel so __init__ can tell "caller didn't pass fallback_model" apart
    # from "caller explicitly passed FALLBACK_MODEL" -- needed because the
    # right default depends on `base_url` (see below), not a single constant.
    _FALLBACK_UNSET = object()

    def __init__(self, api_key: str, fallback_model=_FALLBACK_UNSET,
                 base_url: str = NVIDIA_BASE_URL, model: str = MASTER_MODEL,
                 top_p: float = 1.0, token_meter=None, **kwargs):
        # NVIDIA (the default) still goes through make_nvidia_client() --
        # unchanged code path, same mockable seam existing tests rely on.
        # A different base_url (another provider) builds a plain OpenAI
        # client directly against it.
        self.client  = make_nvidia_client(api_key) if base_url == NVIDIA_BASE_URL \
            else OpenAI(base_url=base_url, api_key=api_key)
        self.api_key = api_key
        self.model   = model
        # Real bug found live (2026-08-23): moonshotai/kimi-k3 (NVIDIA NIM)
        # rejects the previously-hardcoded top_p=1 with a 400 -- that
        # model's top_p is fixed at 0.95 server-side. top_p is otherwise a
        # per-model quirk, not a per-provider one (every other model this
        # app uses accepts 1), so it's a constructor override here, not a
        # new field on utils.model_providers.ProviderConfig.
        self.top_p = top_p
        # B22 fix: pass fallback_model=None to disable (e.g. a caller that
        # wants strict single-model behavior for reproducibility testing).
        # If the caller didn't pass anything, default to FALLBACK_MODEL only
        # for the NVIDIA base_url (its correct historical behavior) -- for
        # any other provider, FALLBACK_MODEL ("openai/gpt-oss-120b") would
        # be a meaningless model string from the wrong catalog, so None.
        if fallback_model is self._FALLBACK_UNSET:
            self.fallback_model = FALLBACK_MODEL if base_url == NVIDIA_BASE_URL else None
        else:
            self.fallback_model = fallback_model
        # Clinova Phase 4, Epic 4.3 token instrumentation (2026-08-24):
        # optional, additive -- every existing caller that doesn't pass
        # token_meter gets byte-identical behavior to before this feature
        # existed (no stream_options requested, no usage capture attempted).
        self.token_meter = token_meter
        self.current_stage = None
        self._base_url = base_url

    def set_stage(self, stage: str) -> None:
        """Clinova Phase 4, Epic 4.3: callers (app.py) set this around each
        pipeline stage so TokenMeter.record() can attribute usage to a real
        stage name -- purely for the by_stage breakdown, never required for
        the client to function."""
        self.current_stage = stage

    def chat(self, system: str, user: str,
             temperature: float = 0.3, max_tokens: int = 4096,
             timeout_seconds: int = None, max_retries: int = None,
             _retry: int = 0, _model: str | None = None) -> Result[str]:
        """Streaming chat with timeout and up to two automatic retries on failure.
        B10 fix: previously no timeout — one hung call blocked Streamlit indefinitely.
        B11 fix: previously returned a plain string for both success and failure
        (a sentinel-value anti-pattern) — now returns Success/Failure explicitly.
        B22 fix: after this model's own retries are exhausted on a retryable
        error, try once (no further retries) on self.fallback_model before
        giving up -- see FALLBACK_MODEL's module-level comment for why.

        Epic 3.6 (2026-08-22): `timeout_seconds`/`max_retries` are now real
        per-call overrides (previously hardcoded module constants every
        caller shared identically) -- this is what makes AgentConfig's
        `timeout_seconds`/`max_requests` fields (pipeline/agent_config.py)
        genuinely enforceable per agent role, not just documented. Omitting
        either keeps the exact prior defaults (120s, 2 retries), so every
        existing caller's behavior is unchanged."""
        import time
        MAX_RETRIES = max_retries if max_retries is not None else 2
        TIMEOUT_SECS = timeout_seconds if timeout_seconds is not None else 120   # 2 minutes max per call, unless overridden
        model = _model or self.model

        # Clinova Phase 4, Epic 4.3 token instrumentation (2026-08-24): only
        # requested when a caller supplied a TokenMeter -- every existing
        # caller (token_meter=None) sends the exact same request as before
        # this feature existed. _STREAM_OPTIONS_SUPPORT.get(..., True)
        # means "try it" until a real provider response says otherwise.
        want_usage = self.token_meter is not None and _STREAM_OPTIONS_SUPPORT.get(self._base_url, True)
        create_kwargs = dict(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            temperature=temperature,
            top_p=self.top_p,
            max_tokens=max_tokens,
            stream=True,
            timeout=TIMEOUT_SECS,
        )
        if want_usage:
            create_kwargs["stream_options"] = {"include_usage": True}

        try:
            stream = self.client.chat.completions.create(**create_kwargs)
            # See _collect_stream()'s docstring: the SDK's own `timeout=`
            # above does not reliably bound total streaming duration, so
            # a real wall-clock deadline is enforced across the read loop.
            deadline = time.monotonic() + TIMEOUT_SECS
            usage_sink = {} if want_usage else None
            content = _collect_stream(stream, deadline=deadline, usage_sink=usage_sink)
            if want_usage:
                _STREAM_OPTIONS_SUPPORT.setdefault(self._base_url, True)
                if usage_sink and self.token_meter is not None:
                    self.token_meter.record(stage=self.current_stage, model=model, usage=usage_sink)
            return Success(content)
        except Exception as e:
            err = str(e)
            kind = _classify_error(err)
            # This provider rejected stream_options -- degrade once (never
            # counted against MAX_RETRIES, since it isn't a transient
            # failure) and remember for every future call to this base_url.
            # token_usage simply stays None for this call, never estimated.
            if want_usage and _stream_options_error(err) and self._base_url not in _STREAM_OPTIONS_SUPPORT:
                _STREAM_OPTIONS_SUPPORT[self._base_url] = False
                return self.chat(system, user, temperature, max_tokens,
                                  timeout_seconds=timeout_seconds, max_retries=max_retries,
                                  _retry=_retry, _model=_model)
            if _retry < MAX_RETRIES and kind in ("rate_limit", "timeout"):
                wait = 2 ** _retry   # exponential back-off: 1s, 2s
                time.sleep(wait)
                return self.chat(system, user, temperature, max_tokens,
                                  timeout_seconds=timeout_seconds, max_retries=max_retries,
                                  _retry=_retry + 1, _model=model)
            # Retries on `model` are exhausted. If this was the primary
            # model failing with a retryable-class error, try exactly once
            # (no further retries -- _retry=MAX_RETRIES makes the recursive
            # call's own retry check false, and model != self.model makes
            # this fallback branch false too, so it can't loop) on the
            # smaller/faster fallback model before giving up entirely. An
            # api_error (not rate_limit/timeout) skips the fallback and
            # fails fast as before -- switching models is unlikely to fix
            # a genuine API/auth/malformed-request error.
            if model == self.model and self.fallback_model and kind in ("rate_limit", "timeout"):
                return self.chat(system, user, temperature, max_tokens,
                                  timeout_seconds=timeout_seconds, max_retries=max_retries,
                                  _retry=MAX_RETRIES, _model=self.fallback_model)
            return Failure(ErrorInfo(kind=kind, detail=err))

    def chat_json(self, system: str, user: str, max_tokens: int = 4096,
                  timeout_seconds: int = None, max_retries: int = None) -> Result[str]:
        """Chat that instructs the model to return only valid JSON."""
        system_json = (
            system
            + "\n\nCRITICAL: Your final response must be ONLY valid JSON. "
            "No markdown fences, no preamble, no explanation. "
            "Start directly with { or [ and end with } or ]."
        )
        return self.chat(system_json, user, temperature=0.1, max_tokens=max_tokens,
                          timeout_seconds=timeout_seconds, max_retries=max_retries)

    def vision(self, system: str, user_text: str,
               image_bytes: bytes, max_tokens: int = 2048, _retry: int = 0) -> Result[str]:
        """Vision call — see VISION_MODEL's module-level comment (B26) for
        which model actually supports image input on NVIDIA NIM and why.
        Returns Result[str].
        B22 fix (2026-08-21): previously had zero retries at all (unlike chat()) --
        now gets the same retry-with-backoff treatment.
        B25 fix (2026-08-22): always uses VISION_MODEL, deliberately NOT
        self.model -- previously used self.model, coupling vision's model
        choice to whichever model happened to be MASTER_MODEL for
        unrelated text-reasoning reasons. That coupling is exactly what
        let B26's bug go unnoticed: MASTER_MODEL was assumed, never
        confirmed, to support images. Vision's model choice is now a
        genuinely independent decision (VISION_MODEL), so a future
        master-model swap for text speed can't silently change it again.
        Still no model fallback within vision() itself: a second
        unconfirmed model is no better than the first."""
        import time
        MAX_RETRIES = 2
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        try:
            stream = self.client.chat.completions.create(
                model=VISION_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text",      "text": user_text},
                            {"type": "image_url", "image_url": {
                                "url": f"data:image/png;base64,{b64}"
                            }},
                        ],
                    },
                ],
                temperature=0.1,
                top_p=1,
                max_tokens=max_tokens,
                stream=True,
                timeout=120,
            )
            # Same real-wall-clock-deadline fix as chat() -- see
            # _collect_stream()'s docstring.
            deadline = time.monotonic() + 120
            return Success(_collect_stream(stream, deadline=deadline))
        except Exception as e:
            err = str(e)
            kind = _classify_error(err)
            if _retry < MAX_RETRIES and kind in ("rate_limit", "timeout"):
                time.sleep(2 ** _retry)
                return self.vision(system, user_text, image_bytes, max_tokens, _retry=_retry + 1)
            return Failure(ErrorInfo(kind=kind, detail=err))
