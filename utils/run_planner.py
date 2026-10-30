"""Run planner: from the papers loaded, a budget and the purpose of the result, choose a tier of models
and depth, and say roughly what the run will cost.

Three tiers (Economy, Balanced, Thorough) each set BOTH the model for every job and how much work is done
(deep gap validation, quality check, cited references). The planner never changes a model by itself: the
caller applies a tier when the user presses its button.

Everything here is an estimate and is labelled as one:
  * Tokens come from the paper text (utils.cost_guard.estimate_run, calibrated on a real run), then are split
    across jobs by SHARES. The defaults are planning assumptions; once a saved run has per-stage token counts,
    `role_shares_from_usage` replaces them with that run's real split.
  * Prices are a built-in table (PRICES_AS_OF) that the user can edit; edits are saved to model_prices.json
    and always win. A model with no price is left out of the total and named, never guessed.
  * Input and output tokens are assumed 75% / 25% (as in cost_guard.estimate_cost).
Real cost can be higher: reasoning tokens, retries and long outputs are not counted.
"""
from __future__ import annotations

import json
from datetime import date

from utils import cost_guard
from utils.model_providers import PROVIDER_REGISTRY

# The jobs a run uses. Same strings as utils.model_router (a test keeps them equal).
ROLE_EXTRACTION, ROLE_WIKI, ROLE_ANALYSIS = "extraction", "wiki", "analysis"
ROLE_COUNCIL_A, ROLE_COUNCIL_B, ROLE_COUNCIL_C, ROLE_CHAIR = "council_a", "council_b", "council_c", "council_chair"
PLAN_ROLES = (ROLE_EXTRACTION, ROLE_WIKI, ROLE_ANALYSIS, ROLE_CHAIR)      # the jobs of a normal run
SEAT_ROLES = (ROLE_COUNCIL_A, ROLE_COUNCIL_B, ROLE_COUNCIL_C, ROLE_CHAIR)  # the Computational Lab council
ROLE_NAMES = {ROLE_EXTRACTION: "Extraction", ROLE_WIKI: "Wiki & graph", ROLE_ANALYSIS: "Analysis",
              ROLE_CHAIR: "Review", ROLE_COUNCIL_A: "Council seat 1", ROLE_COUNCIL_B: "Council seat 2",
              ROLE_COUNCIL_C: "Council seat 3"}

# ── Prices ($ per 1M tokens, input / output) ─────────────────────────────────────────────────
PRICES_AS_OF = "2026-10-23"
PRICE_SOURCE = "Your research notes (23 Oct 2026), not independently checked."
BUILTIN_PRICES = {
    "gemini/gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini/gemini-3.8-flash": (0.75, 3.75),
    "gemini/gemini-4-argon": (2.00, 10.00),
    "openai/gpt-6-luna": (0.10, 0.50),
    "openai/gpt-6.1-sol": (2.00, 10.00),
    "openai/gpt-rosalind": (5.00, 25.00),
    "openai/gpt-6-astra": (10.00, 50.00),
    # From Groq's own price list, noted in utils/model_providers.py (2026-10-20).
    "groq/openai/gpt-oss-20b": (0.075, 0.30),
    "groq/openai/gpt-oss-120b": (0.15, 0.60),
    "groq/qwen/qwen3.8-27b": (0.80, 4.00),
}
# Cautions shown beside a price or a model.
PRICE_NOTES = {
    "gemini/gemini-4-argon": "Introductory price until 30 Nov 2026.",
    "gemini/gemini-3.8-flash": "Promotional price until 31 Dec 2026.",
    "openai/gpt-rosalind": "Needs approved access (not available on an ordinary key).",
}
UNVERIFIED_MODELS = {"gemini/gemini-3.8-flash", "gemini/gemini-4-argon", "openai/gpt-6-luna",
                     "openai/gpt-6.1-sol", "openai/gpt-rosalind", "openai/gpt-6-astra"}


def price_age_days(today: date | None = None) -> int:
    return ((today or date.today()) - date.fromisoformat(PRICES_AS_OF)).days


def effective_prices() -> dict:
    """The built-in table with the user's saved prices on top (the user's always win)."""
    merged = dict(BUILTIN_PRICES)
    merged.update(cost_guard.load_prices())
    return merged


