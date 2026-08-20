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

    def __init__(self, api_key: str, **kwargs):
        self.client  = make_nvidia_client(api_key)
        self.api_key = api_key
        self.model   = MASTER_MODEL

    def chat(self, system: str, user: str,
             temperature: float = 0.3, max_tokens: int = 4096,
             _retry: int = 0) -> Result[str]:
        """Streaming chat with timeout and up to two automatic retries on failure.
        B10 fix: previously no timeout — one hung call blocked Streamlit indefinitely.
        B11 fix: previously returned a plain string for both success and failure
        (a sentinel-value anti-pattern) — now returns Success/Failure explicitly."""
        import time
        MAX_RETRIES = 2
        TIMEOUT_SECS = 120   # 2 minutes max per call

        try:
            stream = self.client.chat.completions.create(
                model=self.model,
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
                return self.chat(system, user, temperature, max_tokens, _retry=_retry + 1)
            # Non-retryable or exhausted retries.
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
               image_bytes: bytes, max_tokens: int = 2048) -> Result[str]:
        """Vision call — gpt-oss-120b supports image input. Returns Result[str];
        no retry logic here (unlike chat()), but error.kind is still classified via
        _classify_error() since a vision call can genuinely time out or be rate-limited."""
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
            )
            return Success(_collect_stream(stream))
        except Exception as e:
            err = str(e)
            return Failure(ErrorInfo(kind=_classify_error(err), detail=err))
