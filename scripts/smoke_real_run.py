"""Manual smoke test against a REAL provider: one tiny call per model role.

Spends a few hundred tokens. Never run in CI.
    python scripts/smoke_real_run.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MAX_TOKENS = 20


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    from utils.model_providers import PROVIDER_REGISTRY
    from utils.model_router import ROLE_LABELS, ModelRouter
    from utils.model_settings import load_config

    keys = {pk: os.environ.get(p.api_key_env, "").strip() for pk, p in PROVIDER_REGISTRY.items()}
    available = {pk for pk, k in keys.items() if k}
    if not available:
        print("No provider key found in the environment / .env")
        return 2
    config = load_config(available)
    router = ModelRouter(config, keys)
    failed = 0
    for role in ROLE_LABELS:
        try:
            res = router.client_for(config.spec_for(role)).chat(
                "Reply with the single word OK.", "ping", max_tokens=MAX_TOKENS)
            ok = hasattr(res, "value")
            print(f"{'PASS' if ok else 'FAIL'}  {role}  {config.spec_for(role).label}")
            failed += 0 if ok else 1
        except Exception as exc:
            print(f"FAIL  {role}: {exc}")
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

