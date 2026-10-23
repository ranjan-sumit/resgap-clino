"""Settings that live for the browser session, resolved without any widget.

Streamlit forgets a widget's value as soon as a run does not draw it. Settings are drawn only on
the Settings page, so their values are copied into one plain dict (`st.session_state["_settings"]`)
and every other screen reads that dict. Keys typed there stay in memory only: nothing here is ever
written to disk.
"""
from __future__ import annotations

import os

# Per-run options and their defaults (the wizard starts from these; the Settings page edits them).
DEFAULT_OPTIONS = {
    "extract_refs": False,
    "ref_limit": "50",
    "enable_quality_engine": False,
    "override_quality_gate": False,
    "enable_gap_challenger": False,
    "min_gaps_per_paper": 0,
    "use_vision": False,
}


def new_settings() -> dict:
    return {"typed_keys": {}, "custom_base": "", "custom_key": "", "ss_key": "", **DEFAULT_OPTIONS}


def resolve_keys(settings: dict, registry: dict, custom_provider: str, env=None) -> dict:
    """{provider: key, 'custom': key, 'sources': {...}, 'available': set, 'ss_key': str}.
    A typed key wins; otherwise the environment variable named by the provider is used."""
    env = os.environ if env is None else env
    typed = settings.get("typed_keys", {})
    keys, sources = {}, {}
    for pk, cfg in registry.items():
        t = (typed.get(pk) or "").strip()
        e = (env.get(cfg.api_key_env, "") or "").strip()
        keys[pk] = t or e
        sources[pk] = "typed" if t else ("environment" if e else None)
    custom_base = (settings.get("custom_base") or "").strip()
    ck_typed = (settings.get("custom_key") or "").strip()
    ck_env = (env.get("CUSTOM_LLM_API_KEY", "") or "").strip()
    keys[custom_provider] = ck_typed or ck_env
    sources[custom_provider] = "typed" if ck_typed else ("environment" if ck_env else None)
    from utils.provider_policy import endpoint_problem, provider_allowed
    available = {pk for pk in registry if keys[pk] and provider_allowed(pk)}
    custom_problem = endpoint_problem(custom_base) if custom_base else None
    if keys[custom_provider] and custom_base and provider_allowed(custom_provider) and not custom_problem:
        available.add(custom_provider)
    ss_typed = (settings.get("ss_key") or "").strip()
    ss_env = (env.get("SEMANTIC_SCHOLAR_API_KEY", "") or "").strip()
    return {"keys": keys, "sources": sources, "available": available, "custom_base": custom_base,
            "custom_base_problem": custom_problem,
            "ss_key": ss_typed or ss_env, "ss_source": "typed" if ss_typed else ("environment" if ss_env else None)}


def model_issues(cfg, available: set, main_roles, role_labels: dict, provider_name) -> list[str]:
    """Problems that would make a run fail (a chosen model's provider has no key)."""
    issues = []
    for role in main_roles:
        spec = cfg.spec_for(role)
        if spec.provider not in available:
            issues.append(f"{role_labels[role]}: add a {provider_name(spec.provider)} key in Settings.")
    return issues


def source_label(source: str | None) -> str:
    return {"typed": "in use (typed this session)", "environment": "in use (from the environment)",
            None: "not set"}[source]


def hide_paths() -> bool:
    """On a hosted deployment the server's folder names mean nothing to the user."""
    return os.environ.get("RESGAP_HIDE_PATHS", "").strip().lower() in ("1", "true", "yes")
