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
    # "unverified" (the literature search was unavailable) is still actionable: not knowing
    # whether a gap is solved is not a reason to drop it.
    actionable_gaps = [
        g for g in gaps
        if g.get("validation_status") in ["open", "partial", "unverified"]
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
    system_prompt = inject_domain_into_proposal_prompt(PROPOSAL_SYSTEM_PROMPT, domain_config or {})
    proposals = []
    # Two attempts: a reply that arrives but cannot be read (fenced, wrapped in
    # an object, cut off) is a sampling accident, and a second sample almost
    # always parses. Seen in a real Gemini run: 4.5k tokens spent, 0 proposals.
    for _attempt in range(2):
        raw = unwrap(client.chat_json(
            system_prompt, user_prompt, max_tokens=10000, timeout_seconds=300, max_retries=3
        ))
        proposals = _parse_proposals(raw)
        if proposals or not (raw or "").strip():
            break

    _resolve_addresses_gap(proposals, actionable_gaps)
    return proposals


_REVIEWER_PROMPT = """You are a skeptical grant-panel reviewer. You are given research proposals, each with the research gap it addresses, the evidence behind that gap (quotes from the source papers), and what an academic search found already exists on that gap.

For EACH proposal give integer scores 1-5 for:
- specificity: concrete population/system, methods, measurements and scope (5) versus vague (1)
- novelty: not already done by the existing papers listed and not an obvious step (5) versus already done (1)
- feasibility: a small team could carry it out in 6-12 months with available methods and data (5) versus not (1)
- impact: would change understanding or practice if it worked (5) versus minor (1)
and a verdict:
- "accept": strong as written.
- "revise": a good core with fixable problems. Put concrete, specific fixes in "required_changes".
- "reject": generic, already done, unsupported by its gap evidence, or infeasible. Give a "reason".
SCORING ANCHORS. Use the whole 1-5 range and do NOT give every proposal the same scores: if two proposals truly are equal, say why in "issues".
- specificity: 1 = names a topic only ("study CFTR in chips"); 3 = names a system and a method but not the measurements or sample; 5 = names the population or model system, the intervention, the readouts and the comparison.
- novelty: 1 = a listed existing paper already does it; 3 = a variation on existing work; 5 = nothing listed does it and it is not an obvious next step.
- feasibility: 1 = needs resources a small team cannot get; 3 = doable with new data collection; 5 = doable with materials and methods the cited papers already describe.
- impact: 1 = a minor refinement; 3 = would strengthen a subfield; 5 = would change practice or understanding.
Example of a weak proposal (specificity 2, novelty 2, impact 2 -> "reject" or "revise"): "Use machine learning to improve outcomes in cystic fibrosis."
Example of a strong proposal (specificity 5, novelty 4, feasibility 4, impact 4 -> "accept"): a named airway-chip infection model, a named modulator at stated doses, ciliary beat frequency and bacterial load as readouts, compared against untreated chips.
Also list the main "issues" (short phrases).

Return ONLY JSON: {"reviews": [ {"index": 0, "specificity": 4, "novelty": 3, "feasibility": 4, "impact": 4, "verdict": "accept|revise|reject", "issues": ["..."], "required_changes": "", "reason": ""} ]}
Review every proposal index exactly once."""


def _gap_context_for(proposal: dict, gaps_by_id: dict) -> dict:
    g = gaps_by_id.get(proposal.get("addresses_gap_id")) or {}
    return {
        "gap": g.get("title") or proposal.get("addresses_gap"),
        "gap_description": g.get("description", ""),
        "gap_evidence": (g.get("evidence") or [])[:4],
        "validation": g.get("validation_status"),
        "already_found_by_search": [p.get("title") for p in (g.get("existing_papers") or [])[:5]],
    }


def review_proposals(proposals: list, gaps: list, client, domain_config: dict = None,
                     feedback_text: str = "") -> tuple[list, dict]:
    """Proposal Reviewer agent + one revision pass. Returns (proposals, diagnostics).
    Each kept proposal gets `review` = {scores, verdict, issues}; "reject" proposals are removed
    (listed in diagnostics), "revise" ones are rewritten once from the reviewer's required changes.
    A failed review never loses proposals: they are returned unreviewed with the reason recorded."""
    from pipeline.agent_config import PROPOSAL_REVIEWER
    from utils.azure_client import LLMCallError
    import re
    diag = {"reviewed": 0, "accepted": 0, "revised": 0, "rejected": [], "error": None}
    if not proposals:
        return proposals, diag
    gaps_by_id = {g.get("gap_id"): g for g in gaps if g.get("gap_id")}
    brief = [{"index": i, "title": p.get("title"), "problem_statement": p.get("problem_statement"),
              "methodology": p.get("methodology"), "novelty_claim": p.get("novelty"),
              **_gap_context_for(p, gaps_by_id)} for i, p in enumerate(proposals)]

    client.set_stage("Stage 6b — Proposal Review")
    try:
        raw = unwrap(client.chat_json(_REVIEWER_PROMPT,
                                      "Proposals to review:\n" + json.dumps(brief, indent=1, ensure_ascii=False)
                                      + ("\n\n" + feedback_text if feedback_text else ""),
                                      max_tokens=PROPOSAL_REVIEWER.max_tokens, timeout_seconds=PROPOSAL_REVIEWER.timeout_seconds,
                                      max_retries=PROPOSAL_REVIEWER.max_retries))
    except LLMCallError as e:
        diag["error"] = f"review failed: {e.error.kind}"
        return proposals, diag
    text = re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$', '', (raw or "").strip())
    reviews = None
    for candidate in (text, re.sub(r',\s*([}\]])', r'\1', text)):
        try:
            value = json.loads(candidate)
            reviews = value.get("reviews") if isinstance(value, dict) else value
            break
        except json.JSONDecodeError:
            continue
    if not isinstance(reviews, list):
        diag["error"] = "review reply could not be read"
        return proposals, diag
    by_index = {r.get("index"): r for r in reviews if isinstance(r, dict)}

    kept, to_revise = [], []
    for i, p in enumerate(proposals):
        r = by_index.get(i)
        if not r:
            kept.append(p)
            continue
        diag["reviewed"] += 1
        verdict = r.get("verdict") if r.get("verdict") in ("accept", "revise", "reject") else "accept"
        p["review"] = {"verdict": verdict, "issues": r.get("issues") or [],
                       "scores": {k: r.get(k) for k in ("specificity", "novelty", "feasibility", "impact")}}
        if verdict == "reject":
            diag["rejected"].append({"title": p.get("title"), "reason": r.get("reason") or "rejected by the reviewer"})
            continue
        if verdict == "revise" and r.get("required_changes"):
            to_revise.append((len(kept), r["required_changes"]))
        else:
            diag["accepted"] += 1
        kept.append(p)

    if to_revise:
        client.set_stage("Stage 6 — Proposals")
        for pos, changes in to_revise:
            original = kept[pos]
            try:
                raw = unwrap(client.chat_json(
                    inject_domain_into_proposal_prompt(PROPOSAL_SYSTEM_PROMPT, domain_config or {}),
                    "Rewrite this ONE proposal so that it fully addresses the reviewer's required changes. "
                    "Keep it grounded in the same gap. Return a JSON array with exactly one proposal.\n\n"
                    f"PROPOSAL:\n{json.dumps({k: v for k, v in original.items() if k != 'review'}, ensure_ascii=False)}\n\n"
                    f"REVIEWER'S REQUIRED CHANGES:\n{changes}",
                    max_tokens=PROPOSAL_REVIEWER.max_tokens, timeout_seconds=PROPOSAL_REVIEWER.timeout_seconds,
                    max_retries=PROPOSAL_REVIEWER.max_retries))
            except LLMCallError:
                continue                              # keep the original rather than lose it
            revised = _parse_proposals(raw)
            if revised:
                new = revised[0]
                for keep_key in ("addresses_gap_id", "addresses_gap_id_resolution", "addresses_gap_ref", "addresses_gap"):
                    if original.get(keep_key) is not None:
                        new[keep_key] = original[keep_key]
                new["review"] = {**original["review"], "revised": True, "required_changes": changes}
                kept[pos] = new
                diag["revised"] += 1
    return kept, diag


def _parse_proposals(raw: str) -> list:
    """The list of proposal dicts in a model reply, tolerating the shapes models
    really return: a bare JSON list, a ```json fence, an object wrapping the list
    ({"proposals": [...]}), or a list cut off mid-way (the complete objects before
    the cut are kept). Returns [] when nothing usable is there."""
    import re
    text = re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$', '', (raw or "").strip())

    def _from(value):
        if isinstance(value, list):
            return [p for p in value if isinstance(p, dict)]
        if isinstance(value, dict):
            for key in ("proposals", "research_proposals", "results", "items"):
                if isinstance(value.get(key), list):
                    return _from(value[key])
            for v in value.values():                      # any single list of objects
                if isinstance(v, list) and v and all(isinstance(p, dict) for p in v):
                    return v
            if value.get("title"):                        # one proposal returned alone
                return [value]
        return []

    try:
        found = _from(json.loads(text))
        if found:
            return found
    except json.JSONDecodeError:
        pass
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            found = _from(json.loads(match.group()))
            if found:
                return found
        except json.JSONDecodeError:
            pass
    # Truncated list: keep every complete {...} object that has a title.
    decoder, found, pos = json.JSONDecoder(), [], text.find("[") + 1
    while pos > 0:
        start = text.find("{", pos)
        if start == -1:
            break
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict) and obj.get("title"):
            found.append(obj)
        pos = end
    return found
