"""
Stage 5: Gap Detector Agent
Queries the knowledge graph + wiki with domain context
to identify citation-grounded research gaps.
"""
import json
import re
from domain_config import inject_domain_into_gap_prompt
from utils.azure_client import unwrap
from pipeline.agent_config import GAP_GENERATOR
from pipeline.evidence_linker import build_paper_index, match_evidence_ids, resolve_paper_id
from packages.research_schemas.gap_identity import attach_gap_identity

# LLM evidence lines follow "Paper X (Section: Limitations): quote" (per
# GAP_DETECTION_PROMPT below) -- this extracts the leading paper reference
# so it can be resolved to a real paper_id via evidence_linker.
_EVIDENCE_LINE_PAPER_RE = re.compile(r'^\s*([^(:]+)')


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


def _link_semantic_evidence(gaps: list, wiki: dict, evidence_objects: dict) -> None:
    """Clinova Phase 4, Epic 4.4 (Scientific Lineage): walks each gap's
    free-text `evidence` lines, resolves the leading paper reference, and
    matches the quote against real Evidence Objects. Semantic gaps are
    always positive_evidence (the prompt requires "Supported by evidence
    from the papers") -- an empty motivating_evidence_ids here is a real,
    meaningful signal (the LLM claimed evidence that couldn't be traced),
    not hidden by falling back to absence_of_evidence."""
    paper_index = build_paper_index(wiki)
    for g in gaps:
        motivating = []
        for line in g.get("evidence", []) or []:
            m = _EVIDENCE_LINE_PAPER_RE.match(line or "")
            paper_ref = m.group(1).strip() if m else ""
            resolved_paper_id = resolve_paper_id(paper_ref, paper_index)
            motivating.extend(match_evidence_ids(line, resolved_paper_id, evidence_objects))
        g["motivating_evidence_ids"] = sorted(set(motivating))


def detect_gaps(wiki: dict, graph: dict, context: dict, client, domain_config: dict = None,
                 evidence_objects: dict = None) -> list:
    """
    Main gap detection: uses wiki + graph + domain context to find research gaps.
    Every gap is grounded with citations.
    """
    pages = wiki.get("pages", [])
    communities = graph.get("communities", [])
    # Orphan concepts and missing bridges are deliberately NOT fed into this
    # prompt (Clinova Phase 3, Epic 3.2 fix, 2026-08-21): they're now
    # independently promoted to their own tagged candidate gaps by
    # pipeline/graph_structural_gaps.py, which app.py's Stage 4 already
    # merges alongside this function's output. Feeding the same raw signal
    # into the semantic LLM call too meant it would often re-derive a
    # differently-worded gap about the identical underlying signal,
    # producing near-duplicate gaps across the two supposedly-distinct
    # Hybrid Gap Engine sources. Communities/conflicts/complementary pairs
    # below are NOT duplicated by the graph-structural source, so they stay.
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
    raw = unwrap(client.chat_json(
        prompt_system, user_prompt, max_tokens=GAP_GENERATOR.max_tokens,
        timeout_seconds=GAP_GENERATOR.timeout_seconds, max_retries=GAP_GENERATOR.max_retries,
    ))
    gaps, parse_failed = _parse_gaps_response(raw)

    if parse_failed:
        raw_retry = unwrap(client.chat_json(
            prompt_system, user_prompt, max_tokens=GAP_GENERATOR.max_tokens,
            timeout_seconds=GAP_GENERATOR.timeout_seconds, max_retries=GAP_GENERATOR.max_retries,
        ))
        gaps, parse_failed = _parse_gaps_response(raw_retry)
        if parse_failed:
            preview = (raw_retry or raw or "")[:1000]
            raise GapDetectionError(
                "Gap detection response could not be parsed as a JSON gap "
                "list after 2 attempts -- not a genuine zero-gap result.",
                raw_response_preview=preview,
            )

    # Attach validation placeholder. `source`/`pattern_id` mirror the shape
    # pipeline/deterministic_gap_patterns.py's output uses (Clinova Phase 3,
    # Epic 3.2's Hybrid Gap Engine) so every gap -- LLM- or rule-produced --
    # is tagged with its contributing source, per 04-ai-research-
    # architecture.md §4 ("every candidate gap emitted carries which of the
    # three sources contributed to it").
    for g in gaps:
        g["validation_status"] = "pending"
        g["existing_papers"] = []
        g.setdefault("source", "semantic")
        g.setdefault("pattern_id", None)
        attach_gap_identity(g, evidence_basis="positive_evidence")

    if evidence_objects is not None:
        _link_semantic_evidence(gaps, wiki, evidence_objects)

    return gaps
