"""
Stage 7: Research Proposal Generator
Generates 3-5 concrete, actionable research paper proposals
from validated gaps. Each proposal is citation-grounded.
"""
import difflib
import json
import re
from domain_config import inject_domain_into_proposal_prompt
from utils.azure_client import unwrap

# How many leading hex chars of gap_id to expose to the LLM as a copyable
# token (Clinova Phase 4, Epic 4.4). Full gap_id is 64 hex chars -- an LLM
# copying a 12-char token verbatim is far more reliable than a full hash,
# and prefix-uniqueness is trivially checkable for the <=6 gaps ever put
# in one prompt (see GAP_REF_LEN's use in _resolve_addresses_gap()).
GAP_REF_LEN = 12


PROPOSAL_SYSTEM_PROMPT = """You are a senior research advisor helping generate concrete, fundable research paper proposals.

Each proposal must be:
- Specific and actionable (a PhD student could implement this)
- Grounded in the analyzed papers (cite them)
- Filling a validated open or partial gap
- Novel but realistic in scope

Return ONLY a JSON array:
[
  {{
    "title": "Proposed paper title (specific, academic-style)",
    "problem_statement": "2-3 sentences: what exact problem does this paper solve and why does it matter?",
    "methodology": "Specific technical approach: what methods, models, data, experiments would be used",
    "novelty": "What makes this different from existing work (reference the gap evidence)",
    "builds_on": ["List of source paper titles this directly builds upon"],
    "addresses_gap": "Which gap (by title) this proposal addresses",
    "addresses_gap_ref": "The gap_ref token, copied EXACTLY from the Validated Research Gaps list",
    "expected_contribution": "What the field gains if this paper succeeds",
    "suggested_experiments": ["3-4 specific experiments to validate the approach"],
    "potential_datasets": ["Datasets that could be used"],
    "confidence": "high|medium|low",
    "effort_estimate": "short (1-3 months) | medium (3-6 months) | long (6-12 months)",
    "risk": "low|medium|high — technical risk assessment"
  }}
]"""


def _normalize_title(text) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


TITLE_MATCH_RATIO = 0.6


def _resolve_addresses_gap(proposals: list, actionable_gaps: list) -> None:
    """Clinova Phase 4, Epic 4.4 (Scientific Lineage): turns the LLM's
    free-text/copied gap reference into a validated foreign key. An LLM
    copying a token correctly is never guaranteed, so this never trusts
    the raw output alone -- three-way resolution, in order:
      1. addresses_gap_ref exactly matches a real gap_id's prefix in this
         run -> "llm_exact".
      2. else addresses_gap (title text) matches a gap's title, normalized
         exact first, then the best difflib ratio >= TITLE_MATCH_RATIO ->
         "title_match".
      3. else addresses_gap_id = None, resolution = "unresolved" -- the
         failure mode is explicit and inspectable, never hidden by
         silently picking the closest-sounding gap.
    Mutates each proposal in place, adding addresses_gap_id/
    addresses_gap_id_resolution."""
    ref_by_prefix = {(g.get("gap_id") or "")[:GAP_REF_LEN]: g.get("gap_id")
                      for g in actionable_gaps if g.get("gap_id")}
    by_title = {_normalize_title(g.get("title")): g.get("gap_id")
                for g in actionable_gaps if g.get("title") and g.get("gap_id")}

    for p in proposals:
        ref = str(p.get("addresses_gap_ref") or "").strip()
        if ref and ref in ref_by_prefix:
            p["addresses_gap_id"] = ref_by_prefix[ref]
            p["addresses_gap_id_resolution"] = "llm_exact"
            continue

        title_norm = _normalize_title(p.get("addresses_gap"))
        if title_norm and title_norm in by_title:
            p["addresses_gap_id"] = by_title[title_norm]
            p["addresses_gap_id_resolution"] = "title_match"
            continue

        best_ratio, best_gap_id = 0.0, None
        for candidate_title, gap_id in by_title.items():
            ratio = difflib.SequenceMatcher(None, title_norm, candidate_title).ratio()
            if ratio > best_ratio:
                best_ratio, best_gap_id = ratio, gap_id
        if best_ratio >= TITLE_MATCH_RATIO:
            p["addresses_gap_id"] = best_gap_id
            p["addresses_gap_id_resolution"] = "title_match"
        else:
            p["addresses_gap_id"] = None
            p["addresses_gap_id_resolution"] = "unresolved"


