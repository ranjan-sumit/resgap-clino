"""
Per-role model routing.

The pipeline has several kinds of LLM work, and one model rarely suits all of
them. Each kind is a ROLE with its own provider + model:

    extraction  pulls details out of papers: reference parsing/enrichment and
                evidence extraction (Stages 1B, 2C), parameter extraction (Lab)
    wiki        compiles each paper's wiki page, cross-links, and the knowledge
                graph (Stages 2, 3)
    analysis    finds and judges gaps and writes proposals (Stages 4, 5, 5b, 6)
    council_*   the Computational Lab's council: three seats and a chair
    fallback    (not a role) the model used when a role's own model fails

Every provider speaks the OpenAI chat format, so a ModelSpec is just
(provider, model) -- plus a base URL for the "custom" provider, which is any
OpenAI-compatible endpoint. Adding a provider is a registry entry, not code.

ModelRouter stands in for the single client the pipeline used to take: it has
the same chat / chat_json / vision / set_stage methods. The pipeline already
calls set_stage("Stage 2 — LLM Wiki") etc. before each step, so the router
picks the role from that and none of the stage code changes.

Fallback is cross-provider and explicit: if a role's model fails, the same call
is retried once on the fallback model (a different provider is best, so one
outage does not take both down). Each switch is recorded in `fallback_events`.
"""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests

from utils.azure_client import AzureOpenAIClient, ErrorInfo, Failure, Success, _retry_after_seconds
from utils.model_providers import MODEL_RPM_LIMITS, PROVIDER_REGISTRY, _MODEL_TOP_P_OVERRIDES, get_provider
from utils.rate_limiter import RateLimiter
from utils.text_hygiene import guard_system

CUSTOM_PROVIDER = "custom"

ROLE_EXTRACTION = "extraction"
ROLE_WIKI = "wiki"
ROLE_ANALYSIS = "analysis"
ROLE_COUNCIL_A = "council_a"
ROLE_COUNCIL_B = "council_b"
ROLE_COUNCIL_C = "council_c"
ROLE_COUNCIL_CHAIR = "council_chair"

MAIN_ROLES = (ROLE_EXTRACTION, ROLE_WIKI, ROLE_ANALYSIS)
COUNCIL_ROLES = (ROLE_COUNCIL_A, ROLE_COUNCIL_B, ROLE_COUNCIL_C, ROLE_COUNCIL_CHAIR)
ALL_ROLES = MAIN_ROLES + COUNCIL_ROLES

ROLE_LABELS = {
    ROLE_EXTRACTION: "Extraction",
    ROLE_WIKI: "Wiki & graph",
    ROLE_ANALYSIS: "Analysis",
    ROLE_COUNCIL_A: "Council seat 1",
    ROLE_COUNCIL_B: "Council seat 2",
    ROLE_COUNCIL_C: "Council seat 3",
    ROLE_COUNCIL_CHAIR: "Council chair",
}
ROLE_HELP = {
    ROLE_EXTRACTION: "Pulls details out of the papers: parses and enriches references and extracts evidence "
                     "(and parameters in the Computational Lab). Many small, structured calls: speed matters most.",
    ROLE_WIKI: "Compiles each paper into a structured wiki page, links the papers, and builds the knowledge graph. "
               "Long structured JSON output: it must follow the format reliably.",
    ROLE_ANALYSIS: "Finds research gaps, judges them against the literature, and writes proposals. "
                   "This is where reasoning quality matters most.",
    ROLE_COUNCIL_A: "First council member in the Computational Lab (Biostatistician / Clinician).",
    ROLE_COUNCIL_B: "Second council member (Epidemiologist / Researcher).",
    ROLE_COUNCIL_C: "Third council member (Analyst / Critic).",
    ROLE_COUNCIL_CHAIR: "Chairs the council: weighs the members' views, writes the consensus and final decision.",
}

