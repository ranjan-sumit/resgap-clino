"""
Evidence Extractor (Clinova Phase 2, Epic 2.1, Stories 2.1.3-2.1.4).

Deliberately NOT a fresh LLM re-extraction of the whole paper. wiki_compiler.py
already extracted methods/datasets/key_findings/limitations/future_work/
contributions via its own LLM call -- re-extracting the same information a
second time would violate 04-ai-research-architecture.md §2's LLM-use
discipline ("use LLM only for difficult scientific extraction," not for
re-deriving what's already been extracted). Instead:

  - 6 of the 13 evidence types (Method, DatasetPopulation, Result,
    Limitation, FutureWork, Claim) are derived DETERMINISTICALLY from the
    wiki page's already-extracted list fields, with real page/section
    provenance resolved by matching against Docling's page-tagged
    text_segments (pipeline/docling_parser.py, Story 2.1.1) when available.
  - The remaining 7 types (ResearchQuestion, Problem, StudyDesign,
    InterventionModel, ComparatorBaseline, Metric, Finding) genuinely
    aren't captured anywhere else in the pipeline today -- ONE small,
    scoped LLM call (still just one call per paper, not one per type)
    with an explicit token budget fills all 7 (2026-08-21: originally
    scoped to 3 of the 7, expanded to all 7 in the same call rather than
    adding a second call).

All 13 evidence types are covered as of 2026-08-21.

Provenance is honest by construction: when Docling didn't run for a paper
(Corpus Quality Engine toggle off) or no matching text segment is found,
`Provenance.page` is None -- never a guessed page number.
"""
import hashlib
import json
import re

from utils.azure_client import unwrap, LLMCallError
from utils import cache_tag
from utils.cache_tag import model_tag
from utils.database import get_cached_evidence_objects, save_cached_evidence_objects
from pipeline.agent_config import EVIDENCE_EXTRACTOR
from packages.research_schemas.evidence_object import (
    EvidenceObject, Provenance, validate_evidence_dict, to_dict,
)

# Bumped 1 -> 2, 2026-08-21: LLM-scoped type coverage expanded from 3 types
# to all 7 remaining types (was ResearchQuestion/Problem/StudyDesign only;
# now also InterventionModel/ComparatorBaseline/Metric/Finding), closing
# the "4 of 13 evidence types unextracted" gap. Cached evidence lists from
# before this change are missing these types entirely -- must not be
# served as if they were extracted (AD-3's stage_logic_version convention).
# Bumped 2 -> 3: the cache key now includes the Docling text_segments hash.
# A result cached from a run without Docling (Provenance.page=None
# everywhere) must not be served to a later run that has Docling segments
# and could resolve real provenance -- and vice versa.
# Bumped 3 -> 4: evidence is now read from the paper's text by the Evidence Reader
# (verified quotes, real pages, study type); results cached from the wiki-based
# path have no quotes and must not be served in its place.
EVIDENCE_STAGE_VERSION = 6      # 6: the cache key includes the model that read the paper

_DETERMINISTIC_FIELD_MAP = {
    "methods": "Method",
    "datasets": "DatasetPopulation",
    "key_findings": "Result",
    "limitations": "Limitation",
    "future_work": "FutureWork",
    "contributions": "Claim",
}

_LLM_EVIDENCE_TYPES = (
    "ResearchQuestion", "Problem", "StudyDesign",
    "InterventionModel", "ComparatorBaseline", "Metric", "Finding",
)

