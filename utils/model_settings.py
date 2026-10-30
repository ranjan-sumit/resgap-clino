"""
Recommended model assignments, and saving the user's choice.

Recommendations come from measurement, not a guess. The same wiki-compile task
(one 16-page paper, the app's own prompt and token limit) was run on each model,
and request limits were probed directly. Models that could not be measured (no
key) are recommended from their provider's registry defaults and flagged.

    model                  time/call  valid JSON  quality           free-tier request limit
    gemini-3.5-flash-lite  5-6 s      always      solid (1 limit.)  no throttling at 16 requests/24 s
    gemini-3.6-flash       5-7 s      7 of 7      richer (2-3)      5 requests/MINUTE (Google's error)
    gemini-3.7-flash       94-135 s   always      richest (4)       not measured; too slow to use
    nvidia gpt-oss-20b     21-42 s    always      solid (0)         not throttled in testing

    (gemini-3.6-flash needs the low reasoning effort the app sends: WITHOUT it a
    call took 13-25 s and 1 of 3 returned cut-off JSON; extra token headroom alone
    still left 2 of 6 broken.)

What that means for each job:
  * extraction, wiki: high-volume structured work -> the fastest reliable model.
  * analysis: gap validation alone makes 29+ calls in a row. gemini-3.6-flash is
    richer, but on a free key its 5/minute limit means a wait of minutes per run
    (a real run fell back to NVIDIA on 12 calls and took 12 minutes instead of 6).
    So analysis defaults to the model with headroom; 3.6-flash stays a one-click
    choice for paid keys.
  * council chair and seats: only a handful of calls per Lab run, so the stronger
    model fits, and seats come from DIFFERENT models/providers (independent views
    are the point of a council).
  * fallback: on a DIFFERENT provider, so one outage or quota cannot take down
    both the primary and its backup.
gemini-3.7-flash is never recommended: ~20x slower than 3.6-flash.

Only model choices are saved (data/model_settings.json). API keys never are.
"""
import json
from pathlib import Path

from utils import database as db
from utils.model_router import (
    ALL_ROLES, ROLE_ANALYSIS, ROLE_COUNCIL_A, ROLE_COUNCIL_B, ROLE_COUNCIL_C,
    ROLE_COUNCIL_CHAIR, ROLE_EXTRACTION, ROLE_WIKI, ModelConfig, ModelSpec,
)

BENCHMARK = [
    {"model": "Gemini · gemini-3.5-flash-lite", "time": "5–6 s", "valid_json": "always", "quality": "solid",
     "limit": "no throttling at 16 requests in 24 s"},
    {"model": "Gemini · gemini-3.6-flash", "time": "5–7 s", "valid_json": "7 of 7 (low reasoning effort)",
     "quality": "richer", "limit": "5 requests per minute"},
    {"model": "Gemini · gemini-3.7-flash", "time": "94–135 s", "valid_json": "always",
     "quality": "richest, ~20× slower", "limit": "not measured"},
    {"model": "NVIDIA · gpt-oss-20b", "time": "21–42 s", "valid_json": "always", "quality": "solid",
     "limit": "not throttled in testing"},
    {"model": "NVIDIA · nemotron-3.5-super-vl-120b", "time": "13 s (thinking off)",
     "valid_json": "1 of 1 tested", "quality": "large, reads images",
     "limit": "92 s with thinking on; not benchmarked on a full run"},
]

# Preference order per need; the first whose provider has a key wins. Entries for
# openai/groq come from registry defaults (not benchmarked).
_FAST = [("gemini", "gemini-3.5-flash-lite"), ("groq", "llama-3.1-8b-instant"),
         ("openai", "gpt-5.6-luna"), ("nvidia", "openai/gpt-oss-20b")]
# Analysis makes dozens of calls in a row, so it needs request headroom (see docstring).
_ANALYSIS = [("gemini", "gemini-3.5-flash-lite"), ("openai", "gpt-5.6-sol"),
             ("groq", "llama-3.3-70b-versatile"), ("nvidia", "openai/gpt-oss-20b")]
# The council makes only a handful of calls, so the stronger model fits there.
_STRONG = [("gemini", "gemini-3.6-flash"), ("openai", "gpt-5.6-sol"),
           ("groq", "llama-3.3-70b-versatile"), ("nvidia", "openai/gpt-oss-20b")]