def save_user_prices(prices: dict) -> None:
    """Save every price that differs from the built-in table (or is new) to model_prices.json."""
    keep = {k: [float(v[0]), float(v[1])] for k, v in prices.items()
            if k not in BUILTIN_PRICES or tuple(map(float, v)) != BUILTIN_PRICES[k]}
    path = cost_guard.prices_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keep, indent=2, sort_keys=True), encoding="utf-8")


def price_for_model(model: str, prices: dict):
    """(input, output) for a bare model name (token usage is recorded without its provider)."""
    for key, value in prices.items():
        if key.split("/", 1)[-1] == model:
            return value
    return None


def _blend(price) -> float:
    return 0.75 * price[0] + 0.25 * price[1]


# ── Tiers ────────────────────────────────────────────────────────────────────────────────────
TIERS = ("economy", "balanced", "thorough")
TIER_INFO = {
    "economy": {"label": "Economy", "purpose": "screen",
                "tagline": "Fast and low cost. Good for screening many papers."},
    "balanced": {"label": "Balanced", "purpose": "review",
                 "tagline": "Stronger analysis and a stronger reviewer. A good default."},
    "thorough": {"label": "Thorough", "purpose": "publish",
                 "tagline": "The strongest reasoning and the full literature check, for results you will act on."},
}
PURPOSES = {"screen": "Quick screen", "review": "Team review", "publish": "Publication or decision"}
# What each tier switches on, beyond the models (these are the same keys as the analysis options).
TIER_OPTIONS = {
    "economy": {"enable_gap_challenger": False, "extract_refs": False, "enable_quality_engine": False},
    "balanced": {"enable_gap_challenger": True, "extract_refs": False, "enable_quality_engine": True},
    "thorough": {"enable_gap_challenger": True, "extract_refs": True, "ref_limit": "50",
                 "enable_quality_engine": True},
}
OPTION_LABELS = (("enable_gap_challenger", "Deep gap validation"), ("enable_quality_engine", "Quality check"),
                 ("extract_refs", "Cited references"))
SPEED = {"economy": "Fastest", "balanced": "Moderate", "thorough": "Slowest"}
REFERENCE_NOTE = "Looking up cited references adds about 5 to 10 minutes per paper."

_LITE = [("gemini", "gemini-3.5-flash-lite"), ("openai", "gpt-6-luna"), ("groq", "openai/gpt-oss-20b"),
         ("nvidia", "openai/gpt-oss-20b")]
_MID = [("gemini", "gemini-3.8-flash")]
_TOP = [("gemini", "gemini-4-argon"), ("openai", "gpt-6.1-sol"), ("gemini", "gemini-3.8-flash")]
# Preference order per job; the first whose provider has a key wins. GPT-Rosalind is never chosen
# automatically (it needs approved access); it stays selectable by hand.
#
# The mix: Gemini does the high-volume reading (extraction, wiki) because that is what was tested live. Where a
# model judges another model's work, it comes from a DIFFERENT provider when two keys exist, so one family's
# blind spots are not shared by writer and judge:
#   Economy   analysis GPT-6 Luna      / review Gemini 3.8 Flash
#   Balanced  analysis Gemini 3.8 Flash / review Gemini 4 Argon   (council seats mix Gemini and GPT)
#   Thorough  analysis GPT-6.1 Sol     / review Gemini 4 Argon
_PREFS = {
    "economy": {
        ROLE_EXTRACTION: _LITE, ROLE_WIKI: _LITE, ROLE_ANALYSIS: [("openai", "gpt-6-luna")] + _LITE,
        ROLE_CHAIR: _MID + _LITE,
        ROLE_COUNCIL_A: _LITE, ROLE_COUNCIL_B: [("openai", "gpt-6-luna"), ("groq", "openai/gpt-oss-20b")] + _LITE,
        ROLE_COUNCIL_C: [("groq", "openai/gpt-oss-20b"), ("nvidia", "openai/gpt-oss-20b")] + _LITE,
        "fallback": [("openai", "gpt-6-luna"), ("groq", "openai/gpt-oss-20b"), ("gemini", "gemini-3.5-flash-lite"),
                     ("gemini", "gemini-3.8-flash"), ("openai", "gpt-6.1-sol")],
    },
    "balanced": {
        ROLE_EXTRACTION: _LITE, ROLE_WIKI: _LITE, ROLE_ANALYSIS: _MID + _LITE, ROLE_CHAIR: _TOP + _LITE,
        ROLE_COUNCIL_A: _MID + _LITE,
        ROLE_COUNCIL_B: [("openai", "gpt-6.1-sol"), ("groq", "openai/gpt-oss-120b")] + _LITE,
        ROLE_COUNCIL_C: [("openai", "gpt-6-luna"), ("groq", "openai/gpt-oss-20b")] + _LITE,
        "fallback": [("openai", "gpt-6-luna"), ("groq", "openai/gpt-oss-20b"), ("gemini", "gemini-3.5-flash-lite"),
                     ("gemini", "gemini-3.8-flash"), ("openai", "gpt-6.1-sol")],
    },
    "thorough": {
        ROLE_EXTRACTION: _LITE, ROLE_WIKI: _LITE,
        ROLE_ANALYSIS: [("openai", "gpt-6.1-sol"), ("gemini", "gemini-4-argon"), ("gemini", "gemini-3.8-flash")] + _LITE,
        ROLE_CHAIR: _TOP + _LITE,
        ROLE_COUNCIL_A: _MID + _LITE,
        ROLE_COUNCIL_B: [("openai", "gpt-6.1-sol"), ("groq", "openai/gpt-oss-120b")] + _LITE,
        ROLE_COUNCIL_C: [("openai", "gpt-6-luna"), ("groq", "openai/gpt-oss-20b")] + _LITE,
        "fallback": [("openai", "gpt-6.1-sol"), ("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-3.8-flash"),
                     ("gemini", "gemini-3.5-flash-lite"), ("openai", "gpt-6-luna")],
    },
}