_EVIDENCE_LLM_SYSTEM_PROMPT = """You identify the paper's research question, the problem it addresses, its study design, the intervention/model it studies, what it's compared against, the metrics it reports, and its qualitative findings. These are facts a research-gap analysis needs that are not already captured by the paper's compiled methods/datasets/results/limitations lists.

Return ONLY a JSON array:
[
  {"evidence_type": "ResearchQuestion", "text": "...", "confidence": "high|medium|low"},
  {"evidence_type": "Problem", "text": "...", "confidence": "high|medium|low"},
  {"evidence_type": "StudyDesign", "text": "...", "confidence": "high|medium|low"},
  {"evidence_type": "InterventionModel", "text": "...", "confidence": "high|medium|low"},
  {"evidence_type": "ComparatorBaseline", "text": "...", "confidence": "high|medium|low"},
  {"evidence_type": "Metric", "text": "...", "confidence": "high|medium|low"},
  {"evidence_type": "Finding", "text": "...", "confidence": "high|medium|low"}
]

Rules:
- ResearchQuestion, Problem, and StudyDesign: at most ONE item each (a paper has one of each).
- InterventionModel, ComparatorBaseline, Metric, Finding: up to THREE items each if the paper reports multiple -- do not force a count that isn't there.
- A "Finding" is a qualitative or interpretive statement (e.g. "X was more strongly associated with Y than Z was"); it is DISTINCT from a quantitative "Result" (numeric results are already captured elsewhere -- do not duplicate them here).
- Omit a type entirely if it is genuinely not stated in the paper. Never invent a value to fill every type."""


# Docling labels that tag NON-body content. Provenance must never resolve
# against these: a running header or page number is repeated on every page,
# so first-match-in-document-order would cite evidence to page 1 (or the
# nearest header page) instead of the page the quote actually appears on.
_NON_BODY_LABELS = frozenset({"page_header", "page_footer", "page_number"})

# Minimum normalized length for a segment to win by being a substring of a
# longer quote -- shorter substrings are too weak as provenance evidence.
_MIN_SEGMENT_MATCH_CHARS = 20


def _build_section_map(text_segments: list) -> list:
    """Returns [{"text", "page", "section"}, ...] -- `section` is the most
    recent section_header segment's text seen before this one, so a body
    segment inherits the heading it actually appeared under."""
    current_section = None
    mapped = []
    for seg in text_segments or []:
        if seg.get("label") == "section_header":
            current_section = seg.get("text")
            continue
        if seg.get("label") in _NON_BODY_LABELS:
            continue
        mapped.append({"text": seg.get("text", ""), "page": seg.get("page"), "section": current_section})
    return mapped


def _resolve_provenance(quote: str, mapped_segments: list) -> Provenance:
    quote_norm = (quote or "").strip().lower()
    if not quote_norm or not mapped_segments:
        return Provenance(page=None, section=None, text_span=None)

    for seg in mapped_segments:
        seg_norm = seg["text"].lower()
        if quote_norm in seg_norm:
            return Provenance(page=seg["page"], section=seg["section"], text_span=None)
        if len(seg_norm) >= _MIN_SEGMENT_MATCH_CHARS and seg_norm in quote_norm:
            return Provenance(page=seg["page"], section=seg["section"], text_span=None)

    # No exact/substring match (the wiki-compiled or LLM-derived text is a
    # paraphrase, not a verbatim quote) -- try a softer match on a leading
    # fragment of meaningful length.
    words = quote_norm.split()
    if len(words) >= 5:
        fragment = " ".join(words[:8])
        for seg in mapped_segments:
            if fragment in seg["text"].lower():
                return Provenance(page=seg["page"], section=seg["section"], text_span=None)

    return Provenance(page=None, section=None, text_span=None)


def _parse_json_list(raw: str):
    """Same 3-strategy fallback convention used elsewhere in this codebase
    (gap_detector.py, param_extractor.py, etc.) -- returns (items, parse_failed)."""
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


