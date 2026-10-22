"""
Evidence Reader agent: reads ONE paper's real text and returns grounded evidence.

The older extractor built "evidence" from the wiki summary (itself a lossy
LLM summary), so nothing could be traced to a passage and many items were copies
of wiki list entries. The reader works from the paper:

  1. The paper's page-tagged text blocks (pipeline/docling_parser.py) are merged
     into numbered passages [P12 | p.4 | 3. Results], references excluded.
  2. ONE model call per paper returns the paper's study type plus evidence items,
     each with a statement, a VERBATIM quote and the passage it came from.
  3. Every quote is checked against the paper's own text. A quote that is not
     found is dropped, so nothing unverifiable reaches the gap analysis. Verified
     items carry the real page, section and quote as provenance.

The study type matters downstream: rule-based checks such as TRIPOD/PROBAST items
only make sense for prediction-model studies, not for a review or a lab study.
"""
import difflib
import json
import re
import unicodedata

from packages.research_schemas.evidence_object import (
    EVIDENCE_TYPES, CONFIDENCE_LEVELS, EvidenceObject, Provenance,
)
from pipeline.agent_config import EVIDENCE_READER
from utils.azure_client import LLMCallError, unwrap

STUDY_TYPES = (
    "ml_prediction_model", "clinical_trial", "observational_clinical", "in_vitro_or_lab",
    "systematic_or_narrative_review", "survey_or_questionnaire", "computational_simulation", "other",
)
STUDY_TYPE_TAG = "[study_type: "

_NON_BODY = frozenset({"page_header", "page_footer", "page_number"})
_REFERENCE_HEADINGS = ("references", "bibliography", "literature cited", "reference list")
_PASSAGE_TARGET_CHARS = 1100
_MAX_BODY_CHARS = 200_000          # ~50k tokens: far inside the model's window, a guard only
_MIN_BODY_CHARS = 1500             # below this the PDF has no usable text (scanned): use the wiki fallback
_FUZZY_MIN_RATIO = 0.82

SYSTEM_PROMPT = f"""You are a meticulous scientific reader. You read ONE research paper, given as numbered passages, and extract grounded evidence for a research-gap analysis.

Return ONLY a JSON object:
{{
  "study_type": one of {list(STUDY_TYPES)},
  "study_type_reason": "one sentence",
  "evidence": [
    {{
      "type": one of {list(EVIDENCE_TYPES)},
      "statement": "a concise, specific statement in your own words (max 45 words; include the actual numbers)",
      "quote": "text copied EXACTLY, character for character, from the cited passage (30-250 characters)",
      "passage": "P12",
      "confidence": "high|medium|low"
    }}
  ]
}}

Rules:
- Every item must rest on a passage. The quote must be copied verbatim from that passage: do not paraphrase, merge sentences or fix typos in it. Items whose quote cannot be found in the paper are discarded.
- ResearchQuestion, Problem and StudyDesign: at most ONE item each.
- Result: report quantitative results WITH their numbers, effect sizes and p-values.
- Limitation and FutureWork: ONLY what the authors explicitly state (check the Discussion and Conclusion). Never infer one.
- Method, DatasetPopulation (with sample sizes), InterventionModel, ComparatorBaseline, Metric, Finding, Claim: include the important ones.
- {{target}}, favouring Results, Limitations, FutureWork, Methods and Datasets. Do not pad: fewer is fine if the text has less.
- Every number in your statement must appear in the passage you cite. Never invent anything; if the paper does not state something, leave it out.
"""

_TARGET_WHOLE = "Aim for 25-45 items in total"
_TARGET_PART = "You are reading part {i} of {n} of the paper; aim for 12-20 items from THIS part (the other parts are read separately)"
_MAX_CHARS_PER_READ = 18_000       # papers are read in parts of this size, in parallel, so no part is skimmed
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


# ── passages ────────────────────────────────────────────────────────────────

def build_passages(text_segments: list) -> list:
    """[{"id": "P1", "page": 3, "section": "3. Results", "text": "..."}], in reading order.
    Consecutive blocks under one heading on one page are merged up to ~1100 chars; the
    reference list and page furniture (headers, footers, page numbers) are left out."""
    passages, section, in_refs = [], None, False
    cur = None

    def flush():
        nonlocal cur
        if cur and cur["text"].strip():
            cur["id"] = f"P{len(passages) + 1}"
            passages.append(cur)
        cur = None

    total = 0
    for seg in text_segments or []:
        label, text = seg.get("label"), (seg.get("text") or "").strip()
        if not text or label in _NON_BODY:
            continue
        if label == "section_header":
            flush()
            section = text[:120]
            in_refs = section.strip().lower().rstrip(".:") in _REFERENCE_HEADINGS
            continue
        if in_refs:
            continue
        page = seg.get("page")
        if cur is None or cur["page"] != page or len(cur["text"]) + len(text) > _PASSAGE_TARGET_CHARS:
            flush()
            cur = {"page": page, "section": section, "text": ""}
        cur["text"] += (" " if cur["text"] else "") + text
        total += len(text)
        if total >= _MAX_BODY_CHARS:
            break
    flush()
    return passages


