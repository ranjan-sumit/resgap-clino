import json

import pytest

from utils import cost_guard
from utils import run_planner as rp

CHARS = [55_000, 55_000, 55_000]                      # the calibrated 3-paper run
ALL_KEYS = {"gemini", "openai", "groq"}


def _costs(available=ALL_KEYS, options=None, prices=None, shares=None):
    prices = prices if prices is not None else rp.BUILTIN_PRICES
    out = {}
    for tier in rp.TIERS:
        opts = {**rp.TIER_OPTIONS[tier], **(options or {})}
        tokens = rp.plan_tokens(CHARS, opts, shares)
        out[tier] = rp.tier_cost(rp.resolve_assignment(tier, available)["roles"], tokens, prices)
    return out


def test_role_names_match_the_model_router():
    from utils import model_router as mr
    assert (rp.ROLE_EXTRACTION, rp.ROLE_WIKI, rp.ROLE_ANALYSIS) == (mr.ROLE_EXTRACTION, mr.ROLE_WIKI, mr.ROLE_ANALYSIS)
    assert (rp.ROLE_COUNCIL_A, rp.ROLE_COUNCIL_B, rp.ROLE_COUNCIL_C, rp.ROLE_CHAIR) == (
        mr.ROLE_COUNCIL_A, mr.ROLE_COUNCIL_B, mr.ROLE_COUNCIL_C, mr.ROLE_COUNCIL_CHAIR)


def test_every_planned_model_is_in_its_providers_catalog():
    from utils.model_providers import PROVIDER_REGISTRY
    for tier, prefs in rp._PREFS.items():
        for role, options in prefs.items():
            for provider, model in options:
                assert model in PROVIDER_REGISTRY[provider].known_models, (tier, role, provider, model)


def test_tiers_get_more_expensive_and_more_thorough():
    c = _costs()
    assert c["economy"]["mid"] < c["balanced"]["mid"] < c["thorough"]["mid"]
    assert not rp.TIER_OPTIONS["economy"]["enable_gap_challenger"] and rp.TIER_OPTIONS["thorough"]["extract_refs"]


def test_a_gemini_only_user_gets_a_complete_plan_and_is_told_what_a_second_key_adds():
    plan = rp.resolve_assignment("balanced", {"gemini"})
    assert all(plan["roles"][r][0] == "gemini" for r in rp.PLAN_ROLES)
    assert plan["roles"][rp.ROLE_ANALYSIS] == ("gemini", "gemini-3.8-flash")
    assert plan["roles"][rp.ROLE_CHAIR] == ("gemini", "gemini-4-argon")
    assert plan["missing"] == ["openai"]                      # only council seats 2 and 3 want an OpenAI model
    assert plan["fallback"] is not None                       # another Gemini model, there being no second provider


def test_with_all_keys_the_balanced_tier_matches_the_research_configuration():
    roles = rp.resolve_assignment("balanced", ALL_KEYS)["roles"]
    assert roles[rp.ROLE_EXTRACTION] == roles[rp.ROLE_WIKI] == ("gemini", "gemini-3.5-flash-lite")
    assert roles[rp.ROLE_ANALYSIS] == ("gemini", "gemini-3.8-flash")
    assert roles[rp.ROLE_CHAIR] == ("gemini", "gemini-4-argon")
    assert roles[rp.ROLE_COUNCIL_B] == ("openai", "gpt-6.1-sol") and roles[rp.ROLE_COUNCIL_C] == ("openai", "gpt-6-luna")
    assert rp.resolve_assignment("balanced", ALL_KEYS)["fallback"][0] != "gemini"   # a different provider


