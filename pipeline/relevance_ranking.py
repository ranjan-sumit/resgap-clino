"""Relevance ranking of search results against a gap, with no network call.

The Gap Challenger used to rerank with a model hosted by NVIDIA. That model was retired (HTTP 410), the one before it
was too, NVIDIA no longer lists a reranker at all, and the step failed silently, so it never ran. It also sent the gap and
every candidate abstract to a third party. Candidate lists are short (a few dozen at most) and the next step is a model
that reads the best ten, so a deterministic lexical ranking is enough: words shared with the gap, weighted by how rare
they are among the candidates, with a bonus for shared two-word phrases. Nothing leaves the machine.
"""
from __future__ import annotations

import math
import re

RANKER = "token-overlap-v1"

_STOP = frozenset("""
a an and are as at be been by for from has have in into is it its of on or that the their these this to was were which
with without not no more most other than then there they we our can may also using use used study studies paper
""".split())
# words that frame a gap rather than describe a topic
_FRAMING = frozenset("missing lack lacking absence unexplored unestablished unknown gap gaps future need needs novel".split())


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]{3,}", (text or "").lower()) if t not in _STOP and t not in _FRAMING]


def rerank_candidates(query: str, passages: list[str]) -> list[dict]:
    """[{"index": i, "score": float}, ...] best first, `index` being the passage's original position. Empty for an
    empty query or no passages. Ties keep the original order."""
    if not query or not passages:
        return []
    q = _tokens(query)
    if not q:
        return [{"index": i, "score": 0.0} for i in range(len(passages))]
    q_set = set(q)
    q_bigrams = set(zip(q, q[1:]))
    docs = [_tokens(p) for p in passages]
    n = len(docs)
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    idf = lambda t: math.log(1 + (n + 1) / (df.get(t, 0) + 1))
    scored = []
    for i, d in enumerate(docs):
        if not d:
            scored.append({"index": i, "score": 0.0})
            continue
        tf: dict[str, int] = {}
        for t in d:
            tf[t] = tf.get(t, 0) + 1
        overlap = sum(idf(t) * (1 + math.log(c)) for t, c in tf.items() if t in q_set)
        phrases = sum(1 for bg in zip(d, d[1:]) if bg in q_bigrams)
        score = (overlap + 1.5 * phrases) / math.sqrt(len(d))
        scored.append({"index": i, "score": round(score, 4)})
    return sorted(scored, key=lambda r: -r["score"])
