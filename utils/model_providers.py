"""
Multi-provider model registry (Clinova model selector, 2026-08-23).

Every provider below exposes an OpenAI-API-compatible `/chat/completions`
endpoint -- confirmed per-provider before being added here, not assumed:
NVIDIA NIM is already in production use throughout this app; OpenAI's API
*is* the reference implementation; Google Gemini documents its own
OpenAI-compatibility layer at the `base_url` below; Qwen's compatibility
layer is Alibaba DashScope's international endpoint. Because all four
speak the same request/response shape, `utils.azure_client.AzureOpenAIClient`
(now `base_url`/`model`-parameterized) covers every one of them -- no
per-provider SDK needed, matching this codebase's established preference
for the smallest change that's honestly correct (same reasoning that kept
`pipeline/relevance_ranking.py` on plain `requests` instead of a vector-DB
client).

`verified_live` is an honest flag, not decoration: `nvidia` (the
pre-existing default, in production) and `gemini` (checked live 2026-10-19,
see its entry) have been exercised against the real API. `openai`/`qwen`
are structurally correct and unit-tested, but nothing here has a real key
to confirm their live behavior (exact error shapes, auth quirks, any per-provider deviation
from strict OpenAI-compatibility) -- do not treat `verified_live=False` as
"probably fine," treat it as "unconfirmed."

DeepSeek and Kimi (Moonshot) are NOT separate providers here -- both are
real NVIDIA NIM models today. Qwen, by contrast, has zero entries in
NVIDIA's live catalog (confirmed directly against `GET /v1/models`, not a
docs page -- see Epic 3.5's RESUME.md note on why that check matters
after three real model-deprecation surprises there) -- it's listed as its
own provider via DashScope instead.

Being IN the `/v1/models` catalog listing turned out not to mean
immediately usable, checked live before trusting it: `deepseek-ai/
deepseek-v4-flash-0731` and `moonshotai/kimi-k3` both returned real
successful completions. `moonshotai/kimi-k2.6` -- also listed in the
catalog -- returned a live 404 ("Function ... Not Found for account ..."),
an entitlement/access gap specific to this account, not a code bug, so
it's deliberately left out of `known_models` rather than listed as
selectable and silently failing. `kimi-k3` needed one real code fix
first: it rejects the standard `top_p=1` with a 400 (its `top_p` is fixed
server-side at 0.95) -- see `_MODEL_TOP_P_OVERRIDES` below and
`utils/azure_client.py`'s now-configurable `top_p` constructor param.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    key: str
    label: str
    base_url: str
    api_key_env: str
    default_model: str
    fallback_model: str | None
    known_models: tuple
    verified_live: bool
    # Model used for image input (figure/table analysis). None = this provider
    # has no known-good vision model here, so the UI hides the option rather
    # than sending an NVIDIA-only model ID to the wrong endpoint.
    vision_model: str | None = None


PROVIDER_REGISTRY = {
    "nvidia": ProviderConfig(
        key="nvidia", label="NVIDIA NIM (current default)",
        base_url="https://integrate.api.nvidia.com/v1", api_key_env="NVIDIA_API_KEY",
        # B28 fix (2026-09-08): openai/gpt-oss-120b reached NVIDIA end-of-life
        # on 2026-09-03 (live HTTP 410 Gone) -- removed from known_models.
        # B29 (2026-09-08): tried swapping to genuinely smaller models
        # (meta/llama-3.2-3b-instruct, ibm/granite-3.0-8b-instruct, plus 6
        # more candidates) -- ALL returned live HTTP 404 "not found for
        # account" on a real chat/completions call, despite some appearing
        # in NVIDIA's /v1/models catalog. This account's real entitlement
        # is a small fixed allowlist; gpt-oss-20b is already the fastest
        # model in it per this codebase's own prior live benchmarking
        # (see utils/azure_client.py's MASTER_MODEL comment). Reverted
        # default_model to gpt-oss-20b; fallback_model is now kimi-k3
        # (live-tested HTTP 200 just now) instead of deepseek-v4-flash-0731
        # (entitled but timed out on a trivial live test call -- kept in
        # known_models as a manually-selectable option, just not the
        # default fallback while it's unreliable).
        default_model="openai/gpt-oss-20b", fallback_model="moonshotai/kimi-k3",
        known_models=(
            "openai/gpt-oss-20b",
            "moonshotai/kimi-k3", "deepseek-ai/deepseek-v4-flash-0731",
            # Added 2026-10-20: 120B vision-language model, answers on this
            # account (13 s for a one-line reply with thinking off). Slow, so
            # it suits council seats, not the call-heavy jobs.
            "nvidia/nemotron-3.5-super-vl-120b-a12b",
        ),
        verified_live=True,
        vision_model="meta/llama-3.2-11b-vision-instruct",
    ),
    "openai": ProviderConfig(
        key="openai", label="OpenAI",
        base_url="https://api.openai.com/v1", api_key_env="OPENAI_API_KEY",
        default_model="gpt-5.6-luna", fallback_model="gpt-5.6-terra",
        known_models=("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"),
        verified_live=False,
    ),
    "gemini": ProviderConfig(
        key="gemini", label="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key_env="GEMINI_API_KEY",
        # flash-lite is the default because it is the model a full 2-paper
        # pipeline run was verified on, and it is fast (one wiki page in ~6s
        # vs ~42s on NVIDIA's gpt-oss-20b). gemini-3.6-flash is the fallback.
        default_model="gemini-3.5-flash-lite", fallback_model="gemini-3.6-flash",
        known_models=("gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash"),
        # Live-checked 2026-10-19 with a real key: /models lists all three IDs,
        # each answered a chat call, a full 2-paper pipeline run completed on
        # gemini-3.5-flash-lite, and image input (vision_model below) described
        # a real PDF page correctly. Google returned a transient 503 "high demand"
        # on gemini-3.6-flash once -- the client's retry/fallback covers that.
        verified_live=True,
        vision_model="gemini-3.6-flash",
    ),
    "groq": ProviderConfig(
        # Groq serves open models behind an OpenAI-compatible API, with very fast
        # inference. Not exercised against the live service yet (no key tested):
        # use "Test models" before relying on it, and "Refresh model list" to see
        # exactly which models your key can use.
        key="groq", label="Groq",
        base_url="https://api.groq.com/openai/v1", api_key_env="GROQ_API_KEY",
        default_model="llama-3.3-70b-versatile", fallback_model=None,
        # From Groq's own model page (2026-10-20), chat models only: no speech
        # (whisper, orpheus) or safety classifiers (prompt-guard, safeguard).
        # Listed prices per 1M tokens, input/output: gpt-oss-20b $0.075/$0.30
        # (1000 tok/s), gpt-oss-120b $0.15/$0.60 (500 tok/s), qwen3.8-27b
        # $0.80/$4.00; the llama, minimax and muse-spark models are "contact sales".
        # minimax-m2.7 and muse-spark-open are preview models (may be withdrawn).
        known_models=("llama-3.3-70b-versatile", "llama-3.1-8b-instant",
                      "openai/gpt-oss-120b", "openai/gpt-oss-20b",
                      "qwen/qwen3.8-27b", "minimaxai/minimax-m2.7", "meta-models/muse-spark-open"),
        verified_live=False,
    ),
    "qwen": ProviderConfig(
        key="qwen", label="Qwen (Alibaba DashScope, international)",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        default_model="qwen3.8-max", fallback_model=None,
        known_models=("qwen3.8-max",),
        verified_live=False,
    ),
}

DEFAULT_PROVIDER_KEY = "nvidia"

# Real, live-confirmed per-model quirk (2026-08-23): moonshotai/kimi-k3
# rejects the standard top_p=1 with a 400 -- its top_p is fixed
# server-side at 0.95. Every other model this app uses accepts 1, so this
# is a narrow, explicit override rather than a new ProviderConfig field
# every provider/model would carry unused.
_MODEL_TOP_P_OVERRIDES = {
    "moonshotai/kimi-k3": 0.95,
}


# Documented request-per-minute limits of models known to be tight (free tier).
# Anything not listed is not throttled; the router still honours Retry-After.
# Keyed by (provider, model).
MODEL_RPM_LIMITS = {
    ("gemini", "gemini-3.6-flash"): 5,
}


def get_provider(provider_key: str) -> ProviderConfig:
    if provider_key not in PROVIDER_REGISTRY:
        raise ValueError(
            f"Unknown model provider '{provider_key}'. Known providers: "
            f"{', '.join(PROVIDER_REGISTRY)}."
        )
    return PROVIDER_REGISTRY[provider_key]


def build_client(provider_key: str, api_key: str, model: str = None, token_meter=None):
    """Returns a configured AzureOpenAIClient for the given provider/model
    -- the one factory app.py's three client-construction sites should
    call instead of constructing AzureOpenAIClient directly, so a model
    selection actually takes effect everywhere a run uses the LLM.
    `model=None` uses the provider's own default_model (NVIDIA's current
    gpt-oss-20b when provider_key="nvidia", preserving today's behavior
    exactly). `token_meter` (Clinova Phase 4, Epic 4.3 token
    instrumentation) is optional and additive -- omitting it keeps every
    existing caller's behavior unchanged."""
    # Local import -- avoids a circular import (azure_client.py doesn't
    # need to know about model_providers.py, only the reverse).
    from utils.azure_client import AzureOpenAIClient

    cfg = get_provider(provider_key)
    resolved_model = model or cfg.default_model
    return AzureOpenAIClient(
        api_key=api_key,
        base_url=cfg.base_url,
        model=resolved_model,
        fallback_model=cfg.fallback_model,
        top_p=_MODEL_TOP_P_OVERRIDES.get(resolved_model, 1.0),
        token_meter=token_meter,
        vision_model=cfg.vision_model,
    )
