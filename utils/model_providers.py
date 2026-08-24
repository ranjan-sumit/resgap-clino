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

`verified_live` is an honest flag, not decoration: only `nvidia` has been
exercised against the real API this session (it's the pre-existing
default, already in production). `openai`/`gemini`/`qwen` are structurally
correct and unit-tested, but nothing here has a real key to confirm their
live behavior (exact error shapes, auth quirks, any per-provider deviation
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


PROVIDER_REGISTRY = {
    "nvidia": ProviderConfig(
        key="nvidia", label="NVIDIA NIM (current default)",
        base_url="https://integrate.api.nvidia.com/v1", api_key_env="NVIDIA_API_KEY",
        default_model="openai/gpt-oss-20b", fallback_model="openai/gpt-oss-120b",
        known_models=(
            "openai/gpt-oss-20b", "openai/gpt-oss-120b",
            "deepseek-ai/deepseek-v4-flash-0731", "moonshotai/kimi-k3",
        ),
        verified_live=True,
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
        default_model="gemini-3.6-flash", fallback_model="gemini-3.5-flash-lite",
        known_models=("gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"),
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
    )