# First matching prefix wins, so the more specific "Stage 2C" precedes "Stage 2".
_STAGE_ROLES = (
    ("Stage 1B", ROLE_EXTRACTION),
    ("Stage 2C", ROLE_EXTRACTION),
    ("Stage 2", ROLE_WIKI),
    ("Stage 3", ROLE_WIKI),
    ("Stage 4c", ROLE_COUNCIL_CHAIR),  # the gap critic: a few high-stakes judgements, so the stronger model
    ("Stage 4", ROLE_ANALYSIS),
    ("Stage 5", ROLE_ANALYSIS),       # includes 5b, the Gap Challenger judge
    ("Stage 6b", ROLE_COUNCIL_CHAIR),  # the proposal reviewer
    ("Stage 6", ROLE_ANALYSIS),
    ("Lab — Parameter", ROLE_EXTRACTION),
    ("Lab", ROLE_ANALYSIS),
)

# Council seats are keyed in pipeline/llm_council.py by the model_key each agent
# was originally written against; this maps those keys to the configurable roles.
COUNCIL_KEY_ROLE = {
    "gpt_20b": ROLE_COUNCIL_A,
    "llama_3b": ROLE_COUNCIL_B,
    "nemotron": ROLE_COUNCIL_C,
    "gpt_120b": ROLE_COUNCIL_CHAIR,
}

# "Thinking" models spend part of max_tokens on hidden reasoning, so the same
# limit that is plenty for a plain model can truncate their JSON mid-object.
# Measured on gemini-3.6-flash: extra headroom alone still left 2 of 6 wiki
# calls broken; the real fix is the low reasoning effort sent in
# utils/azure_client._MODEL_EXTRA_BODY (7 of 7 valid, 5-7 s). The headroom stays
# as cheap insurance for the occasional long reasoning chain.
_TOKEN_BOOST = {("gemini", "gemini-3.6-flash"): 2.0, ("gemini", "gemini-3.7-flash"): 2.0}


def token_boost(model: str, provider: str = "gemini") -> float:
    """Output-token headroom for a model on a provider (keyed by both, so the same
    model name elsewhere does not inherit it). `provider` defaults to Gemini, the
    only provider with entries today."""
    return _TOKEN_BOOST.get((provider, model), 1.0)


def role_for_stage(stage: str) -> str:
    for prefix, role in _STAGE_ROLES:
        if (stage or "").startswith(prefix):
            return role
    return ROLE_ANALYSIS


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    base_url: str = ""          # only for the custom provider

    @property
    def provider_label(self) -> str:
        if self.provider == CUSTOM_PROVIDER:
            return "Custom endpoint"
        cfg = PROVIDER_REGISTRY.get(self.provider)
        return cfg.label.split(" (")[0] if cfg else self.provider

    @property
    def label(self) -> str:
        return f"{self.provider_label} · {self.model}"

    def to_dict(self) -> dict:
        d = {"provider": self.provider, "model": self.model}
        if self.base_url:
            d["base_url"] = self.base_url
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ModelSpec":
        provider = str(d.get("provider", ""))
        if provider != CUSTOM_PROVIDER and provider not in PROVIDER_REGISTRY:
            raise ValueError(f"Unknown provider: {provider!r}")
        model = str(d.get("model", "")).strip()
        if not model:
            raise ValueError("A model name is required.")
        return cls(provider, model, str(d.get("base_url", "") or "").strip())


@dataclass
class ModelConfig:
    roles: dict                     # role -> ModelSpec
    fallback: ModelSpec | None = None

    def spec_for(self, role: str) -> ModelSpec:
        """A council role that was never set follows the analysis model."""
        return self.roles.get(role) or self.roles[ROLE_ANALYSIS]

    def distinct_specs(self) -> list:
        seen, out = set(), []
        for role in ALL_ROLES:
            spec = self.roles.get(role)
            if spec and spec not in seen:
                seen.add(spec); out.append(spec)
        if self.fallback and self.fallback not in seen:
            out.append(self.fallback)
        return out

    def to_dict(self) -> dict:
        return {"roles": {r: s.to_dict() for r, s in self.roles.items()},
                "fallback": self.fallback.to_dict() if self.fallback else None}

    @classmethod
    def from_dict(cls, d: dict) -> "ModelConfig":
        roles = {r: ModelSpec.from_dict(s) for r, s in (d.get("roles") or {}).items() if r in ALL_ROLES}
        for needed in MAIN_ROLES:
            if needed not in roles:
                raise ValueError(f"Missing model for role {needed!r}")
        fb = d.get("fallback")
        return cls(roles, ModelSpec.from_dict(fb) if fb else None)


