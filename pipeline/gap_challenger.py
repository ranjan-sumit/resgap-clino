"""
Gap Challenger — state machine (Clinova Phase 3, Epic 3.4, resolves PRD
FR-11/FR-12/FR-13 and ADR-008; 04-ai-research-architecture.md §5).

Builds on pipeline/academic_search.py's existing Semantic Scholar + arXiv
search (already in production as Stage 5's `validate_gaps()`), adding the
richer 6-terminal-status lifecycle the architecture doc specifies, on top
of it -- not a replacement. `validate_gaps()` and its simple open/partial/
solved status keep working unchanged; `run_challenge()` here is a second,
additive path any caller can opt into per gap.

No new infrastructure needed: query-family generation is deterministic
string variation (no embeddings/Qdrant), multi-provider search reuses the
existing SS/arXiv functions, and only the relevance/contradiction
judgment step uses one scoped LLM call per gap -- everything else,
including the terminal-status decision itself, is plain deterministic
code, per §5.1's explicit requirement ("never left to implicit LLM
judgment").
"""
import json
import re

from utils.azure_client import unwrap
from pipeline.academic_search import (
    _search_semantic_scholar_with_status, _search_arxiv_with_status,
    _truncate_at_word_boundary,
)

GAP_CHALLENGER_STAGE_VERSION = 1

# 04-ai-research-architecture.md §5.2's binding rule: below this, a search
# can never resolve to anything but INSUFFICIENT_EVIDENCE, regardless of
# result count. The doc explicitly marks 0.6 as a Phase 3 tuning parameter,
# not a permanently fixed constant -- kept as a module constant here for
# the same reason QUALITY_GATE_FAIL_THRESHOLD lives in corpus_quality.py.
SEARCH_COVERAGE_THRESHOLD = 0.6
LIKELY_CLOSED_MIN_CONVERGING = 2
CLOSED_MIN_CONVERGING = 3

STATES = (
    "GENERATED", "EVIDENCE_SUPPORTED", "SEARCH_PENDING", "SEARCHED", "CHALLENGED",
)
TERMINAL_STATUSES = (
    "INSUFFICIENT_EVIDENCE", "OPEN", "PARTIALLY_OPEN", "CONTESTED",
    "LIKELY_CLOSED", "CLOSED",
)

_PROVIDERS = ("semantic_scholar", "arxiv")


def check_evidence_supported(gap: dict) -> bool:
    """§5.1's EVIDENCE_SUPPORTED gate: "at least one Evidence Object with
    confidence in {medium, high} supports the candidate." Every gap
    candidate from all three Hybrid Gap Engine sources (gap_detector.py's
    semantic gaps, deterministic_gap_patterns.py, graph_structural_gaps.py)
    already carries a top-level `confidence` field for exactly this
    purpose -- reused here rather than re-deriving it from a fresh
    Evidence Object cross-reference, which would be a much larger,
    separate piece of work not needed to satisfy this specific gate."""
    return gap.get("confidence") in ("medium", "high")


def generate_query_families(gap: dict, domain_config: dict = None) -> list[str]:
    """§5.1's "query-planning -> query-expansion" step, and §4's mention of
    "synonyms/terminology/broader-narrower" -- implemented deterministically
    (no LLM call) as 2-3 distinct query strings from the gap's own already-
    extracted text, not a semantic paraphrase. Returns 2 or 3 non-empty,
    de-duplicated queries."""
    title = (gap.get("title") or "").strip()
    missing = (gap.get("missing_connection") or "").strip()
    description = (gap.get("description") or "").strip()

    families = []

    specific = _truncate_at_word_boundary(f"{title} {missing}".strip() or title, 120)
    if specific:
        families.append(specific)

    broader = _truncate_at_word_boundary(title, 120)
    if broader and broader not in families:
        families.append(broader)

    if domain_config:
        boost_terms = domain_config.get("search_boost_terms", [])
        if boost_terms:
            gap_lower = title.lower()
            relevant = [t for t in boost_terms if any(w in gap_lower for w in t.split())]
            boost = relevant[0] if relevant else boost_terms[0]
            boosted = _truncate_at_word_boundary(f"{specific or title} {boost}", 150)
            if boosted and boosted not in families:
                families.append(boosted)

    if not families and description:
        families.append(_truncate_at_word_boundary(description, 120))

    return families