def test_the_mix_has_a_judge_from_a_different_provider_than_the_writer_where_it_matters():
    both = {"gemini", "openai"}
    for tier in ("economy", "thorough"):
        roles = rp.resolve_assignment(tier, both)["roles"]
        assert roles[rp.ROLE_ANALYSIS][0] == "openai" and roles[rp.ROLE_CHAIR][0] == "gemini", tier
    assert rp.resolve_assignment("economy", both)["roles"][rp.ROLE_ANALYSIS] == ("openai", "gpt-6-luna")
    assert rp.resolve_assignment("thorough", both)["roles"][rp.ROLE_ANALYSIS] == ("openai", "gpt-6.1-sol")
    # reading stays on the model that was tested live
    for tier in rp.TIERS:
        roles = rp.resolve_assignment(tier, both)["roles"]
        assert roles[rp.ROLE_EXTRACTION] == roles[rp.ROLE_WIKI] == ("gemini", "gemini-3.5-flash-lite")
        providers = {spec[0] for spec in roles.values()}
        assert providers == {"gemini", "openai"}, tier                           # every tier really mixes


def test_provider_modes_restrict_the_plan_and_never_leave_it_empty():
    keys = {"gemini", "openai", "groq", "nvidia"}
    assert rp.restrict_providers(keys, "mix") == {"gemini", "openai"}
    assert rp.restrict_providers(keys, "gemini") == {"gemini"} and rp.restrict_providers(keys, "openai") == {"openai"}
    assert rp.restrict_providers({"gemini", "groq"}, "openai") == {"gemini", "groq"}      # no GPT key: unrestricted
    for tier in rp.TIERS:
        gpt_only = rp.resolve_assignment(tier, {"openai"})
        assert {s[0] for s in gpt_only["roles"].values()} == {"openai"} and gpt_only["fallback"] is not None
        gem_only = rp.resolve_assignment(tier, {"gemini"})
        assert {s[0] for s in gem_only["roles"].values()} == {"gemini"}


def test_preview_shows_each_mode_even_without_its_key_so_the_modes_differ():
    gemini_key = {"gemini"}
    plans = {m: rp.resolve_assignment("balanced", rp.restrict_providers(gemini_key, m, preview=True))
             for m in rp.PROVIDER_MODES}
    providers = {m: {s[0] for s in p["roles"].values()} for m, p in plans.items()}
    assert providers == {"mix": {"gemini", "openai"}, "gemini": {"gemini"}, "openai": {"openai"}}
    assert rp.providers_needed(plans["gemini"]) <= gemini_key                     # usable now
    assert rp.providers_needed(plans["openai"]) - gemini_key == {"openai"}        # needs the missing key
    assert "openai" in rp.providers_needed(plans["mix"])
    # without preview a mode whose key is missing still falls back to what exists
    assert rp.restrict_providers(gemini_key, "openai") == gemini_key


def test_the_default_mode_matches_the_keys_that_exist():
    assert rp.default_mode({"gemini", "openai", "groq"}) == "mix"
    assert rp.default_mode({"gemini"}) == "gemini" and rp.default_mode({"openai"}) == "openai"
    assert rp.default_mode({"groq"}) == "gemini" and rp.default_mode(set()) == "gemini"


def test_rosalind_is_never_picked_automatically():
    for tier in rp.TIERS:
        for spec in rp.resolve_assignment(tier, ALL_KEYS)["roles"].values():
            assert spec[1] != "gpt-rosalind"


def test_no_keys_means_no_roles_not_a_crash():
    plan = rp.resolve_assignment("economy", set())
    assert plan["roles"] == {} and plan["fallback"] is None


def test_cost_scales_with_paper_text_and_depth():
    small = rp.plan_tokens([20_000, 20_000], {})["total"]
    big = rp.plan_tokens([200_000, 200_000], {})["total"]
    assert big > small * 5
    base = rp.plan_tokens(CHARS, {})["total"]
    assert rp.plan_tokens(CHARS, {"extract_refs": True})["total"] > base
    assert rp.plan_tokens(CHARS, {"enable_gap_challenger": True})["total"] == base + cost_guard.GAP_CHALLENGER_TOKENS
    assert rp.plan_tokens(CHARS, {"use_vision": True})["total"] == base + rp.VISION_TOKENS_PER_PAPER * 3