def render_passages(passages: list) -> str:
    return "\n\n".join(
        f"[{p['id']} | p.{p['page'] if p['page'] is not None else '?'} | {p['section'] or 'front matter'}]\n{p['text']}"
        for p in passages)


# ── quote verification ──────────────────────────────────────────────────────

def _alnum(text: str) -> str:
    """Lower-case letters and digits only, after Unicode compatibility folding (so the
    PDF's 'ﬁ' ligature equals 'fi'), which makes the match immune to the line-break
    hyphens, odd spacing and punctuation PDF text extraction introduces."""
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKC", text or "").lower())


def locate_quote(quote: str, passages: list, hint_id: str | None = None):
    """The passage a quote really comes from, or None. Exact (alphanumeric-folded)
    containment first, in the cited passage, then anywhere; then a fuzzy match for quotes
    the model slightly mangled (accepted when 82%+ of the quote is one contiguous run in
    a passage). Returns (passage, exact: bool)."""
    q = _alnum(quote)
    if len(q) < 20 or not passages:
        return None
    folded = [(p, _alnum(p["text"])) for p in passages]
    ordered = sorted(folded, key=lambda pf: 0 if pf[0]["id"] == hint_id else 1)
    for p, f in ordered:
        if q in f:
            return p, True
    best, best_ratio = None, 0.0
    for p, f in ordered:
        if len(f) < 20:
            continue
        m = difflib.SequenceMatcher(None, q, f, autojunk=False).find_longest_match(0, len(q), 0, len(f))
        ratio = m.size / len(q)
        if ratio > best_ratio:
            best, best_ratio = p, ratio
    if best is not None and best_ratio >= _FUZZY_MIN_RATIO:
        return best, False
    return None


# ── parsing ─────────────────────────────────────────────────────────────────

def _parse_object(raw: str):
    text = re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$', '', (raw or "").strip())
    for candidate in (text, re.sub(r',\s*([}\]])', r'\1', text)):
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
            if isinstance(value, list):                      # a bare evidence list
                return {"evidence": value}
        except json.JSONDecodeError:
            pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            value = json.loads(match.group())
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    return None


def _split_parts(passages: list) -> list:
    """Consecutive groups of passages of at most ~30k characters each (one group for a normal
    paper). A long paper read in one go is skimmed: a 72k-character review gave 9 items."""
    parts, cur, size = [], [], 0
    for p in passages:
        n = len(p["text"])
        if cur and size + n > _MAX_CHARS_PER_READ:
            parts.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += n
    if cur:
        parts.append(cur)
    # Avoid a tiny last part: fold it into the previous one.
    if len(parts) > 1 and sum(len(p["text"]) for p in parts[-1]) < _MAX_CHARS_PER_READ // 4:
        parts[-2].extend(parts.pop())
    return parts


def _numbers_supported(statement: str, source_text: str) -> bool:
    """True if every multi-digit number in `statement` appears in `source_text` (comma and
    point decimals treated alike). Single digits are ignored: they are usually counts the
    model wrote as a word ('three') in the source."""
    src = source_text.replace(",", ".")
    for n in _NUMBER_RE.findall(statement or ""):
        n = n.replace(",", ".")
        if len(n.replace(".", "")) < 2:
            continue
        if n not in src:
            return False
    return True


# ── the agent ───────────────────────────────────────────────────────────────

