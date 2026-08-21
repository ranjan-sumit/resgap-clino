"""
Stage 5: Gap Detector Agent
Queries the knowledge graph + wiki with domain context
to identify citation-grounded research gaps.
"""
import json
import re
from domain_config import inject_domain_into_gap_prompt
from utils.azure_client import unwrap


class GapDetectionError(Exception):
    """B19 fix: raised when detect_gaps cannot obtain a parseable gap list
    from the LLM after retrying once. Distinct from a genuine empty result --
    previously a parse failure silently became `gaps = []`, indistinguishable
    from the LLM genuinely finding zero gaps, and that silent empty list then
    flowed into generate_proposals, which fabricated proposals from nothing
    (see evals/benchmarks/baseline/phase0-findings.md, 2026-08-20 zero-gap-
    silent-fabrication finding)."""
    def __init__(self, message: str, raw_response_preview: str = ""):
        super().__init__(message)
        self.raw_response_preview = raw_response_preview


def _parse_gaps_response(raw: str):
    """Returns (gaps, parse_failed). parse_failed=True means `raw` could not
    be interpreted as a JSON list by any of the three fallback strategies --
    distinct from a genuinely-empty `[]` response, which returns
    ([], False)."""
    if not raw or not raw.strip():
        return None, True
    for strategy in (
        lambda s: s,
        lambda s: re.sub(r'^```(?:json)?\s*|\s*```$', '', s.strip()),
        lambda s: re.sub(r',\s*([}\]])', r'\1', s),
    ):
        try:
            result = json.loads(strategy(raw))
            if isinstance(result, list):
                return result, False
        except Exception:
            pass
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return result, False
        except Exception:
            pass
    return None, True


GAP_DETECTION_PROMPT = """You are an expert research gap analyst. Your task is to identify genuine, specific, and actionable research gaps from a set of analyzed papers.

Researcher Context:
- Domain: {domain}
- Research Interest: {interest}
- Gap Type Focus: {gap_type}

You have access to:
1. Compiled wiki pages from {n_papers} papers
2. Knowledge graph with entities and communities
3. Orphan concepts (mentioned once, never built upon)
4. Missing bridges (limitations in one paper that could be solved by another)

A GOOD research gap must be:
- Specific and actionable (not "more research needed")
- Supported by evidence from the papers
- Not already the main contribution of one of the papers
- Feasible (something a PhD student could actually work on)

Return ONLY a JSON array of gaps:
[
  {{
    "title": "Short descriptive title of the gap",
    "description": "2-3 sentence specific description of what is missing and why it matters",
    "gap_type": "methodology|application|dataset|evaluation|theory|benchmark",
    "confidence": "high|medium|low",
    "evidence": [
      "Paper X (Section: Limitations): exact quote or paraphrase",
      "Paper Y (Section: Future Work): exact quote or paraphrase"
    ],
    "supporting_papers": ["paper title 1", "paper title 2"],
    "missing_connection": "What concept/method/application combination is absent",
    "why_important": "Why filling this gap would matter to the field"
  }}
]"""


def detect_gaps(wiki: dict, graph: dict, context: dict, client, domain_config: dict = None) -> list:
    """
    Main gap detection: uses wiki + graph + domain context to find research gaps.
    Every gap is grounded with citations.
    """
    pages = wiki.get("pages", [])
    communities = graph.get("communities", [])
    orphans = graph.get("orphan_concepts", [])
    bridges = graph.get("missing_bridges", [])
    cross_links = wiki.get("cross_links", {})

    # Build comprehensive context for the detector
    wiki_summary = []
    for p in pages:
        wiki_summary.append({
            "title": p.get("title", p.get("source_file", "Unknown")),
            "contributions": p.get("contributions", []),
            "methods": p.get("methods", []),
            "limitations": p.get("limitations", []),
            "future_work": p.get("future_work", []),
            "evaluated_on": p.get("evaluated_on", []),
            "comparison_gap": p.get("comparison_gap", ""),
        })

    community_summary = [
        {
            "theme": c.get("theme", ""),
            "summary": c.get("summary", ""),
            "gap_signal": c.get("gap_signal", ""),
        }
        for c in communities
    ]

    orphan_signals = [o.get("signal", "") for o in orphans[:10]]
    bridge_signals = [b.get("description", "") for b in bridges[:10]]
    conflicts = cross_links.get("conflicts", [])
    complementary = cross_links.get("complementary_pairs", [])

    prompt_system = inject_domain_into_gap_prompt(
        GAP_DETECTION_PROMPT.format(
            domain=context.get("domain", "General AI/ML"),
            interest=context.get("interest", "General research"),
            gap_type=context.get("gap_type", "Any"),
            n_papers=len(pages),
        ),
        domain_config or {}
    )

    user_prompt = f"""WIKI PAGES (per-paper compiled knowledge):
{json.dumps(wiki_summary, indent=2)}

KNOWLEDGE GRAPH COMMUNITIES:
{json.dumps(community_summary, indent=2)}

ORPHAN CONCEPTS (mentioned but not built upon):
{json.dumps(orphan_signals, indent=2)}

MISSING BRIDGES (limitations that could be solved cross-paper):
{json.dumps(bridge_signals, indent=2)}

COMPLEMENTARY PAPER PAIRS:
{json.dumps(complementary, indent=2)}

CONFLICTS BETWEEN PAPERS:
{json.dumps(conflicts, indent=2)}

Based on all this, identify 4-7 specific, evidence-grounded research gaps.
Prioritize gaps aligned with the researcher's domain: {context.get('domain', 'General AI/ML')}"""

    # B19 fix: retry once on a genuine parse failure before giving up --
    # gap-detection output is nondeterministic (live-reproduced: an identical
    # retry recovered a valid 5-gap response after one parse failure), so a
    # single retry has real recovery value. If both attempts fail to parse,
    # raise explicitly rather than silently returning [] -- a parse failure
    # must never be indistinguishable from "the LLM found zero gaps."
    raw = unwrap(client.chat_json(prompt_system, user_prompt, max_tokens=4000))
    gaps, parse_failed = _parse_gaps_response(raw)

    if parse_failed:
        raw_retry = unwrap(client.chat_json(prompt_system, user_prompt, max_tokens=4000))
        gaps, parse_failed = _parse_gaps_response(raw_retry)
        if parse_failed:
            preview = (raw_retry or raw or "")[:1000]
            raise GapDetectionError(
                "Gap detection response could not be parsed as a JSON gap "
                "list after 2 attempts -- not a genuine zero-gap result.",
                raw_response_preview=preview,
            )

    # Attach validation placeholder
    for g in gaps:
        g["validation_status"] = "pending"
        g["existing_papers"] = []

    return gaps