def test_role_tokens_add_up_to_the_total_and_the_range_brackets_it():
    t = rp.plan_tokens(CHARS, rp.TIER_OPTIONS["thorough"])
    assert abs(sum(t["by_role"].values()) - t["total"]) <= len(rp.PLAN_ROLES)
    assert t["low"] < t["total"] < t["high"]


def test_an_unpriced_model_is_named_and_left_out_not_guessed():
    roles = {rp.ROLE_EXTRACTION: ("gemini", "gemini-3.5-flash-lite"), rp.ROLE_WIKI: ("nvidia", "openai/gpt-oss-20b"),
             rp.ROLE_ANALYSIS: ("gemini", "gemini-3.5-flash-lite"), rp.ROLE_CHAIR: ("gemini", "gemini-3.5-flash-lite")}
    c = rp.tier_cost(roles, rp.plan_tokens(CHARS, {}), rp.BUILTIN_PRICES)
    assert c["unpriced"] == [rp.ROLE_WIKI] and c["by_role"][rp.ROLE_WIKI] is None and c["saving"] is None
    assert c["mid"] > 0


def test_prices_nothing_when_no_price_is_known():
    c = rp.tier_cost({r: ("nvidia", "x") for r in rp.PLAN_ROLES}, rp.plan_tokens(CHARS, {}), {})
    assert c["mid"] == 0 and len(c["unpriced"]) == 4


def test_routing_saving_compares_against_the_review_model_everywhere():
    c = _costs()["balanced"]
    assert c["premium"] > c["mid"] and 0 < c["saving"] < 1
    for tier, cost in _costs().items():
        assert cost["saving"] is None or 0 <= cost["saving"] < 1, tier


def test_purpose_picks_the_starting_tier_and_a_budget_only_lowers_it():
    costs = _costs()
    assert rp.choose_tier("screen", 0, costs)[0] == "economy"
    assert rp.choose_tier("review", 0, costs)[0] == "balanced"
    assert rp.choose_tier("publish", 0, costs)[0] == "thorough"
    tier, why = rp.choose_tier("publish", costs["balanced"]["high"] + 0.001, costs)
    assert tier == "balanced" and "over your" in why
    assert rp.choose_tier("screen", 1000, costs)[0] == "economy"          # a big budget never raises it
    tier, why = rp.choose_tier("publish", 0.0001, costs)
    assert tier == "economy" and "Even Economy" in why


def test_unpriced_tiers_are_not_ruled_out_by_a_budget():
    costs = _costs(prices={})
    assert rp.choose_tier("publish", 1.0, costs)[0] == "thorough"


def test_council_cost_is_priced_seat_by_seat():
    roles = rp.resolve_assignment("balanced", ALL_KEYS)["roles"]
    c = rp.council_cost_per_gap(roles, rp.BUILTIN_PRICES)
    assert c["unpriced"] == [] and 0.05 < c["usd"] < 1.0
    # the research notes' worked example: Gemini 3.8 Flash seat 30k in / 5k out = $0.04125
    flash = (30_000 * 0.75 + 5_000 * 3.75) / 1_000_000
    assert flash == pytest.approx(0.04125)


def test_shares_are_learned_from_a_real_runs_stage_tokens():
    by_stage = {"Stage 2 — LLM Wiki": 50_000, "Stage 1B — References": 10_000, "Stage 4 — Gaps": 30_000,
                "Stage 4c — Critic": 10_000}
    s = rp.role_shares_from_usage(by_stage)
    assert s[rp.ROLE_WIKI] == pytest.approx(0.5) and s[rp.ROLE_EXTRACTION] == pytest.approx(0.1)
    assert s[rp.ROLE_ANALYSIS] == pytest.approx(0.3) and s[rp.ROLE_CHAIR] == pytest.approx(0.1)
    assert rp.role_shares_from_usage({"Stage 2": 100}) is None and rp.role_shares_from_usage(None) is None