PROVIDER_MODES = {"mix": "Mix of Gemini and GPT", "gemini": "Gemini only", "openai": "GPT only"}
_MODE_PROVIDERS = {"mix": {"gemini", "openai"}, "gemini": {"gemini"}, "openai": {"openai"}}


def restrict_providers(available: set, mode: str, preview: bool = False) -> set:
    """The providers a plan may use. By default a mode whose providers have no key leaves the plan unrestricted,
    so there is always an answer. With `preview=True` the plan uses the mode's providers whether or not a key
    exists, so the user can see what Gemini only, GPT only or the mix would look like and cost before adding a key."""
    if preview and mode in _MODE_PROVIDERS:
        return set(_MODE_PROVIDERS[mode])
    wanted = set(available) & _MODE_PROVIDERS.get(mode, set())
    return wanted or set(available)


def default_mode(available: set) -> str:
    """The Providers choice to start on: the mix when both keys exist, else the one provider that does."""
    if {"gemini", "openai"} <= set(available):
        return "mix"
    return "openai" if "openai" in available and "gemini" not in available else "gemini"


def providers_needed(plan: dict) -> set:
    """Every provider a resolved plan uses, fallback included."""
    used = {spec[0] for spec in plan["roles"].values()}
    if plan["fallback"]:
        used.add(plan["fallback"][0])
    return used


def _any_default(available: set):
    """Last resort: the registry default of whichever provider has a key."""
    for provider in sorted(available):
        cfg = PROVIDER_REGISTRY.get(provider)
        if cfg:
            return provider, cfg.default_model
    return None


def resolve_assignment(tier: str, available: set) -> dict:
    """{"roles": {role: (provider, model)}, "fallback": (provider, model) | None, "missing": [provider, ...]}.
    `missing` lists providers whose key would let the tier use its first-choice models."""
    prefs = _PREFS[tier]
    roles, missing = {}, []
    for role in (*PLAN_ROLES, ROLE_COUNCIL_A, ROLE_COUNCIL_B, ROLE_COUNCIL_C):
        chosen = next(((p, m) for p, m in prefs[role] if p in available), None)
        first = prefs[role][0][0]
        if first not in available and first not in missing:
            missing.append(first)
        roles[role] = chosen or _any_default(available)
    roles = {r: s for r, s in roles.items() if s}
    analysis = roles.get(ROLE_ANALYSIS)
    fallback = None
    for p, m in prefs["fallback"]:                       # another provider first, so one outage cannot take both
        if p in available and analysis and p != analysis[0]:
            fallback = (p, m)
            break
    if fallback is None:
        for p, m in prefs["fallback"]:
            if p in available and (p, m) != analysis:
                fallback = (p, m)
                break
    return {"roles": roles, "fallback": fallback, "missing": missing}