def generate_proposals(gaps: list, wiki: dict, context: dict, client, domain_config: dict = None) -> list:
    """
    Generate research proposals from validated open/partial gaps.
    """
    # B19 fix: an empty `gaps` list means gap detection found nothing to
    # build proposals from. Calling the LLM anyway invites it to fabricate
    # proposals ungrounded in any actual gap -- live-reproduced 2026-08-20
    # (see evals/benchmarks/baseline/phase0-findings.md): a 0-gap run still
    # produced 4 specific, plausible-sounding, entirely invented proposals.
    # Return early instead of ever sending an empty gap list to the LLM.
    if not gaps:
        return []

    # Only generate proposals for open or partial gaps
    actionable_gaps = [
        g for g in gaps
        if g.get("validation_status") in ["open", "partial"]
    ]

    if not actionable_gaps:
        # Fall back to all gaps only when every gap is explicitly marked
        # solved -- any other status (missing, unknown, malformed) must not
        # silently widen the proposal set beyond open/partial gaps.
        if all(g.get("validation_status") == "solved" for g in gaps):
            actionable_gaps = gaps
        else:
            return []

    # Compact wiki context
    pages = wiki.get("pages", [])
    paper_summaries = [
        {
            "title": p.get("title", p.get("source_file", "Unknown")),
            "methods": p.get("methods", []),
            "datasets": p.get("datasets", []),
            "contributions": p.get("contributions", []),
        }
        for p in pages
    ]

    # Build gap summaries for proposal generation
    gap_summaries = [
        {
            "title": g.get("title"),
            "description": g.get("description"),
            "evidence": g.get("evidence", []),
            "gap_type": g.get("gap_type"),
            "validation_status": g.get("validation_status"),
            "missing_connection": g.get("missing_connection"),
            "why_important": g.get("why_important"),
            # Clinova Phase 4, Epic 4.4 (Scientific Lineage): a copyable
            # token for the resolver below -- None (never fabricated) for
            # a gap predating Epic 4.4's identity fields.
            "gap_ref": (g.get("gap_id") or "")[:GAP_REF_LEN] or None,
        }
        for g in actionable_gaps[:6]  # Cap at 6 gaps to keep prompt manageable
    ]

    user_prompt = f"""Research Context:
- Domain: {context.get('domain', 'General AI/ML')}
- Researcher Interest: {context.get('interest', 'General')}

Source Papers Available to Build On:
{json.dumps(paper_summaries, indent=2)}

Validated Research Gaps:
{json.dumps(gap_summaries, indent=2)}

Generate 3-5 concrete research paper proposals. 
Prioritize gaps marked as 'open' over 'partial'.
Make proposals specific enough that a researcher could begin working on them immediately."""

    # B30 fix (2026-09-08): this call was hitting the default 120s
    # timeout/2-retries/5000-max_tokens repeatedly in real runs (3
    # consecutive live failures at exactly this stage this session, with
    # 3 different immediate symptoms -- a dead fallback model, a plain
    # timeout, then a mid-stream deadline timeout -- pointing at the same
    # underlying cause: this call is genuinely the heaviest single LLM call
    # in the pipeline, not a model-specific fluke). Generating up to 5
    # detailed multi-field proposals from a "thinking" model (which spends
    # real max_tokens budget on hidden reasoning_content before any real
    # JSON, per B24's same finding for knowledge-graph extraction) needs
    # more of both than the shared chat_json() defaults give it. Raised
    # to 300s/3 retries/10000 tokens -- generous headroom, not a precise
    # measurement (no successful timing sample exists yet to measure
    # against), consistent with B24's own "measure later, add margin now"
    # approach when no real measurement exists.
    raw = unwrap(client.chat_json(
        inject_domain_into_proposal_prompt(PROPOSAL_SYSTEM_PROMPT, domain_config or {}),
        user_prompt, max_tokens=10000, timeout_seconds=300, max_retries=3
    ))

    try:
        proposals = json.loads(raw)
        if not isinstance(proposals, list):
            proposals = []
    except json.JSONDecodeError:
        import re
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            try:
                proposals = json.loads(match.group())
            except Exception:
                proposals = []
        else:
            proposals = []

    _resolve_addresses_gap(proposals, actionable_gaps)
    return proposals