def test_usage_cost_prices_recorded_tokens_by_model_and_names_unknown_ones():
    got = rp.usage_cost({"gemini-3.5-flash-lite": 1_000_000, "mystery-model": 5}, rp.BUILTIN_PRICES)
    assert got["usd"] == pytest.approx(0.75 * 0.30 + 0.25 * 2.50) and got["unpriced"] == ["mystery-model"]


def test_user_prices_win_and_only_changes_are_saved(isolated_env):
    assert rp.effective_prices() == rp.BUILTIN_PRICES
    prices = dict(rp.BUILTIN_PRICES)
    prices["gemini/gemini-3.5-flash-lite"] = (0.5, 3.0)           # changed
    prices["custom/my-model"] = (1.0, 2.0)                        # new
    rp.save_user_prices(prices)
    saved = json.loads(cost_guard.prices_path().read_text(encoding="utf-8"))
    assert set(saved) == {"gemini/gemini-3.5-flash-lite", "custom/my-model"}
    eff = rp.effective_prices()
    assert eff["gemini/gemini-3.5-flash-lite"] == (0.5, 3.0) and eff["openai/gpt-6-luna"] == (0.10, 0.50)


def test_scanned_papers_and_page_conversion():
    assert rp.scanned_count([100_000, 800, 2_000]) == 2
    assert rp.chars_for_pages(2, 10) == [36_000, 36_000]


def test_each_job_offers_the_distinct_models_the_tiers_would_use():
    opts = rp.job_options(rp.ROLE_EXTRACTION, ALL_KEYS, rp.BUILTIN_PRICES)
    assert [o["model"] for o in opts] == ["gemini-3.5-flash-lite"] and opts[0]["tiers"] == ["Economy", "Balanced", "Thorough"]
    analysis = rp.job_options(rp.ROLE_ANALYSIS, ALL_KEYS, rp.BUILTIN_PRICES)
    assert [(o["provider"], o["model"], o["tiers"]) for o in analysis] == [
        ("openai", "gpt-6-luna", ["Economy"]), ("gemini", "gemini-3.8-flash", ["Balanced"]),
        ("openai", "gpt-6.1-sol", ["Thorough"])]
    assert rp.job_options("fallback", ALL_KEYS, rp.BUILTIN_PRICES)             # the fallback row gets suggestions too
    assert rp.job_options(rp.ROLE_ANALYSIS, set(), rp.BUILTIN_PRICES) == []


def test_option_labels_name_the_tiers_the_model_and_its_price():
    opts = rp.job_options(rp.ROLE_ANALYSIS, ALL_KEYS, rp.BUILTIN_PRICES)
    assert rp.option_label(opts[1]) == "Balanced: gemini-3.8-flash ($0.75/$3.75)"           # input/output per 1M tokens
    assert rp.option_label({"model": "m", "tiers": ["Economy", "Thorough"], "price": (1, 2)}).startswith("Economy, Thorough: m")
    assert rp.option_label(rp.job_options(rp.ROLE_EXTRACTION, ALL_KEYS, rp.BUILTIN_PRICES)[0]).startswith("All tiers: ")
    assert "no price set" in rp.option_label({"model": "x", "tiers": ["Economy"], "price": None})
    assert "($0.075/$0.30)" in rp.option_label({"model": "g", "tiers": ["Economy"], "price": (0.075, 0.3)})


def test_formatting():
    assert rp.fmt_usd(0.001) == "<$0.01" and rp.fmt_usd(0.1234) == "$0.12" and rp.fmt_usd(12.5) == "$12.50"
    assert rp.fmt_range(0.2, 0.5) == "$0.20 to $0.50"
    assert "approved access" in rp.model_note("openai", "gpt-rosalind")
    assert rp.model_note("gemini", "gemini-3.5-flash-lite") == ""
