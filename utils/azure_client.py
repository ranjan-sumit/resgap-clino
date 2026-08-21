"""
LLM Client — NVIDIA NIM, Master Model: openai/gpt-oss-120b
Used for all 7 main pipeline stages.
LLM Council uses separate per-agent models (see llm_council.py).

All models share the same NVIDIA base URL and API key.
Streaming is used throughout — handles reasoning_content from thinking models.
"""
import base64
import re
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar
from openai import OpenAI

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
MASTER_MODEL    = "openai/gpt-oss-120b"
# B22 fix (2026-08-21): smaller/faster fallback model, tried once after
# MASTER_MODEL's own retries are exhausted, before giving up entirely.
# Not a new, unproven model -- openai/gpt-oss-20b is already one of
# pipeline/llm_council.py's tuned agents against this exact NVIDIA NIM
# endpoint. Real motivation: an isolated evidence-extraction call to
# MASTER_MODEL took 298.7s this session (this file's own retry math
# accounts for that exactly -- 120s timeout x2 attempts + backoff),
# consistent with the NVIDIA API running degraded rather than a code bug.
# A different, smaller model is a genuine independent recovery path in
# that scenario, not just "retry the same slow thing again."
FALLBACK_MODEL  = "openai/gpt-oss-20b"

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


def _collect_stream(stream) -> str:
    """
    Collect streaming response from NVIDIA NIM.
    Skips reasoning_content (chain-of-thought) and returns only final content.
    """
    parts = []
    for chunk in stream:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        content = getattr(delta, "content", None)
        if content:
            parts.append(content)
    return "".join(parts).strip()


def make_nvidia_client(api_key: str) -> OpenAI:
    return OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key)


class AzureOpenAIClient:
    """
    Master pipeline client using openai/gpt-oss-120b via NVIDIA NIM.
    Name kept for backward compatibility — all pipeline imports unchanged.
    """

    def __init__(self, api_key: str, fallback_model: str | None = FALLBACK_MODEL, **kwargs):
        self.client  = make_nvidia_client(api_key)
        self.api_key = api_key
        self.model   = MASTER_MODEL
        # B22 fix: pass fallback_model=None to disable (e.g. a caller that
        # wants strict single-model behavior for reproducibility testing).
        self.fallback_model = fallback_model

    def chat(self, system: str, user: str,
             temperature: float = 0.3, max_tokens: int = 4096,
             _retry: int = 0, _model: str | None = None) -> Result[str]:
        """Streaming chat with timeout and up to two automatic retries on failure.
        B10 fix: previously no timeout — one hung call blocked Streamlit indefinitely.
        B11 fix: previously returned a plain string for both success and failure
        (a sentinel-value anti-pattern) — now returns Success/Failure explicitly.
        B22 fix: after this model's own retries are exhausted on a retryable
        error, try once (no further retries) on self.fallback_model before
        giving up -- see FALLBACK_MODEL's module-level comment for why."""
        import time
        MAX_RETRIES = 2
        TIMEOUT_SECS = 120   # 2 minutes max per call
        model = _model or self.model

        try:
            stream = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                temperature=temperature,
                top_p=1,
                max_tokens=max_tokens,
                stream=True,
                timeout=TIMEOUT_SECS,
            )
            return Success(_collect_stream(stream))
        except Exception as e:
            err = str(e)
            kind = _classify_error(err)
            if _retry < MAX_RETRIES and kind in ("rate_limit", "timeout"):
                wait = 2 ** _retry   # exponential back-off: 1s, 2s
                time.sleep(wait)
                return self.chat(system, user, temperature, max_tokens, _retry=_retry + 1, _model=model)
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
                                  _retry=MAX_RETRIES, _model=self.fallback_model)
            return Failure(ErrorInfo(kind=kind, detail=err))

    def chat_json(self, system: str, user: str, max_tokens: int = 4096) -> Result[str]:
        """Chat that instructs the model to return only valid JSON."""
        system_json = (
            system
            + "\n\nCRITICAL: Your final response must be ONLY valid JSON. "
            "No markdown fences, no preamble, no explanation. "
            "Start directly with { or [ and end with } or ]."
        )
        return self.chat(system_json, user, temperature=0.1, max_tokens=max_tokens)

    def vision(self, system: str, user_text: str,
               image_bytes: bytes, max_tokens: int = 2048, _retry: int = 0) -> Result[str]:
        """Vision call — gpt-oss-120b supports image input. Returns Result[str].
        B22 fix (2026-08-21): previously had zero retries at all (unlike chat()) --
        now gets the same retry-with-backoff treatment. Deliberately NOT given the
        smaller-model fallback chat() has: FALLBACK_MODEL's image-input support
        isn't confirmed, and silently falling back to a model that can't actually
        see the image would produce a wrong-but-successful-looking answer, which
        is worse than a clean Failure -- narrower scope than chat()'s fix,
        on purpose."""
        import time
        MAX_RETRIES = 2
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
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
            return Success(_collect_stream(stream))
        except Exception as e:
            err = str(e)
            kind = _classify_error(err)
            if _retry < MAX_RETRIES and kind in ("rate_limit", "timeout"):
                time.sleep(2 ** _retry)
                return self.vision(system, user_text, image_bytes, max_tokens, _retry=_retry + 1)
            return Failure(ErrorInfo(kind=kind, detail=err))