def extract_deterministic_evidence(paper_id: str, wiki_page: dict, docling_result: dict = None):
    """Story 2.1.3 (deterministic half). Returns (list[EvidenceObject], diagnostics)."""
    mapped_segments = _build_section_map((docling_result or {}).get("text_segments", []))

    objects = []
    diagnostics = {"attempted": 0, "accepted": 0, "rejected": 0, "provenance_resolved": 0}

    for wiki_field, evidence_type in _DETERMINISTIC_FIELD_MAP.items():
        for item in (wiki_page.get(wiki_field) or []):
            text = str(item).strip()
            if not text:
                continue
            diagnostics["attempted"] += 1
            candidate = {"evidence_type": evidence_type, "confidence": "medium", "text": text}
            if not validate_evidence_dict(candidate):
                diagnostics["rejected"] += 1
                continue
            prov = _resolve_provenance(text, mapped_segments)
            if prov.page is not None:
                diagnostics["provenance_resolved"] += 1
            objects.append(EvidenceObject(
                evidence_type=evidence_type, paper_id=paper_id, text=text,
                provenance=prov, confidence="medium",
            ))
            diagnostics["accepted"] += 1

    return objects, diagnostics


def extract_llm_evidence(paper_id: str, wiki_page: dict, docling_result: dict, client,
                          max_tokens: int = EVIDENCE_EXTRACTOR.max_tokens):
    """Story 2.1.3 (LLM half, scoped to the 7 types nothing else captures).
    Returns (list[EvidenceObject], diagnostics). Never silently returns []
    on a parse/call failure without flagging it -- mirrors gap_detector.py's
    B19-fixed discipline (a failure must not look identical to "no evidence
    of this type exists"). max_tokens raised 800->1500 (2026-08-21) to fit
    up to ~15 items (3x each for InterventionModel/ComparatorBaseline/
    Metric/Finding + 1x each for ResearchQuestion/Problem/StudyDesign)
    without truncation. Default now sourced from pipeline/agent_config.py's
    EVIDENCE_EXTRACTOR (Epic 3.6) -- the literal value is unchanged, just
    no longer a bare inline number disconnected from the rest of that
    agent's real, typed budget/timeout."""
    mapped_segments = _build_section_map((docling_result or {}).get("text_segments", []))

    context = {
        "title": wiki_page.get("title", ""),
        "contributions": wiki_page.get("contributions", []),
        "methods": wiki_page.get("methods", []),
        "key_findings": wiki_page.get("key_findings", []),
    }
    user_prompt = f"Paper summary:\n{json.dumps(context, indent=2)}"

    diagnostics = {"attempted": 0, "accepted": 0, "rejected": 0,
                    "provenance_resolved": 0, "llm_call_failed": False}

    try:
        raw = unwrap(client.chat_json(
            _EVIDENCE_LLM_SYSTEM_PROMPT, user_prompt, max_tokens=max_tokens,
            timeout_seconds=EVIDENCE_EXTRACTOR.timeout_seconds,
            max_retries=EVIDENCE_EXTRACTOR.max_retries,
        ))
    except LLMCallError:
        diagnostics["llm_call_failed"] = True
        return [], diagnostics

    items, parse_failed = _parse_json_list(raw)
    if parse_failed:
        diagnostics["llm_call_failed"] = True
        return [], diagnostics

    objects = []
    for item in items:
        diagnostics["attempted"] += 1
        if not isinstance(item, dict) or item.get("evidence_type") not in _LLM_EVIDENCE_TYPES:
            diagnostics["rejected"] += 1
            continue
        item.setdefault("confidence", "medium")
        if not validate_evidence_dict(item):
            diagnostics["rejected"] += 1
            continue
        prov = _resolve_provenance(item["text"], mapped_segments)
        if prov.page is not None:
            diagnostics["provenance_resolved"] += 1
        objects.append(EvidenceObject(
            evidence_type=item["evidence_type"], paper_id=paper_id,
            text=item["text"], provenance=prov, confidence=item["confidence"],
        ))
        diagnostics["accepted"] += 1

    return objects, diagnostics