def read_paper(paper_id: str, text_segments: list, client, domain_hint: str = ""):
    """Returns (evidence_objects, diagnostics). diagnostics["usable"] is False when the
    reader could not run (no text, model failure, unreadable reply, nothing verified): the
    caller then falls back to the wiki-based extractor. Never raises."""
    diag = {"reader": True, "usable": False, "passages": 0, "parts": 1, "proposed": 0, "verified_exact": 0,
            "verified_fuzzy": 0, "dropped_unverified": 0, "dropped_invalid": 0, "dropped_number_mismatch": 0,
            "study_type": None, "error": None}
    passages = build_passages(text_segments)
    diag["passages"] = len(passages)
    if sum(len(p["text"]) for p in passages) < _MIN_BODY_CHARS:
        diag["error"] = "no usable text layer (scanned PDF?)"
        return [], diag

    parts = _split_parts(passages)
    diag["parts"] = len(parts)
    # Every part also gets the paper's opening passages (title, abstract), so a part that
    # starts mid-paper still knows what the study is.
    opening = render_passages(passages[:3]) if len(parts) > 1 else ""

    def read_part(idx_part):
        idx, part = idx_part
        target = _TARGET_WHOLE if len(parts) == 1 else _TARGET_PART.format(i=idx + 1, n=len(parts))
        user = (f"Paper id: {paper_id}\n" + (f"Domain: {domain_hint}\n" if domain_hint else "")
                + (f"\nPaper opening (for context only):\n\n{opening}\n" if opening and idx > 0 else "")
                + "\nPassages:\n\n" + render_passages(part))
        try:
            raw = unwrap(client.chat_json(SYSTEM_PROMPT.replace("{target}", target), user,
                                          max_tokens=EVIDENCE_READER.max_tokens,
                                          timeout_seconds=EVIDENCE_READER.timeout_seconds,
                                          max_retries=EVIDENCE_READER.max_retries))
        except LLMCallError as e:
            return None, f"model call failed: {e.error.kind}"
        data = _parse_object(raw)
        if not data or not isinstance(data.get("evidence"), list):
            return None, "reply could not be read"
        return data, None

    if len(parts) == 1:
        results = [read_part((0, parts[0]))]
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(len(parts), 4)) as pool:
            results = list(pool.map(read_part, enumerate(parts)))
    good = [d for d, _ in results if d is not None]
    if not good:
        diag["error"] = next((e for _, e in results if e), "reply could not be read")
        return [], diag

    study_type = next((d.get("study_type") for d in good if d.get("study_type") in STUDY_TYPES), "other")
    diag["study_type"] = study_type
    data = {"evidence": [it for d in good for it in d["evidence"]],
            "study_type_reason": next((d.get("study_type_reason") for d in good if d.get("study_type_reason")), "")}
    if len(good) < len(parts):
        diag["error"] = f"{len(parts) - len(good)} of {len(parts)} parts could not be read"
    objects, seen_single = [], set()
    index_of = {p["id"]: i for i, p in enumerate(passages)}
    for item in data["evidence"]:
        diag["proposed"] += 1
        if not isinstance(item, dict):
            diag["dropped_invalid"] += 1
            continue
        etype = item.get("type") or item.get("evidence_type")
        statement = str(item.get("statement") or item.get("text") or "").strip()
        conf = item.get("confidence") if item.get("confidence") in CONFIDENCE_LEVELS else "medium"
        if etype not in EVIDENCE_TYPES or not statement:
            diag["dropped_invalid"] += 1
            continue
        if etype in ("ResearchQuestion", "Problem", "StudyDesign"):
            if etype in seen_single:
                diag["dropped_invalid"] += 1
                continue
            seen_single.add(etype)
        found = locate_quote(str(item.get("quote") or ""), passages, str(item.get("passage") or "").strip())
        if found is None:
            diag["dropped_unverified"] += 1
            continue
        passage, exact = found
        # A statement's numbers must appear in the cited passage (or its neighbours): a quote
        # can be real while the statement states a figure the paper never gives.
        i0 = index_of.get(passage["id"], 0)
        context_text = " ".join(p["text"] for p in passages[max(0, i0 - 1): i0 + 2])
        if not _numbers_supported(statement, context_text):
            diag["dropped_number_mismatch"] += 1
            continue
        diag["verified_exact" if exact else "verified_fuzzy"] += 1
        if etype == "StudyDesign":
            statement = f"{STUDY_TYPE_TAG}{study_type}] {statement}"
        objects.append(EvidenceObject(
            evidence_type=etype, paper_id=paper_id, text=statement,
            provenance=Provenance(page=passage["page"], section=passage["section"], text_span=None,
                                  quote=str(item.get("quote")).strip()[:300]),
            confidence=conf if exact else ("low" if conf == "high" else conf)))
    if not any(o.evidence_type == "StudyDesign" for o in objects):
        # Keep the study type even when the model gave no verifiable StudyDesign quote.
        objects.append(EvidenceObject(
            evidence_type="StudyDesign", paper_id=paper_id,
            text=f"{STUDY_TYPE_TAG}{study_type}] {str(data.get('study_type_reason') or 'classified by the reader')}",
            provenance=Provenance(page=None, section=None, text_span=None), confidence="low"))
    diag["usable"] = diag["verified_exact"] + diag["verified_fuzzy"] >= 5
    return objects, diag


def study_type_of(evidence: list) -> str | None:
    """The study type the reader recorded, from a list of evidence dicts or objects
    (it is stored in the StudyDesign item's text so it survives caching)."""
    for e in evidence or []:
        text = e.get("text") if isinstance(e, dict) else getattr(e, "text", "")
        etype = e.get("evidence_type") if isinstance(e, dict) else getattr(e, "evidence_type", "")
        if etype == "StudyDesign" and isinstance(text, str) and text.startswith(STUDY_TYPE_TAG):
            return text[len(STUDY_TYPE_TAG):].split("]", 1)[0].strip() or None
    return None