def job_options(role: str, available: set, prices: dict) -> list[dict]:
    """The models the three tiers would use for one job (role "fallback" for the fallback row):
    [{"provider", "model", "tiers": [tier labels], "price": (in, out) | None}], cheapest tier first, no repeats."""
    found: dict = {}
    for tier in TIERS:
        plan = resolve_assignment(tier, available)
        spec = plan["fallback"] if role == "fallback" else plan["roles"].get(role)
        if not spec:
            continue
        option = found.setdefault(spec, {"provider": spec[0], "model": spec[1], "tiers": [],
                                         "price": prices.get(f"{spec[0]}/{spec[1]}")})
        option["tiers"].append(TIER_INFO[tier]["label"])
    return list(found.values())


def _price_text(value: float) -> str:
    return f"${value:.2f}" if value >= 0.1 else f"${value:.3f}"


def option_label(option: dict) -> str:
    """One line for a dropdown: which tiers use it, the model, and what a million tokens cost."""
    tiers = "All tiers" if len(option["tiers"]) == len(TIERS) else ", ".join(option["tiers"])
    price = option["price"]
    cost = f"{_price_text(price[0])}/{_price_text(price[1])}" if price else "no price set"   # input/output per 1M tokens
    return f"{tiers}: {option['model']} ({cost})"


# ── Tokens ───────────────────────────────────────────────────────────────────────────────────
# Planning assumption for how a run's tokens split across jobs, until real per-stage counts exist.
DEFAULT_SHARES = {ROLE_EXTRACTION: 0.25, ROLE_WIKI: 0.30, ROLE_ANALYSIS: 0.35, ROLE_CHAIR: 0.10}
CHARS_PER_PAGE = 3600                  # a calibrated 3-paper run averaged about 55,000 characters over ~15 pages
VISION_TOKENS_PER_PAPER = 7_500        # "Analyze figures and tables" sends up to 5 pages per paper, roughly 1,500 tokens each
SCANNED_BELOW_CHARS = 2_500            # a PDF with less text than this is probably scanned or all figures


def chars_for_pages(papers: int, pages_each: int) -> list[int]:
    return [pages_each * CHARS_PER_PAGE] * papers


def scanned_count(paper_chars: list[int]) -> int:
    return sum(1 for c in paper_chars if c < SCANNED_BELOW_CHARS)


def role_shares_from_usage(by_stage: dict | None) -> dict | None:
    """The real split of a past run's tokens across the four jobs, from its per-stage counts.
    None when there is too little data to trust."""
    if not by_stage:
        return None
    from utils.model_router import role_for_stage
    totals = dict.fromkeys(PLAN_ROLES, 0)
    for stage, tokens in by_stage.items():
        role = role_for_stage(stage)
        if role in totals:
            totals[role] += int(tokens or 0)
    grand = sum(totals.values())
    if grand < 20_000:
        return None
    return {role: totals[role] / grand for role in PLAN_ROLES}


def plan_tokens(paper_chars: list[int], options: dict, shares: dict | None = None) -> dict:
    """{"total", "low", "high", "by_role"}: the run's tokens and how they split across the four jobs."""
    shares = shares or DEFAULT_SHARES
    base = cost_guard.estimate_run(paper_chars)["tokens"]
    by_role = {role: base * shares.get(role, 0) for role in PLAN_ROLES}
    if options.get("extract_refs"):
        by_role[ROLE_EXTRACTION] += cost_guard.estimate_run(paper_chars, extract_refs=True)["tokens"] - base
    if options.get("enable_gap_challenger"):
        by_role[ROLE_ANALYSIS] += cost_guard.GAP_CHALLENGER_TOKENS
    if options.get("use_vision"):
        by_role[ROLE_EXTRACTION] += VISION_TOKENS_PER_PAPER * len(paper_chars)
    total = sum(by_role.values())
    return {"total": int(total), "low": int(total * cost_guard.LOW), "high": int(total * cost_guard.HIGH),
            "by_role": {r: int(t) for r, t in by_role.items()}}