def extract_evidence(paper_id: str, wiki_page: dict, docling_result: dict = None,
                      client=None, use_llm: bool = True):
    """Combined entry point. `client=None` or `use_llm=False` skips the
    LLM half entirely and returns only the 6 deterministic evidence types
    -- a legitimate, honest mode (e.g. the Corpus Quality Engine toggle is
    off, or a caller wants zero LLM cost).

    When the paper's page-tagged text is available and a client is given, the
    Evidence Reader agent (pipeline/evidence_reader.py) reads the paper itself and
    every item carries a verified quote, page and section. Only if the reader cannot
    run (no text layer, model failure, nothing verified) does extraction fall back to
    the wiki-based path below, with the reason recorded in diagnostics["reader"]."""
    reader_diag = None
    if use_llm and client is not None:
        segments = (docling_result or {}).get("text_segments")
        if segments:
            from pipeline.evidence_reader import read_paper
            objects, reader_diag = read_paper(paper_id, segments, client)
            if reader_diag["usable"]:
                return objects, {"deterministic": None, "llm": None, "reader": reader_diag}

    det_objects, det_diag = extract_deterministic_evidence(paper_id, wiki_page, docling_result)

    if not use_llm or client is None:
        return det_objects, {"deterministic": det_diag, "llm": None, "reader": reader_diag}

    llm_objects, llm_diag = extract_llm_evidence(paper_id, wiki_page, docling_result, client)
    if reader_diag and reader_diag.get("error") and "no usable text" not in reader_diag["error"]:
        # The reader should have worked: do not cache this degraded fallback as if it
        # were the real extraction (a transient failure must not be frozen in).
        llm_diag["llm_call_failed"] = True
    return det_objects + llm_objects, {"deterministic": det_diag, "llm": llm_diag, "reader": reader_diag}


def _evidence_content_hash(paper_id: str, wiki_page: dict, docling_result: dict = None) -> str:
    segments = (docling_result or {}).get("text_segments") or []
    segment_material = [
        {"text": s.get("text", ""), "page": s.get("page"), "label": s.get("label")}
        for s in segments
    ]
    canonical = json.dumps({"paper_id": paper_id, "wiki_page": wiki_page,
                            "docling_segments": segment_material},
                            sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def extract_evidence_cached(paper_id: str, wiki_page: dict, docling_result: dict = None,
                             client=None, use_llm: bool = True):
    """Story 2.2.1: cache-aside wrapper around extract_evidence(), same
    AD-2/AD-3 pattern as every other Epic-2-style cache in this codebase.
    Content-addressed on (paper_id, wiki_page, docling text_segments) --
    the text_segments decide which provenance pages get resolved, so a
    result extracted without Docling (page=None everywhere) must not be
    served to a run that has Docling segments, and vice versa.

    Returns (evidence_dicts, diagnostics, from_cache). Evidence Objects are
    always returned as dicts (via to_dict()) -- consistent shape whether
    served from cache or freshly extracted, so callers don't need to
    special-case reconstruction. `diagnostics` always carries a
    "from_cache" flag (True/False) regardless of which path produced it.

    Never caches a result where the LLM half failed (AD-2's "never cache a
    failure" rule) -- the deterministic-only evidence would otherwise be
    permanently frozen in place of what should have been a fuller result
    once the transient failure clears."""
    content_hash = _evidence_content_hash(paper_id, wiki_page, docling_result)
    cache_key = f"{content_hash}:none:{EVIDENCE_STAGE_VERSION}" + cache_tag.suffix(model_tag(client) if use_llm else "")

    cached = get_cached_evidence_objects(cache_key)
    if cached is not None:
        return cached, {"deterministic": None, "llm": None, "from_cache": True}, True

    objects, diagnostics = extract_evidence(paper_id, wiki_page, docling_result, client, use_llm)
    diagnostics["from_cache"] = False
    evidence_dicts = [to_dict(o) for o in objects]

    llm_diag = diagnostics.get("llm")
    llm_failed = bool(llm_diag and llm_diag.get("llm_call_failed"))
    if not llm_failed:
        save_cached_evidence_objects(cache_key, content_hash, EVIDENCE_STAGE_VERSION, evidence_dicts)

    return evidence_dicts, diagnostics, False
