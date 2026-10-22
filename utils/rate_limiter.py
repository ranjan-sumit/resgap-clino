"""Shared per-(provider, model) request limiter.

Parallel stages (wiki pages, evidence reading, gap finders) all call the same
model; without a shared limiter a burst exceeds a free-tier requests-per-minute
quota and the whole run degrades into 429s. `acquire` reserves the next free
slot (so concurrent callers queue in order) and sleeps until it; `penalize`
makes every caller wait out a provider's Retry-After.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, limits: dict | None = None, clock=time.monotonic, sleep=time.sleep,
                 window: float = 60.0):
        self.limits = dict(limits or {})           # {(provider, model): requests per window}
        self._clock, self._sleep, self.window = clock, sleep, window
        self._slots: dict = {}                     # key -> deque of reserved start times
        self._blocked_until: dict = {}
        self._lock = threading.Lock()
        self.waited_seconds = 0.0

    def acquire(self, provider: str, model: str) -> float:
        """Blocks until a request may start. Returns the seconds waited."""
        key = (provider, model)
        limit = self.limits.get(key)
        with self._lock:
            now = self._clock()
            start = max(now, self._blocked_until.get(key, 0.0))
            if limit:
                slots = self._slots.setdefault(key, deque())
                while slots and slots[0] <= start - self.window:
                    slots.popleft()
                if len(slots) >= limit:
                    start = max(start, slots[-limit] + self.window)
                slots.append(start)
            wait = max(0.0, start - now)
            self.waited_seconds += wait
        if wait > 0:
            self._sleep(wait)
        return wait

    def penalize(self, provider: str, model: str, seconds: float) -> None:
        """A 429 with Retry-After: nobody calls this model again until it elapses."""
        key = (provider, model)
        with self._lock:
            self._blocked_until[key] = max(self._blocked_until.get(key, 0.0), self._clock() + seconds)