_NOT_BENCHMARKED = {"groq", "openai", "qwen"}


def _first(pool: list, available: set) -> ModelSpec | None:
    for provider, model in pool:
        if provider in available:
            return ModelSpec(provider, model)
    return None


def recommend(available: set, preset: str = "recommended") -> ModelConfig:
    """A full assignment from the providers that have a key.
    preset="recommended": fast model for extraction/wiki, a model with request
    headroom for analysis, a stronger model for the council chair, mixed council
    seats, and a fallback on another provider. preset="fastest": the fast model
    for every role."""
    if preset not in ("recommended", "fastest"):
        raise ValueError(f"Unknown preset {preset!r}")
    fast = _first(_FAST, available) or ModelSpec("gemini", "gemini-3.5-flash-lite")
    fastest = preset == "fastest"
    analysis = fast if fastest else (_first(_ANALYSIS, available) or fast)
    chair = fast if fastest else (_first(_STRONG, available) or fast)

    roles = {ROLE_EXTRACTION: fast, ROLE_WIKI: fast, ROLE_ANALYSIS: analysis, ROLE_COUNCIL_CHAIR: chair}

    # Council seats: distinct models, different providers first.
    pool = [ModelSpec(p, m) for p, m in _STRONG + _FAST if p in available]
    seats, used_providers = [], set()
    for spec in pool:
        if spec not in seats and spec.provider not in used_providers:
            seats.append(spec); used_providers.add(spec.provider)
    for spec in pool:                         # fill remaining seats with other models
        if len(seats) >= 3:
            break
        if spec not in seats:
            seats.append(spec)
    while len(seats) < 3:                     # fewer than 3 distinct models available
        seats.append(chair)
    if fastest:
        seats = [fast, fast, fast]
    for role, spec in zip((ROLE_COUNCIL_A, ROLE_COUNCIL_B, ROLE_COUNCIL_C), seats):
        roles[role] = spec

    # Fallback: another provider if there is one, else another model on the same provider.
    fallback = None
    for provider, model in _FAST + _STRONG:
        if provider in available and provider != analysis.provider:
            fallback = ModelSpec(provider, model)
            break
    if fallback is None:
        for provider, model in _FAST + _STRONG:
            if provider == analysis.provider and ModelSpec(provider, model) != analysis:
                fallback = ModelSpec(provider, model)
                break
    return ModelConfig(roles, fallback)


def explain(config: ModelConfig) -> dict:
    """One-line reasons for the current assignment, for the UI."""
    notes = {}
    for role in ALL_ROLES:
        spec = config.spec_for(role)
        bits = []
        if spec.provider in _NOT_BENCHMARKED:
            bits.append("not benchmarked here: run Test models")
        elif spec.provider == "gemini" and spec.model == "gemini-3.7-flash":
            bits.append("measured 94–135 s per call, about 20× slower than gemini-3.6-flash")
        elif spec.provider == "gemini" and spec.model == "gemini-3.6-flash" and role in (
                ROLE_EXTRACTION, ROLE_WIKI, ROLE_ANALYSIS):
            bits.append("free-tier limit is 5 requests/minute (measured): long runs will wait or fall back")
        elif spec.provider == "nvidia":
            bits.append("measured 21–42 s per call, 4–8× slower than Gemini flash-lite")
        notes[role] = "; ".join(bits)
    return notes


# -- saving ------------------------------------------------------------------------
def settings_path() -> Path:
    return Path(db._db_path()).resolve().parent / "model_settings.json"


def save_config(config: ModelConfig) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
    from utils import audit_log                      # local import: audit_log needs the database, this module is loaded earlier
    from urllib.parse import urlparse
    audit_log.record("settings.provider", "model_settings", "", {
        "roles": ", ".join(f"{r}={s.provider}{'@' + (urlparse(s.base_url).hostname or '') if s.base_url else ''}/{s.model}"
                           for r, s in config.roles.items())})


def load_config(available: set) -> ModelConfig:
    """The saved assignment, or the recommended one if nothing valid is saved."""
    path = settings_path()
    if path.exists():
        try:
            return ModelConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, KeyError, TypeError, OSError):
            pass
    return recommend(available)