def can_read_images(spec: ModelSpec) -> bool:
    """Whether the provider has a known-good vision model (the custom endpoint
    has none, since nothing is known about it)."""
    cfg = PROVIDER_REGISTRY.get(spec.provider)
    return bool(cfg and cfg.vision_model)


def key_for(spec: ModelSpec, keys: dict) -> str:
    return (keys.get(spec.provider) or "").strip()


def build_spec_client(spec: ModelSpec, api_key: str, token_meter=None) -> AzureOpenAIClient:
    """A client for one (provider, model). No same-provider fallback here: the
    router owns fallback, and a provider's built-in fallback model may be retired."""
    if spec.provider == CUSTOM_PROVIDER:
        return AzureOpenAIClient(api_key=api_key, base_url=spec.base_url, model=spec.model,
                                 fallback_model=None, token_meter=token_meter, vision_model=None)
    cfg = PROVIDER_REGISTRY[spec.provider]
    return AzureOpenAIClient(
        api_key=api_key, base_url=cfg.base_url, model=spec.model, fallback_model=None,
        top_p=_MODEL_TOP_P_OVERRIDES.get(spec.model, 1.0), token_meter=token_meter,
        vision_model=cfg.vision_model,
    )


class ModelRouter:
    """Drop-in replacement for AzureOpenAIClient that routes by pipeline stage."""

    def __init__(self, config: ModelConfig, keys: dict, token_meter=None, factory=build_spec_client):
        self.config = config
        self.keys = dict(keys)
        self.token_meter = token_meter
        self._factory = factory
        self._clients: dict = {}
        self._lock = threading.Lock()
        self._role = ROLE_ANALYSIS
        self.current_stage = None
        self.fallback_events: list = []
        self.call_log = None            # a utils.call_log.CallLog, set by the pipeline
        self.limiter = RateLimiter(MODEL_RPM_LIMITS)   # shared by every thread using this router
        self.budget = None              # a utils.cost_guard.TokenBudget, set by the pipeline

    # -- clients ---------------------------------------------------------------
    def client_for(self, spec: ModelSpec):
        with self._lock:
            if spec not in self._clients:
                self._clients[spec] = self._factory(spec, key_for(spec, self.keys), self.token_meter)
            return self._clients[spec]

    def _role_client(self, role: str):
        return self.client_for(self.config.spec_for(role))

    # -- the client interface the pipeline uses ----------------------------------
    def set_stage(self, stage: str) -> None:
        self.current_stage = stage
        self._role = role_for_stage(stage)
        self._role_client(self._role).set_stage(stage)

    @property
    def model(self) -> str:
        return self.config.spec_for(self._role).model

    def cache_tag(self) -> str:
        """The provider and model that answer for the current stage; part of every cached result's key."""
        spec = self.config.spec_for(self._role)
        return f"{spec.provider}:{spec.model}"

    @property
    def api_key(self) -> str:
        return key_for(self.config.spec_for(ROLE_ANALYSIS), self.keys)

    def chat(self, system: str, user: str, temperature: float = 0.3, max_tokens: int = 4096,
             timeout_seconds: int = None, max_retries: int = None) -> object:
        return self._call(self._role, "chat", system, user, temperature=temperature,
                          max_tokens=max_tokens, timeout_seconds=timeout_seconds, max_retries=max_retries)

    def chat_json(self, system: str, user: str, max_tokens: int = 4096,
                  timeout_seconds: int = None, max_retries: int = None) -> object:
        return self._call(self._role, "chat_json", system, user,
                          max_tokens=max_tokens, timeout_seconds=timeout_seconds, max_retries=max_retries)

    def vision(self, system: str, user_text: str, image_bytes: bytes, max_tokens: int = 2048) -> object:
        """Reads the image with the first of (current role, analysis, fallback) whose
        model can read images, moving on to the next one when a call fails (a hung
        or rate-limited vision endpoint must not decide the whole run). If that
        still fails, a Gemini key (verified for images, fast) is tried last."""
        candidates = [self.config.spec_for(self._role), self.config.spec_for(ROLE_ANALYSIS), self.config.fallback]
        if self.keys.get("gemini"):
            candidates.append(ModelSpec("gemini", get_provider("gemini").default_model))
        tried, last = set(), None
        system = guard_system(system)                         # paper text in an image is data, like text
        # A provider that timed out on an earlier page of this run is skipped
        # (each hung call costs the full wait), unless nothing else is left.
        hung = getattr(self, "_vision_hung", None)
        if hung is None:
            hung = self._vision_hung = set()
        candidates = [s for s in candidates if s is None or s.provider not in hung] or candidates
        for spec in candidates:
            if spec is None or spec.provider in tried:
                continue
            client = self.client_for(spec)
            if not getattr(client, "vision_model", None):
                continue
            tried.add(spec.provider)
            client.set_stage(self.current_stage)
            if self.budget is not None:
                self.budget.check()                           # over the cap: no further spend
            self.limiter.acquire(spec.provider, spec.model)
            started = time.time()
            result = client.vision(system, user_text, image_bytes, max_tokens=max_tokens)
            if not isinstance(result, Failure):
                if self.budget is not None:
                    self.budget.add(self.budget.tokens_of(system, user_text, str(result.value or "")) + VISION_IMAGE_TOKENS)
                self._log(spec, "vision", system, user_text, started, True)
                return result
            self._log(spec, "vision", system, user_text, started, False, result.error.kind, result.error.detail)
            if result.error.kind == "timeout":
                hung.add(spec.provider)
            last = result
        return last or Failure(ErrorInfo(
            kind="unsupported",
            detail="None of the selected models can read images (extraction, analysis, fallback)."))

    # -- routing + cross-provider fallback ---------------------------------------
    def _invoke(self, client, spec: ModelSpec, method: str, system: str, user: str, kwargs: dict):
        kwargs = dict(kwargs)
        kwargs["max_tokens"] = int(kwargs["max_tokens"] * token_boost(spec.model, spec.provider))
        system = guard_system(system)                 # every prompt says paper text is data, never instructions
        client.set_stage(self.current_stage)
        if self.budget is not None:
            self.budget.check()          # over the cap: no further spend
        self.limiter.acquire(spec.provider, spec.model)
        started = time.time()
        try:
            result = getattr(client, method)(system, user, **kwargs)
        except Exception as e:
            self._log(spec, method, system, user, started, False, "exception", f"{type(e).__name__}: {e}")
            raise
        if self.budget is not None:
            self.budget.add(self.budget.tokens_of(system, user, str(result.value or "") if isinstance(result, Success) else ""))
        if isinstance(result, Success):
            self._log(spec, method, system, user, started, True, response_chars=len(str(result.value or "")))
        else:
            self._log(spec, method, system, user, started, False, result.error.kind, result.error.detail)
            if result.error.kind == "rate_limit":
                # One caller hitting a quota means every caller should back off.
                self.limiter.penalize(spec.provider, spec.model,
                                      _retry_after_seconds(result.error.detail) or 15.0)
        return result

    def _log(self, spec, method, system, user, started, ok, kind="", detail="", response_chars=0):
        log = self.call_log
        if log is not None:
            log.record(stage=self.current_stage, provider=spec.provider, model=spec.model, method=method,
                       system=system, user=user, started=started, ok=ok, error_kind=kind,
                       error_detail=detail, response_chars=response_chars)

    def _call(self, role: str, method: str, system: str, user: str, **kwargs):
        spec = self.config.spec_for(role)
        result = self._invoke(self.client_for(spec), spec, method, system, user, kwargs)
        if isinstance(result, Success) or self.config.fallback is None:
            return result                      # no fallback configured means none is wanted
        if result.error.kind == "unsupported":
            return result
        chain = self._fallback_chain(spec)
        if not chain:
            return result
        detail, last = f"{spec.label}: {result.error.detail[:200]}", result
        for fb in chain:
            fb_result = self._invoke(self.client_for(fb), fb, method, system, user, kwargs)
            with self._lock:
                self.fallback_events.append({
                    "stage": self.current_stage, "role": role, "from": spec.label, "to": fb.label,
                    "error": result.error.detail[:700], "fallback_ok": isinstance(fb_result, Success),
                })
            if isinstance(fb_result, Success):
                return fb_result
            detail += f" || fallback {fb.label}: {fb_result.error.detail[:200]}"
            last = fb_result
        return Failure(ErrorInfo(kind=last.error.kind, detail=detail))

    def _fallback_chain(self, spec: ModelSpec) -> list:
        """The configured fallback, then the Analysis-role model, skipping whatever just failed.
        Without the second link, a fallback that IS the failing model (the strong Gemini model is
        both the council's choice and the all-Gemini fallback) never actually took over, and a
        quota error on it left the council empty."""
        chain = []
        for cand in (self.config.fallback, self.config.spec_for(ROLE_ANALYSIS)):
            if cand is not None and cand != spec and cand not in chain:
                chain.append(cand)
        return chain

    # -- council -----------------------------------------------------------------
    def council_backend(self) -> "CouncilBackend":
        return CouncilBackend(self)


