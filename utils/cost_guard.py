"""Before a run: how many tokens will it use (roughly), what might that cost, and a cap that
stops it cleanly. During a run: a running count that warns near the cap and refuses further
model calls once it is passed.

The count is an estimate from text length (about 4 characters per token), not the provider's
own meter: some providers report no usage on streamed replies, and a cap has to work for all.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

CHARS_PER_TOKEN = 4
WARN_FRACTION = 0.8
DEFAULT_CAP_TOKENS = 2_000_000

# Calibrated on a real 3-paper run (about 55,000 characters each, ~170,000 tokens recorded by the
# provider, more unrecorded): reading, extraction, gap finding, critic, literature check and
# proposals together come to about 4x the paper text, plus a fixed part per paper.
PAPER_TEXT_MULTIPLIER = 4.0
PER_PAPER_FIXED_TOKENS = 6_000
REFERENCES_TOKENS = 25_000            # when cited references are fetched (about 50 per paper)
GAP_CHALLENGER_TOKENS = 30_000
LOW, HIGH = 0.7, 1.7                  # the honest width of the estimate


class BudgetExceededError(Exception):
    """The run used more tokens than its cap, so it was stopped."""

    def __init__(self, used: int, cap: int):
        self.used, self.cap = used, cap
        super().__init__(f"This run reached its token cap ({used:,} of {cap:,} estimated tokens) and was "
                         "stopped before using more. Raise the cap under Advanced options, or use fewer papers.")


def estimate_run(paper_chars: list[int], *, extract_refs: bool = False, gap_challenger: bool = False) -> dict:
    """{'tokens': mid, 'low': .., 'high': ..} for a run over papers with these text lengths."""
    paper_tokens = sum(paper_chars) / CHARS_PER_TOKEN
    mid = paper_tokens * PAPER_TEXT_MULTIPLIER + PER_PAPER_FIXED_TOKENS * len(paper_chars)
    mid += REFERENCES_TOKENS * len(paper_chars) / 3 if extract_refs else 0
    mid += GAP_CHALLENGER_TOKENS if gap_challenger else 0
    return {"tokens": int(mid), "low": int(mid * LOW), "high": int(mid * HIGH)}


def prices_path() -> Path:
    import utils.database as db
    return Path(db._db_path()).resolve().parent / "model_prices.json"


def load_prices() -> dict:
    """Optional data/model_prices.json: {"provider/model": [usd_per_million_input, usd_per_million_output]}.
    There is no built-in price list: prices change, and a wrong one is worse than none."""
    try:
        raw = json.loads(prices_path().read_text(encoding="utf-8"))
        return {k: (float(v[0]), float(v[1])) for k, v in raw.items()}
    except (OSError, ValueError, TypeError, IndexError):
        return {}


def estimate_cost(tokens: int, provider: str, model: str, prices: dict | None = None) -> float | None:
    """USD for `tokens` (assumed 75% input, 25% output), or None when no price is configured."""
    price = (prices if prices is not None else load_prices()).get(f"{provider}/{model}")
    if not price:
        return None
    return round((tokens * 0.75 * price[0] + tokens * 0.25 * price[1]) / 1_000_000, 2)


def describe_estimate(est: dict, cap: int, cost: float | None = None) -> str:
    text = f"Estimated {est['low']:,}–{est['high']:,} tokens (about {est['tokens']:,})"
    text += f" · about ${cost:.2f}" if cost is not None else " · cost depends on your plan (no price set)"
    if est["high"] > cap:
        text += f" · ⚠ the upper estimate exceeds your cap of {cap:,}"
    return text


class TokenBudget:
    """Thread-safe running count with a cap. `add` raises nothing; `check` raises
    BudgetExceededError once the cap is passed."""

    def __init__(self, cap: int | None, on_warn=None):
        self.cap = cap
        self.used = 0
        self._on_warn = on_warn
        self._warned = False
        self._lock = threading.Lock()

    def add(self, tokens: int) -> None:
        warn = False
        with self._lock:
            self.used += max(0, int(tokens))
            if self.cap and not self._warned and self.used >= WARN_FRACTION * self.cap:
                self._warned = warn = True
        if warn and self._on_warn:
            self._on_warn(f"This run has used about {self.used:,} of its {self.cap:,}-token cap.")

    @property
    def exceeded(self) -> bool:
        return bool(self.cap) and self.used >= self.cap

    def check(self) -> None:
        if self.exceeded:
            raise BudgetExceededError(self.used, self.cap)

    @staticmethod
    def tokens_of(*texts) -> int:
        return sum(len(t or "") for t in texts) // CHARS_PER_TOKEN
