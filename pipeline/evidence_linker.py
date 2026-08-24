"""
Evidence linker (Clinova Phase 4, Epic 4.4's Scientific Lineage plumbing).
Pure, deterministic, zero LLM calls -- shared by pipeline/graph_builder.py
(linking relationship "evidence" text to real Evidence Object ids) and
pipeline/gap_detector.py (linking LLM-generated gaps' free-text evidence
quotes the same way).

Repairs a real units mismatch found while investigating Scientific
Lineage: graph relationships' "paper" field is an LLM-written paper
TITLE (packages/research_schemas/evidence_object.py's paper_id is a
filename). build_paper_index()/resolve_paper_id() are the translation
layer between the two namespaces.

Matching is exact-normalized first, then fuzzy (difflib title ratio /
token-Jaccard for evidence text), scoped to a resolved paper_id when
possible for a lower, more permissive threshold, and corpus-wide
otherwise at a stricter threshold. Returns [] honestly when nothing
clears the bar -- never a best-guess single match, matching this
codebase's "honest empty over fabricated link" convention used
throughout Phase 1-3.
"""
import difflib
import re

EVIDENCE_LINK_VERSION = 1

TITLE_MATCH_RATIO = 0.85
EVIDENCE_MATCH_JACCARD_SCOPED = 0.35
EVIDENCE_MATCH_JACCARD_CORPUS_WIDE = 0.55
MAX_MATCHES = 3

_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "and", "or", "to", "for", "with",
    "is", "are", "was", "were", "this", "that", "these", "those", "as",
    "by", "at", "from", "be", "it", "its", "which",
}


def _normalize(text) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _tokens(text: str) -> set:
    words = re.findall(r"[a-z0-9]+", _normalize(text))
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def build_paper_index(wiki: dict) -> dict:
    """{normalized_title: paper_id} from wiki["pages"], joining on
    source_file (= paper["filename"], set unconditionally by
    wiki_compiler.py -- the same key evidence_objects is keyed by)."""
    index = {}
    for page in wiki.get("pages", []):
        paper_id = page.get("source_file")
        if not paper_id:
            continue
        title = page.get("title")
        if title:
            index[_normalize(title)] = paper_id
        # The filename itself is always a valid resolution target too --
        # a relationship's "paper" field occasionally already IS the
        # filename rather than a title (e.g. the fallback graph path,
        # which sets "paper" to the wiki page's title-or-source_file).
        index[_normalize(paper_id)] = paper_id
    return index


def resolve_paper_id(paper_ref: str, paper_index: dict) -> str | None:
    """Exact-normalized match first, then a fuzzy title match (ratio >=
    TITLE_MATCH_RATIO). Returns None, never a guess, if nothing clears
    the bar."""
    if not paper_ref or not paper_index:
        return None
    normalized = _normalize(paper_ref)
    if normalized in paper_index:
        return paper_index[normalized]

    best_ratio, best_id = 0.0, None
    for title, paper_id in paper_index.items():
        ratio = difflib.SequenceMatcher(None, normalized, title).ratio()
        if ratio > best_ratio:
            best_ratio, best_id = ratio, paper_id
    return best_id if best_ratio >= TITLE_MATCH_RATIO else None


def match_evidence_ids(text: str, paper_id: str | None, evidence_objects: dict) -> list[str]:
    """Matches `text` (a relationship's "evidence" paraphrase, or a
    gap's free-text evidence quote) against real Evidence Objects'
    `.text` fields via token-Jaccard similarity. Scoped to `paper_id`'s
    evidence when resolvable (lower threshold -- already narrowed to the
    right paper), corpus-wide otherwise (higher threshold, since a
    coincidental token overlap across unrelated papers is a real risk).
    Returns up to MAX_MATCHES ids, ranked by score, honestly empty below
    threshold -- never a best-guess single match."""
    if not text or not evidence_objects:
        return []

    query_tokens = _tokens(text)
    if not query_tokens:
        return []

    if paper_id and paper_id in evidence_objects:
        candidates = [(paper_id, e) for e in evidence_objects[paper_id]]
        threshold = EVIDENCE_MATCH_JACCARD_SCOPED
    else:
        candidates = [(pid, e) for pid, objs in evidence_objects.items() for e in objs]
        threshold = EVIDENCE_MATCH_JACCARD_CORPUS_WIDE

    scored = []
    for _pid, e in candidates:
        eid = e.get("evidence_id")
        if not eid:
            continue
        score = _jaccard(query_tokens, _tokens(e.get("text", "")))
        if score >= threshold:
            scored.append((score, eid))

    scored.sort(key=lambda x: -x[0])
    # Dedupe while preserving score order (an evidence_id could
    # theoretically appear once per candidate list entry).
    seen = set()
    out = []
    for _score, eid in scored:
        if eid not in seen:
            seen.add(eid)
            out.append(eid)
        if len(out) >= MAX_MATCHES:
            break
    return out
