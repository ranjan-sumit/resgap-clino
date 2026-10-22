"""
Agentic gap detection (Stage 4).

The earlier Stage 4 made ONE model call over the wiki summary and asked for 4-7 gaps,
then padded the list with rule-based and graph-template gaps that did not look at what
each paper actually is. This replaces it with a small team of agents that work from the
quoted evidence the Evidence Reader produced:

  finders (run in parallel, each a different lens)
    - limitation_miner        starts from what the authors themselves say is limited / future work
    - cross_paper_synthesizer looks ACROSS papers: uncombined methods, conflicts, bridges
    - methodology_auditor     one call per paper, using a checklist that fits THAT paper's
                              study type (a review is not audited like a prediction model)
  critic (the "Methodology Critic" the architecture notes call for, previously absent)
    - scores every candidate for novelty, importance, feasibility, merges duplicates, drops
      generic or already-answered ones, and may sharpen a vague title

Grounding is enforced in code, not trusted: a finder cites evidence handles (E1a2b3c4); a
handle that does not exist in the brief is discarded, and the gap's evidence lines are
rebuilt from the verified quotes. A non-audit gap with no valid handle is dropped.
Rule-based pattern gaps and graph-template gaps are no longer mixed into the main list;
the caller keeps them as a separate "supplementary" list.
"""
import difflib
import json
import re
from concurrent.futures import ThreadPoolExecutor

from pipeline.agent_config import GAP_CRITIC, GAP_FINDER
from packages.research_schemas.gap_identity import attach_gap_identity
from utils.azure_client import LLMCallError, unwrap

MAX_GAPS = 12
LENSES = ("limitation_miner", "cross_paper_synthesizer", "methodology_auditor")
_DUPLICATE_RATIO = 0.74

_CHECKLISTS = {
    "ml_prediction_model": (
        "external validation on an independent site/cohort; calibration; temporal or dataset-shift "
        "validation; subgroup performance and fairness; sample size / events-per-variable; missing-data "
        "handling; comparison with a standard-of-care or strong baseline; explainability; prospective or "
        "deployment evidence; data and code availability; class imbalance handling"),
    "clinical_trial": (
        "sample size and power; randomisation, blinding and allocation concealment; confounding; "
        "follow-up length; generalisability and population diversity; choice of endpoints; safety and "
        "adverse-event reporting; comparison with the standard of care"),
    "observational_clinical": (
        "selection bias; confounding control; sample size; follow-up length; generalisability and "
        "population diversity; measurement validity; causal vs associational claims"),
    "in_vitro_or_lab": (
        "number of donors / biological replicates; controls and benchmark against in-vivo or patient data; "
        "physiological relevance and what is not modelled; throughput and standardisation; long-term "
        "stability; validation with a second cell source or perturbation; reproducibility across labs"),
    "systematic_or_narrative_review": (
        "transparency of search and selection; quality appraisal of included studies; recency; "
        "subtopics or populations left out; absence of quantitative synthesis; conflicting evidence "
        "not reconciled"),
    "survey_or_questionnaire": (
        "sampling frame and response bias; validation of the instrument; respondent expertise; "
        "stated opinion versus objective data; follow-up over time; geographic or demographic balance"),
    "computational_simulation": (
        "validation against real data; sensitivity and uncertainty analysis; source of parameters; "
        "reproducibility; comparison with alternative models"),
    "other": (
        "whether the central claim is tested against an independent comparison; sample size; "
        "generalisability; reproducibility"),
}

_COMMON_RULES = """Rules for every gap you propose:
- A gap is something specific that the papers here do not yet do, test or know, and that a research project could address. It is NOT "more research is needed", NOT a restatement of what a paper already did, and NOT something another paper in this set already answers.
- Ground every gap. In "evidence_refs" list the handles (like E1a2b3c4) of the evidence items it rests on, copied exactly from the brief. Only handles that appear in the brief are accepted.
- Be specific: name the population, method, outcome or comparison that is missing.
- Return ONLY JSON: {"gaps": [ {"title": "...", "description": "2-3 sentences: what is missing and why it matters", "gap_type": "methodology|application|dataset|evaluation|theory|benchmark", "confidence": "high|medium|low", "evidence_refs": ["E..."], "supporting_papers": ["paper title", ...], "missing_connection": "the combination or element that is absent", "why_important": "1-2 sentences"} ]}
- If you find nothing that meets this bar, return {"gaps": []}. Do not pad."""