VISION_IMAGE_TOKENS = 1200      # what one image costs in tokens, as an estimate for the run's budget


class CouncilBackend:
    """What pipeline/llm_council.py calls instead of its old NVIDIA-only table:
    .call(model_key, system, user) -> reply text, or {"_failed": True, ...}."""

    def __init__(self, router: ModelRouter):
        self._router = router

    def _role(self, model_key: str) -> str:
        return COUNCIL_KEY_ROLE.get(model_key, ROLE_COUNCIL_CHAIR)

    def label(self, model_key: str) -> str:
        return self._router.config.spec_for(self._role(model_key)).label

    def call(self, model_key: str, system: str, user: str):
        role = self._role(model_key)
        spec = self._router.config.spec_for(role)
        self._router.current_stage = f"Lab — Council ({ROLE_LABELS[role]})"
        result = self._router._call(role, "chat", system, user, temperature=0.6, max_tokens=4096,
                                    timeout_seconds=None, max_retries=None)
        if isinstance(result, Success):
            return (result.value or "").strip()
        return {"_failed": True, "error": result.error.detail, "model": spec.model}


# -- testing and discovery ---------------------------------------------------------
def friendly_error(error: ErrorInfo) -> str:
    """A short, plain reason for a failed call. A rate limit is called a rate
    limit (with how long to wait and which limit), not shown as a model fault."""
    detail = error.detail or ""
    if error.kind == "rate_limit":
        wait = _retry_after_seconds(detail)
        limit = re.search(r"limit:\s*(\d+)", detail)
        per = "minute" if "PerMinute" in detail else "day" if "PerDay" in detail else ""
        bits = ["Rate limit reached"]
        if limit and per:
            bits.append(f"({limit.group(1)} requests per {per})")
        elif limit:
            bits.append(f"(limit {limit.group(1)})")
        if wait:
            bits.append(f"· retry in about {wait:.0f} s")
        return " ".join(bits) + ". This is the provider throttling you, not a problem with the model."
    return detail[:300]