# ── Cost ─────────────────────────────────────────────────────────────────────────────────────
def tier_cost(roles: dict, tokens: dict, prices: dict) -> dict:
    """{"by_role": {role: usd | None}, "mid", "low", "high", "unpriced": [role], "premium", "saving"}.
    A job whose model has no price is left out of the total and listed in `unpriced`.
    `premium` is the cost if every job ran on the review model; `saving` is how much less this mix costs
    (None when it cannot be compared)."""
    by_role, unpriced = {}, []
    for role, tok in tokens["by_role"].items():
        spec = roles.get(role)
        price = prices.get(f"{spec[0]}/{spec[1]}") if spec else None
        by_role[role] = tok * _blend(price) / 1_000_000 if price else None
        if not price:
            unpriced.append(role)
    mid = sum(v for v in by_role.values() if v is not None)
    premium = saving = None
    chair = roles.get(ROLE_CHAIR)
    chair_price = prices.get(f"{chair[0]}/{chair[1]}") if chair else None
    if chair_price and not unpriced:
        premium = tokens["total"] * _blend(chair_price) / 1_000_000
        saving = max(0.0, 1 - mid / premium) if premium > 0 else None
    return {"by_role": by_role, "mid": mid, "low": mid * cost_guard.LOW, "high": mid * cost_guard.HIGH,
            "unpriced": unpriced, "premium": premium, "saving": saving}


# What one Computational Lab council evaluation sends and receives, per seat (input, output tokens). These
# are planning assumptions from the research notes, not measurements.
COUNCIL_CALL_TOKENS = {ROLE_COUNCIL_A: (30_000, 5_000), ROLE_COUNCIL_B: (30_000, 5_000),
                       ROLE_COUNCIL_C: (15_000, 2_000), ROLE_CHAIR: (40_000, 6_000)}


def council_cost_per_gap(roles: dict, prices: dict) -> dict:
    """{"usd": float, "unpriced": [role]}: one council evaluation of one gap, priced seat by seat."""
    usd, unpriced = 0.0, []
    for role, (tin, tout) in COUNCIL_CALL_TOKENS.items():
        spec = roles.get(role)
        price = prices.get(f"{spec[0]}/{spec[1]}") if spec else None
        if not price:
            unpriced.append(role)
            continue
        usd += (tin * price[0] + tout * price[1]) / 1_000_000
    return {"usd": usd, "unpriced": unpriced}


def usage_cost(by_model: dict | None, prices: dict) -> dict:
    """What a finished run's recorded tokens cost at these prices: {"usd", "unpriced": [model]}."""
    usd, unpriced = 0.0, []
    for model, tokens in (by_model or {}).items():
        price = price_for_model(model, prices)
        if price:
            usd += int(tokens or 0) * _blend(price) / 1_000_000
        else:
            unpriced.append(model)
    return {"usd": usd, "unpriced": unpriced}


# ── Choosing ─────────────────────────────────────────────────────────────────────────────────
def choose_tier(purpose: str, budget_usd: float, costs: dict) -> tuple[str, str]:
    """(tier, one-line reason). The purpose sets the starting tier; a budget (0 = none) can only lower it.
    Costs are compared at their upper estimate. A tier with no priced model is never ruled out by price."""
    start = TIERS.index(TIER_INFO_BY_PURPOSE.get(purpose, "balanced"))
    label = PURPOSES.get(purpose, PURPOSES["review"]).lower()
    if not budget_usd or budget_usd <= 0:
        return TIERS[start], f"Fits a {label}."
    for i in range(start, -1, -1):
        c = costs[TIERS[i]]
        nothing_priced = c["mid"] == 0 and bool(c["unpriced"])
        if nothing_priced or c["high"] <= budget_usd:
            why = f"Fits a {label} and your {fmt_usd(budget_usd)} budget."
            if i < start:
                why = (f"A {label} would normally use {TIER_INFO[TIERS[start]]['label']}, but its upper estimate "
                       f"is over your {fmt_usd(budget_usd)} budget.")
            return TIERS[i], why
    return TIERS[0], f"Even Economy may go over your {fmt_usd(budget_usd)} budget (up to {fmt_usd(costs['economy']['high'])})."


TIER_INFO_BY_PURPOSE = {info["purpose"]: tier for tier, info in TIER_INFO.items()}


# ── Words ────────────────────────────────────────────────────────────────────────────────────
def fmt_usd(value: float) -> str:
    if value < 0.005:
        return "<$0.01"
    return f"${value:,.2f}"


def fmt_range(low: float, high: float) -> str:
    if low < 0.005 and high < 0.005:
        return "<$0.01"
    return f"{fmt_usd(low)} to {fmt_usd(high)}"


def model_note(provider: str, model: str) -> str:
    key = f"{provider}/{model}"
    notes = [PRICE_NOTES[key]] if key in PRICE_NOTES else []
    if key in UNVERIFIED_MODELS:
        notes.append("Not yet checked with a live key: use Test models.")
    return " ".join(notes)