_FINDER_PROMPTS = {
    "limitation_miner": """You are a Limitation Miner on a research-gap team.
Start from what the authors THEMSELVES flag: items of type Limitation and FutureWork, and results they describe as preliminary or uncertain. For each strong one, decide whether it is a researchable gap and whether anything else in these papers already addresses it. Propose up to 5 gaps.
""",
    "cross_paper_synthesizer": """You are a Cross-Paper Synthesizer on a research-gap team.
Look ACROSS the papers, not inside one: methods or models that were never combined; a population, condition or organism one paper studies that another overlooks; results that conflict and need resolving; a limitation in one paper that another paper's method could address; an evaluation that exists for each part but never for the combination. Every gap you propose must involve at least two papers. Propose up to 5 gaps.
""",
    "methodology_auditor": """You are a Methodology Auditor on a research-gap team, reviewing ONE paper like a careful peer reviewer.
The study type of this paper is: {study_type}. Checklist that fits this study type (use only what fits; skip what does not apply to this design): {checklist}.
Name up to 3 weaknesses that point to a gap OTHER researchers could fill, each resting on what this paper reports or omits. Never apply a checklist item that does not make sense for this design (for example, a review has no calibration curve).
""",
}

_CRITIC_PROMPT = """You are the Methodology Critic and research chair for a research-gap analysis. Several finders proposed candidate gaps from a small set of papers. Review them like a skeptical senior reviewer.

For EACH candidate give integer scores 1-5:
- novelty: 5 = not already done in these papers and not an obvious next step; 1 = already addressed or trivial.
- importance: 5 = would change scientific understanding or clinical practice; 1 = minor.
- feasibility: 5 = a small team could start within 6-12 months with available methods and data; 1 = needs unavailable resources.
and a verdict:
- "keep": a genuine, specific, non-trivial gap.
- "merge": the same underlying gap as another candidate; set "merge_into" to that candidate's id.
- "drop": generic ("more research"), a restatement of a paper's own contribution, already answered by the papers, or not really a gap. Give a short "reason".
Also give a one-sentence "critique" and, if the title is vague, a "sharpened_title".
When candidates are of comparable quality, prefer a final set that draws on every paper rather than clustering on one; do not keep a weak candidate just to include a paper.

Return ONLY JSON: {"reviews": [ {"id": "G1", "novelty": 4, "importance": 5, "feasibility": 3, "verdict": "keep|merge|drop", "merge_into": null, "reason": "", "critique": "...", "sharpened_title": null} ]}
Review every candidate id exactly once."""


# ── evidence brief ──────────────────────────────────────────────────────────

def _handle(ev: dict) -> str:
    return "E" + str(ev.get("evidence_id", ""))[:8]


def _loc(ev: dict) -> str:
    prov = ev.get("provenance") or {}
    bits = []
    if prov.get("page") is not None:
        bits.append(f"p.{prov['page']}")
    if prov.get("section"):
        bits.append(str(prov["section"])[:40])
    return ", ".join(bits) or "location unknown"


def _statement(ev: dict) -> str:
    text = str(ev.get("text") or "")
    if text.startswith("[study_type:"):
        text = text.split("]", 1)[-1].strip()
    return text


def _titles(wiki: dict, evidence_objects: dict) -> dict:
    """filename -> the paper's title, so gaps name papers the way a reader would."""
    out = {name: name for name in evidence_objects}
    for page in (wiki or {}).get("pages", []):
        src = page.get("source_file")
        if src in out and page.get("title"):
            out[src] = str(page["title"])
    return out


def build_brief(evidence_objects: dict, profiles: dict, titles: dict, per_paper_limit: int = 60,
                types: tuple | None = None) -> tuple[str, dict]:
    """The evidence the agents see, grouped by paper, plus {handle: (paper_id, evidence)}."""
    by_handle, blocks = {}, []
    for pid, items in evidence_objects.items():
        profile = (profiles or {}).get(pid, {}) or {}
        lines = [f"## PAPER: {titles.get(pid, pid)}  (study type: {profile.get('study_type') or 'unknown'})"]
        shown = 0
        for ev in items:
            if types and ev.get("evidence_type") not in types:
                continue
            if shown >= per_paper_limit:
                break
            quote = (ev.get("provenance") or {}).get("quote")
            h = _handle(ev)
            by_handle[h] = (pid, ev)
            lines.append(f"[{h}] {ev.get('evidence_type')} ({_loc(ev)}): {_statement(ev)}"
                         + (f'  | quote: "{quote}"' if quote else ""))
            shown += 1
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks), by_handle


# ── parsing and grounding ───────────────────────────────────────────────────