def _test_one(spec: ModelSpec, keys: dict, roles: list, factory, timeout: int) -> dict:
    out = {"spec": spec, "label": spec.label, "roles": roles, "ok": False, "latency_s": None,
           "json_ok": None, "json_note": "", "rate_limited": False, "error": ""}
    key = key_for(spec, keys)
    if not key:
        out["error"] = f"No API key for {spec.provider_label}."
        return out
    if spec.provider == CUSTOM_PROVIDER and not spec.base_url:
        out["error"] = "The custom endpoint needs a base URL."
        return out
    boost = token_boost(spec.model, spec.provider)
    try:
        client = factory(spec, key, None)
        t0 = time.time()
        r = client.chat("You are terse.", "Reply with the single word: pong", max_tokens=int(200 * boost),
                        timeout_seconds=timeout, max_retries=0)
        out["latency_s"] = round(time.time() - t0, 1)
        if not isinstance(r, Success):
            out["error"] = friendly_error(r.error)
            out["rate_limited"] = r.error.kind == "rate_limit"
            return out
        if not (r.value or "").strip():
            out["error"] = "The model returned an empty reply."
            return out
        out["ok"] = True
        # Most stages need strict JSON, so check that too.
        j = client.chat_json('Return a JSON object {"ok": true}.', "Return it now.",
                             max_tokens=int(300 * boost), timeout_seconds=timeout, max_retries=0)
        if isinstance(j, Success):
            try:
                out["json_ok"] = isinstance(json.loads(_strip_fences(j.value)), dict)
            except ValueError:
                out["json_ok"] = False
        elif j.error.kind == "rate_limit":
            out["json_ok"] = None                      # inconclusive: it was throttled, not wrong
            out["json_note"] = friendly_error(j.error)
        else:
            out["json_ok"] = False
            out["json_note"] = friendly_error(j.error)
    except Exception as e:                      # noqa: BLE001 -- a test must report, never raise
        out["ok"] = False
        out["error"] = f"{type(e).__name__}: {str(e)[:250]}"
    return out


