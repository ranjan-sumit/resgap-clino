"""Which model answered a cached step, as a short string for cache keys.

A cached result belongs to the (provider, model) that produced it: the same paper read by two models must give two
entries, and switching the model must recompute. Clients without a model (tests, plain fakes) give an empty tag.
"""
from __future__ import annotations

import hashlib


def model_tag(client) -> str:
    """The model the client would use for its current stage, or '' when it cannot say."""
    fn = getattr(client, "cache_tag", None)
    if not callable(fn):
        return ""
    try:
        tag = fn()
    except Exception:
        return ""
    return tag if isinstance(tag, str) else ""


def suffix(tag: str) -> str:
    """The part appended to a cache key; nothing when there is no tag (keeps old-style keys for taggless callers)."""
    return f":m{hashlib.sha256(tag.encode()).hexdigest()[:10]}" if tag else ""