def _parse_list(raw: str, key: str):
    text = re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$', '', (raw or "").strip())
    for candidate in (text, re.sub(r',\s*([}\]])', r'\1', text)):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get(key), list):
            return [x for x in value[key] if isinstance(x, dict)]
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            value = json.loads(match.group())
            if isinstance(value, dict) and isinstance(value.get(key), list):
                return [x for x in value[key] if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass
    return None


def _ground(gap: dict, by_handle: dict, titles: dict, lens: str, audited_paper: str | None,
            require_quote: bool = False) -> bool:
    """Rebuild the gap's evidence from VERIFIED handles. Returns False if it should be dropped.
    With require_quote, only evidence that carries a verified quote counts as grounding (an
    unquoted bookkeeping item such as the study-type note is context, not evidence)."""
    refs = [h for h in (gap.get("evidence_refs") or []) if isinstance(h, str) and h in by_handle]
    if require_quote:
        refs = [h for h in refs if (by_handle[h][1].get("provenance") or {}).get("quote")]
    seen, lines, ids, papers = set(), [], [], []
    for h in refs:
        if h in seen:
            continue
        seen.add(h)
        pid, ev = by_handle[h]
        ids.append(ev["evidence_id"])
        title = titles.get(pid, pid)
        if title not in papers:
            papers.append(title)
        quote = (ev.get("provenance") or {}).get("quote")
        lines.append(f"{title} ({_loc(ev)}): " + (f"“{quote}”" if quote else _statement(ev)))
    gap["motivating_evidence_ids"] = ids
    gap["evidence"] = lines
    if audited_paper and titles.get(audited_paper, audited_paper) not in papers:
        papers.insert(0, titles.get(audited_paper, audited_paper))
    gap["supporting_papers"] = papers or [p for p in (gap.get("supporting_papers") or []) if isinstance(p, str)]
    gap["lens"] = lens
    if ids:
        gap["evidence_basis"] = "positive_evidence"
        return True
    if lens == "methodology_auditor" and audited_paper:
        gap["evidence_basis"] = "absence_of_evidence"        # the gap is what the paper does NOT report
        gap["evidence"] = [f"{titles.get(audited_paper, audited_paper)}: not reported in the paper "
                           f"(found by the methodology audit)"]
        return True
    return False


def _same_gap(a: dict, b: dict) -> bool:
    return difflib.SequenceMatcher(None, str(a.get("title", "")).lower(),
                                   str(b.get("title", "")).lower()).ratio() >= _DUPLICATE_RATIO


def _dedupe(gaps: list) -> list:
    """Near-identical titles collapse to the better grounded one (more quotes, then earlier lens)."""
    kept = []
    for g in sorted(gaps, key=lambda x: (-len(x.get("motivating_evidence_ids") or []), LENSES.index(x["lens"]))):
        if not any(_same_gap(g, k) for k in kept):
            kept.append(g)
    return kept


# ── agents ──────────────────────────────────────────────────────────────────

def _context_block(context: dict) -> str:
    focus = context.get("gap_type", "Any")
    return (f"Domain: {context.get('domain', 'General')}\nResearcher interest: {context.get('interest', 'General research')}"
            + (f"\nGap type focus: {focus}" if focus and focus != "Any" else ""))


def _run_finder(client, lens: str, system: str, user: str, by_handle: dict, titles: dict,
                audited_paper: str | None = None, require_quote: bool = False):
    """One finder call. Returns (gaps, diagnostics-dict). Never raises."""
    diag = {"lens": lens, "paper": audited_paper, "proposed": 0, "kept": 0, "dropped_ungrounded": 0, "error": None}
    try:
        raw = unwrap(client.chat_json(system, user, max_tokens=GAP_FINDER.max_tokens,
                                      timeout_seconds=GAP_FINDER.timeout_seconds, max_retries=GAP_FINDER.max_retries))
    except LLMCallError as e:
        diag["error"] = f"model call failed: {e.error.kind}"
        return [], diag
    items = _parse_list(raw, "gaps")
    if items is None:
        diag["error"] = "reply could not be read"
        return [], diag
    out = []
    for g in items:
        diag["proposed"] += 1
        if not str(g.get("title") or "").strip() or not str(g.get("description") or "").strip():
            diag["dropped_ungrounded"] += 1
            continue
        if _ground(g, by_handle, titles, lens, audited_paper, require_quote):
            out.append(g)
            diag["kept"] += 1
        else:
            diag["dropped_ungrounded"] += 1
    return out, diag


def _critic(client, candidates: list, feedback_text: str = ""):
    """Returns ({id: review}, error). Reviews are advisory: if the critic fails the caller ranks by grounding."""
    brief = [{"id": c["_cid"], "lens": c["lens"], "title": c["title"], "description": c["description"],
              "why_important": c.get("why_important", ""), "papers": c.get("supporting_papers", []),
              "grounded_quotes": len(c.get("motivating_evidence_ids") or [])} for c in candidates]
    try:
        user = "Candidate gaps:\n" + json.dumps(brief, indent=1, ensure_ascii=False)
        if feedback_text:
            user += "\n\n" + feedback_text
        raw = unwrap(client.chat_json(_CRITIC_PROMPT, user,
                                      max_tokens=GAP_CRITIC.max_tokens, timeout_seconds=GAP_CRITIC.timeout_seconds,
                                      max_retries=GAP_CRITIC.max_retries))
    except LLMCallError as e:
        return {}, f"model call failed: {e.error.kind}"
    reviews = _parse_list(raw, "reviews")
    if reviews is None:
        return {}, "reply could not be read"
    return {str(r.get("id")): r for r in reviews if r.get("id")}, None


def _score(review: dict | None, gap: dict) -> float:
    grounding = min(len(gap.get("motivating_evidence_ids") or []), 3) / 3 * 5
    if not review:
        return 0.3 * 3 + 0.3 * 3 + 0.2 * 3 + 0.2 * grounding           # neutral when the critic gave no scores

    def n(key):
        try:
            return max(1, min(5, int(review.get(key))))
        except (TypeError, ValueError):
            return 3
    return 0.30 * n("importance") + 0.30 * n("novelty") + 0.20 * n("feasibility") + 0.20 * grounding


def paper_support(gaps: list, evidence_objects: dict, titles: dict) -> dict:
    """{filename: number of gaps that cite it} (by supporting-paper title or filename)."""
    from pipeline.coverage import _is_paper
    return {pid: sum(1 for g in gaps if any(_is_paper(ref, pid, titles.get(pid, pid))
                                            for ref in (g.get("supporting_papers") or [])))
            for pid in evidence_objects}


def find_gaps(wiki: dict, graph: dict, context: dict, client, evidence_objects: dict,
              paper_profiles: dict | None = None, max_gaps: int = MAX_GAPS,
              feedback_items: list | None = None, feedback_text: str = "",
              min_gaps_per_paper: int = 0) -> dict:
    """Returns {"gaps": [...ranked, each with scores/critique/rank], "rejected": [...], "diagnostics": {...}}.
    Raises nothing: failed agents are recorded in diagnostics and the rest carry on."""
    paper_profiles = paper_profiles or {}
    titles = _titles(wiki, evidence_objects)
    brief, by_handle = build_brief(evidence_objects, paper_profiles, titles)
    ctx = _context_block(context)
    cross = json.dumps({k: v for k, v in (wiki or {}).get("cross_links", {}).items() if v}, indent=1, ensure_ascii=False)
    communities = json.dumps([{"theme": c.get("theme"), "summary": c.get("summary")} for c in (graph or {}).get("communities", [])],
                             indent=1, ensure_ascii=False)
    shared_user = (f"{ctx}\n\nEVIDENCE BRIEF (cite handles in evidence_refs):\n{brief}\n\n"
                   f"CROSS-PAPER LINKS FROM THE WIKI:\n{cross}\n\nKNOWLEDGE-GRAPH THEMES:\n{communities}\n")

    jobs = []   # (lens, system, user, audited_paper)
    jobs.append(("limitation_miner", _FINDER_PROMPTS["limitation_miner"] + _COMMON_RULES, shared_user, None))
    jobs.append(("cross_paper_synthesizer", _FINDER_PROMPTS["cross_paper_synthesizer"] + _COMMON_RULES, shared_user, None))
    for pid in evidence_objects:
        st = (paper_profiles.get(pid) or {}).get("study_type") or "other"
        sys_prompt = _FINDER_PROMPTS["methodology_auditor"].format(
            study_type=st, checklist=_CHECKLISTS.get(st, _CHECKLISTS["other"])) + _COMMON_RULES
        one_brief, _ = build_brief({pid: evidence_objects[pid]}, paper_profiles, titles)
        jobs.append(("methodology_auditor", sys_prompt, f"{ctx}\n\nEVIDENCE BRIEF (this paper only):\n{one_brief}\n", pid))

    # Quotes are required as grounding whenever the Evidence Reader produced any; if it could not
    # run for these papers (wiki-based fallback evidence has no quotes), unquoted items must do.
    require_quote = any((e.get("provenance") or {}).get("quote")
                        for items in evidence_objects.values() for e in items)
    with ThreadPoolExecutor(max_workers=max(1, min(len(jobs), 5))) as pool:
        results = list(pool.map(
            lambda j: _run_finder(client, j[0], j[1], j[2], by_handle, titles, j[3], require_quote), jobs))

    candidates, finder_diag = [], []
    for gaps, diag in results:
        finder_diag.append(diag)
        candidates.extend(gaps)
    candidates = _dedupe(candidates)
    for i, c in enumerate(candidates, 1):
        c["_cid"] = f"G{i}"

    diagnostics = {"finders": finder_diag, "candidates": len(candidates), "critic_error": None}
    if not candidates:
        return {"gaps": [], "rejected": [], "diagnostics": diagnostics}

    client.set_stage("Stage 4c — Gap Critic")
    reviews, critic_error = _critic(client, candidates, feedback_text)
    diagnostics["critic_error"] = critic_error

    by_cid = {c["_cid"]: c for c in candidates}
    rejected, live = [], []
    for c in candidates:
        r = reviews.get(c["_cid"])
        verdict = (r or {}).get("verdict", "keep")
        c["scores"] = {k: (r or {}).get(k) for k in ("novelty", "importance", "feasibility")}
        c["critique"] = (r or {}).get("critique") or ""
        if r and r.get("sharpened_title") and str(r["sharpened_title"]).strip():
            c["title"] = str(r["sharpened_title"]).strip()
        if verdict == "drop":
            c["rejected_reason"] = (r or {}).get("reason") or "judged generic or already answered"
            rejected.append(c)
        elif verdict == "merge" and (r or {}).get("merge_into") in by_cid and r["merge_into"] != c["_cid"]:
            target = by_cid[r["merge_into"]]
            c["rejected_reason"] = f"merged into “{target['title']}”"
            rejected.append(c)
            for ev_id in c.get("motivating_evidence_ids", []):
                if ev_id not in target["motivating_evidence_ids"]:
                    target["motivating_evidence_ids"].append(ev_id)
            for line in c.get("evidence", []):
                if line not in target["evidence"]:
                    target["evidence"].append(line)
        else:
            live.append(c)
    from pipeline.feedback_context import feedback_adjustment
    adjusted = []
    for c in live:
        base = round(_score(reviews.get(c["_cid"]), c), 2)
        delta, note = feedback_adjustment(c["title"], feedback_items or [])
        c["composite_score"] = round(base + delta, 2)
        if note:
            c["feedback_note"] = note
            adjusted.append({"title": c["title"], "change": delta})
    live.sort(key=lambda g: -g["composite_score"])
    final, overflow = live[:max_gaps], live[max_gaps:]

    # Coverage rule: a paper that supports no gap is reported, and with a minimum set the best
    # gaps citing it are promoted from below the cut (the list may then exceed max_gaps).
    promoted = []
    if min_gaps_per_paper > 0:
        for pid in evidence_objects:
            while paper_support(final, {pid: 1}, titles)[pid] < min_gaps_per_paper:
                pick = next((c for c in overflow if paper_support([c], {pid: 1}, titles)[pid]), None)
                if pick is None:
                    break
                overflow.remove(pick)
                final.append(pick)
                promoted.append({"paper": pid, "title": pick["title"]})
        final.sort(key=lambda g: -g["composite_score"])
    for c in overflow:
        c["rejected_reason"] = f"ranked below the top {max_gaps}"
        rejected.append(c)
    support = paper_support(final, evidence_objects, titles)
    diagnostics["paper_support"] = support
    diagnostics["papers_without_gaps"] = [titles.get(pid, pid) for pid, n in support.items() if n == 0]
    diagnostics["promoted_for_coverage"] = promoted
    diagnostics["feedback_adjusted"] = adjusted

    for rank, g in enumerate(final, 1):
        g["rank"] = rank
        g["validation_status"] = "pending"
        g["existing_papers"] = []
        g["source"] = f"agent:{g['lens']}"
        g["pattern_id"] = None
        attach_gap_identity(g, evidence_basis=g.get("evidence_basis", "positive_evidence"))
    for g in final + rejected:
        g.pop("_cid", None)
        g.pop("evidence_refs", None)
    diagnostics.update({"kept": len(final), "rejected": len(rejected)})
    return {"gaps": final, "rejected": rejected, "diagnostics": diagnostics}