def _strip_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    return text.strip()


def run_model_tests(config: ModelConfig, keys: dict, *, factory=build_spec_client, timeout: int = 30) -> list:
    """Sends each distinct model a tiny real request (plain, then strict-JSON) in
    parallel and reports ok / latency / json_ok / the exact error. One entry per
    distinct model, listing every role that uses it."""
    roles_by_spec: dict = {}
    for role in ALL_ROLES:
        spec = config.roles.get(role)
        if spec:
            roles_by_spec.setdefault(spec, []).append(ROLE_LABELS[role])
    if config.fallback:
        roles_by_spec.setdefault(config.fallback, []).append("Fallback")
    specs = list(roles_by_spec)
    with ThreadPoolExecutor(max_workers=max(1, len(specs))) as pool:
        futures = [pool.submit(_test_one, s, keys, roles_by_spec[s], factory, timeout) for s in specs]
        return [f.result() for f in futures]


_NON_CHAT = ("embedding", "embed", "tts", "image", "audio", "transcribe", "whisper", "guard", "rerank",
             "moderation", "vision-preview", "imagen", "veo", "live", "robotics", "computer-use",
             "orpheus", "safeguard")      # Groq: text-to-speech and the safety classifier


def fetch_models(provider: str, api_key: str, base_url: str = "", timeout: int = 15) -> list:
    """The chat models a provider's /models endpoint lists for this key (empty
    list when it cannot be reached; the UI falls back to the registry's list)."""
    if provider == CUSTOM_PROVIDER:
        base = base_url
    else:
        cfg = PROVIDER_REGISTRY.get(provider)
        base = cfg.base_url if cfg else ""
    if not base or not api_key:
        return []
    try:
        r = requests.get(base.rstrip("/") + "/models", headers={"Authorization": f"Bearer {api_key}"},
                         timeout=timeout)
        r.raise_for_status()
        ids = [str(m.get("id", "")).replace("models/", "") for m in r.json().get("data", [])]
    except (requests.RequestException, ValueError):
        return []
    return sorted({i for i in ids if i and not any(bad in i.lower() for bad in _NON_CHAT)})