def _dedupe_by_title(papers: list) -> list:
    seen = set()
    out = []
    for p in papers:
        key = (p.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def run_search_funnel(query_families: list[str], ss_api_key: str = "",
                       per_query_limit: int = 5) -> dict:
    """§5.1's SEARCHED state: "full query-planning -> query-expansion ->
    multi-provider search -> dedup -> rerank funnel has executed." No
    reranker exists yet (Epic 3.5, needs embeddings/Qdrant -- not
    available on this machine); dedup is by normalized title, the same
    identity key the rest of this codebase already uses for reference
    dedup (pipeline/reference_extractor.py).

    Returns a funnel dict recording every stage per §5.3's inspectability
    requirement: query families used, providers queried, candidate count,
    post-dedup count, and the deduped candidate list itself.
    """
    provider_success = {p: False for p in _PROVIDERS}
    all_candidates = []

    for query in query_families:
        ss_results, ss_ok = _search_semantic_scholar_with_status(query, limit=per_query_limit, api_key=ss_api_key)
        if ss_ok:
            provider_success["semantic_scholar"] = True
        all_candidates.extend(ss_results)

        arxiv_results, arxiv_ok = _search_arxiv_with_status(query, limit=max(2, per_query_limit // 2))
        if arxiv_ok:
            provider_success["arxiv"] = True
        all_candidates.extend(arxiv_results)

    deduped = _dedupe_by_title(all_candidates)

    providers_responded = sum(1 for ok in provider_success.values() if ok)
    query_family_execution_rate = 1.0 if query_families else 0.0
    provider_response_rate = providers_responded / len(_PROVIDERS)
    # §5.2's exact formula: fraction of planned query families executed x
    # fraction of queried providers that responded successfully. Every
    # planned query family IS executed here (no batching/rate-limit queue
    # yet), so that factor is always 1.0 today -- kept as an explicit,
    # separate factor (not simplified away) so a future queued/batched
    # search path can populate it honestly without changing this formula.
    search_coverage_score = round(query_family_execution_rate * provider_response_rate, 3)

    return {
        "query_families": query_families,
        "providers_queried": list(_PROVIDERS),
        "provider_success": provider_success,
        "candidate_count": len(all_candidates),
        "post_dedup_count": len(deduped),
        "candidates": deduped,
        "search_coverage_score": search_coverage_score,
    }


_CHALLENGE_PROMPT = """You are assessing whether existing published work already addresses a candidate research gap.

Gap being challenged:
Title: {title}
Description: {description}

For EACH candidate paper below, judge:
- "relevant": does this paper address the gap's specific claim at all (true/false)?
- "relevance_type": "direct" (addresses the gap's specific claim) or "adjacent" (related area, doesn't directly address it) -- only set if relevant=true
- "contradicts_gap": does this paper's finding conflict with the gap's framing, OR does it conflict with another candidate paper's finding on this same question (true/false) -- only meaningful if relevant=true
- "confidence": "high", "medium", or "low" -- how confident are you this paper genuinely addresses the gap (not just keyword-matches)

Return ONLY a JSON array, one entry per candidate paper, same order as given:
[
  {{"title": "...", "relevant": true, "relevance_type": "direct", "contradicts_gap": false, "confidence": "high"}}
]

Candidates with weak/coincidental keyword overlap should be relevant=false -- do not inflate relevance to make the gap look more "solved" than it is."""


def _parse_judgments(raw: str) -> list | None:
    if not raw or not raw.strip():
        return None
    for strategy in (
        lambda s: s,
        lambda s: re.sub(r'^```(?:json)?\s*|\s*```$', '', s.strip()),
        lambda s: re.sub(r',\s*([}\]])', r'\1', s),
    ):
        try:
            result = json.loads(strategy(raw))
            if isinstance(result, list):
                return result
        except Exception:
            pass
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return result
        except Exception:
            pass
    return None


def judge_candidates(gap: dict, candidates: list, client, max_candidates: int = 8) -> list:
    """§5.1's CHALLENGED state: "relevance judgment and contradiction
    analysis have both completed against the searched results." One
    scoped LLM call for the whole candidate set (not one call per
    candidate), per the LLM-use discipline. Returns the candidates capped
    to `max_candidates`, each annotated with the judged fields; on any
    parse/call failure, every candidate gets `relevant: False` (never
    silently counted as supporting evidence it wasn't actually judged to
    provide -- a failure here must not accidentally read as CLOSED)."""
    capped = candidates[:max_candidates]
    if not capped:
        return []

    user_prompt = "Candidate papers:\n" + json.dumps(
        [{"title": c.get("title", ""), "year": c.get("year"),
          "abstract": c.get("abstract", "")} for c in capped],
        indent=2,
    )
    system_prompt = _CHALLENGE_PROMPT.format(
        title=gap.get("title", ""), description=gap.get("description", ""),
    )

    try:
        raw = unwrap(client.chat_json(system_prompt, user_prompt, max_tokens=2000))
    except Exception:
        raw = None

    judgments = _parse_judgments(raw) if raw else None

    judged = []
    for i, c in enumerate(capped):
        j = judgments[i] if judgments and i < len(judgments) and isinstance(judgments[i], dict) else {}
        judged.append({
            **c,
            "relevant": bool(j.get("relevant", False)),
            "relevance_type": j.get("relevance_type") if j.get("relevant") else None,
            "contradicts_gap": bool(j.get("contradicts_gap", False)) if j.get("relevant") else False,
            "confidence": j.get("confidence", "low"),
        })
    return judged


def apply_decision_table(search_coverage_score: float, judged_candidates: list) -> dict:
    """§5.2's terminal-status decision table, applied deterministically --
    "never left to implicit LLM judgment." Returns {status, relevant_count,
    contradiction_count, converging_count} so the funnel stays inspectable
    (§5.3), not just the final verdict."""
    if search_coverage_score < SEARCH_COVERAGE_THRESHOLD:
        return {"status": "INSUFFICIENT_EVIDENCE", "relevant_count": 0,
                "contradiction_count": 0, "converging_count": 0}

    relevant = [c for c in judged_candidates if c.get("relevant")]
    contradicting = [c for c in relevant if c.get("contradicts_gap")]
    # "independent, directly-relevant, converging, high-confidence" --
    # direct (not merely adjacent), high confidence, and not itself
    # flagged as contradicting (a contradicting result can't also count
    # toward "converging" agreement).
    converging = [
        c for c in relevant
        if c.get("relevance_type") == "direct"
        and c.get("confidence") == "high"
        and not c.get("contradicts_gap")
    ]

    relevant_count = len(relevant)
    contradiction_count = len(contradicting)
    converging_count = len(converging)

    if contradiction_count == 0 and converging_count >= CLOSED_MIN_CONVERGING:
        status = "CLOSED"
    elif contradiction_count == 0 and converging_count >= LIKELY_CLOSED_MIN_CONVERGING:
        status = "LIKELY_CLOSED"
    elif contradiction_count >= 1:
        status = "CONTESTED"
    elif relevant_count >= 1:
        status = "PARTIALLY_OPEN"
    else:
        status = "OPEN"

    return {
        "status": status,
        "relevant_count": relevant_count,
        "contradiction_count": contradiction_count,
        "converging_count": converging_count,
    }


def run_challenge(gap: dict, client, ss_api_key: str = "", domain_config: dict = None) -> dict:
    """Runs the full GENERATED -> ... -> terminal-status pipeline for one
    gap. Returns a dict with the lifecycle state reached, the terminal
    status (once CHALLENGED), and the full inspectable funnel (§5.3) --
    merged into the gap dict's own keys by the caller, not returned as a
    replacement for the gap.

    Does NOT mutate `gap` -- returns a fresh dict the caller merges in,
    consistent with how deterministic_gap_patterns.py/graph_structural_
    gaps.py build new dicts rather than mutating shared state."""
    result = {"challenger_stage_version": GAP_CHALLENGER_STAGE_VERSION}

    if not check_evidence_supported(gap):
        result["challenger_state"] = "GENERATED"
        result["challenger_status"] = None
        result["challenger_reason"] = "Failed the evidence-quality gate (confidence not medium/high) -- not promoted to search."
        return result

    result["challenger_state"] = "EVIDENCE_SUPPORTED"

    query_families = generate_query_families(gap, domain_config)
    if not query_families:
        result["challenger_state"] = "SEARCH_PENDING"
        result["challenger_status"] = None
        result["challenger_reason"] = "No usable query text could be generated from this gap."
        return result

    funnel = run_search_funnel(query_families, ss_api_key=ss_api_key)
    result["challenger_state"] = "SEARCHED"
    result["challenge_funnel"] = {
        "query_families": funnel["query_families"],
        "providers_queried": funnel["providers_queried"],
        "provider_success": funnel["provider_success"],
        "candidate_count": funnel["candidate_count"],
        "post_dedup_count": funnel["post_dedup_count"],
        "search_coverage_score": funnel["search_coverage_score"],
    }

    judged = judge_candidates(gap, funnel["candidates"], client)
    result["challenger_state"] = "CHALLENGED"

    decision = apply_decision_table(funnel["search_coverage_score"], judged)
    result["challenger_status"] = decision["status"]
    result["challenge_funnel"]["relevant_count"] = decision["relevant_count"]
    result["challenge_funnel"]["contradiction_count"] = decision["contradiction_count"]
    result["challenge_funnel"]["converging_count"] = decision["converging_count"]
    result["challenge_funnel"]["judged_candidates"] = judged[:10]

    return result
