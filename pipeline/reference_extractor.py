"""
Stage: Reference Extractor
Extracts cited references from uploaded PDFs, then enriches them
with metadata from Semantic Scholar, CrossRef and OpenAlex.

Solves the 50+ paper problem:
  Uploaded PDFs     → Tier 1 (full processing)
  Cited references  → Tier 2 (abstract + params, no PDF needed)
  Refs of refs      → Tier 3 (title/year only, gap signal)

No Apify needed — three free academic APIs cover everything.
"""
import re
import json
import time
import html
import unicodedata
from concurrent.futures import ThreadPoolExecutor
import difflib
import requests
import urllib.parse
from typing import Optional
from utils.azure_client import unwrap
from pipeline.agent_schemas import keep_valid
from utils.database import compute_cache_key, get_cached_reference, save_cached_reference

# Bumped whenever enrich_reference's lookup/normalization logic changes, so
# old cached entries don't silently keep serving stale-logic results (AD-3).
REFERENCE_STAGE_VERSION = 2   # 2: title matches are verified; old cached matches may belong to another paper

# Minimum normalized title similarity for a search-API candidate to be
# accepted as the same paper the reference's title points at. Without this,
# the first hit carrying an abstract wins even when its title belongs to a
# different paper, and the wrong metadata gets cached under the queried
# title.
_TITLE_MATCH_THRESHOLD = 0.85

# ── API constants ──────────────────────────────────────────────────────────────
SS_SEARCH   = "https://api.semanticscholar.org/graph/v1/paper/search"
SS_PAPER    = "https://api.semanticscholar.org/graph/v1/paper/{id}"
SS_REFS     = "https://api.semanticscholar.org/graph/v1/paper/{id}/references"
CROSSREF    = "https://api.crossref.org/works/{doi}"
OPENALEX    = "https://api.openalex.org/works"
UNPAYWALL   = "https://api.unpaywall.org/v2/{doi}"

SS_FIELDS   = "title,year,abstract,authors,externalIds,citationCount,referenceCount"
_HEADERS    = {"User-Agent": "ResearchGapAnalyzer/1.0 (academic research tool)"}
_TIMEOUT    = 8
_ENRICH_WORKERS = 3      # lookups in flight at once; the public APIs throttle above this


# ── Reference text parsing ─────────────────────────────────────────────────────

DOI_RE    = re.compile(r'10\.\d{4,9}/[^\s\n,;\"\'<>]+', re.IGNORECASE)
ARXIV_RE  = re.compile(r'arxiv[:\s]+(\d{4}\.\d{4,5})', re.IGNORECASE)
YEAR_RE   = re.compile(r'\b(19|20)\d{2}\b')


def _extract_dois_from_text(text: str) -> list[str]:
    """Pull all DOIs from raw text using regex."""
    raw = DOI_RE.findall(text)
    # Clean trailing punctuation that crept in
    cleaned = []
    for doi in raw:
        doi = doi.rstrip('.,;)>]"\'')
        if len(doi) > 8:
            cleaned.append(doi.lower())
    return list(dict.fromkeys(cleaned))  # deduplicate, preserve order


def _extract_arxiv_ids(text: str) -> list[str]:
    return list(dict.fromkeys(ARXIV_RE.findall(text)))


def clean_reference_text(text: str) -> str:
    """Make reference text searchable: ligatures folded ("ﬁ" -> "fi"), words broken across lines rejoined
    ("com- plementary" -> "complementary"), and DOIs split by a line break or a space put back together."""
    text = unicodedata.normalize("NFKC", text or "").replace("\u00ad", "")
    text = re.sub(r"(?<=[A-Za-z])-\s+(?=[a-z])", "", text)
    text = re.sub(r"(?i)(doi\.org/|doi:)\s+(?=10\.)", r"\1", text)
    text = re.sub(r"(10\.\d{4,9}/\S*-)\s+(?=[A-Za-z0-9])", r"\1", text)
    text = re.sub(r"(10\.\d{4,9}/\S*[A-Za-z]\.)\s+(?=\d{5,}\b)", r"\1", text)
    return text


_MARKERS = {
    "bracket": re.compile(r"(?:(?<=\s)|^)\[(\d{1,3})\]\s*"),
    "paren": re.compile(r"(?:(?<=\s)|^)\((\d{1,3})\)\s+(?=[A-Z])"),
    "dot": re.compile(r"(?:(?<=\s)|^)(\d{1,3})\.\s+(?=[A-Z])"),
}


def _numbered_chain(text: str, pattern: re.Pattern) -> list[re.Match]:
    """The markers 1, 2, 3 ... in order. A number inside an entry ("pp. 12. Smith") is skipped because only the
    next number in the sequence is accepted."""
    chain, want = [], 1
    for m in pattern.finditer(text):
        if int(m.group(1)) == want:
            chain.append(m)
            want += 1
    return chain


def _split_reference_entries(refs_text: str) -> list[str]:
    """
    Split a References section into individual citation strings.
    Handles numbered [1], (1), 1. styles and author-year styles.
    """
    refs_text = re.sub(r'\s+', ' ', clean_reference_text(refs_text)).strip()
    if not refs_text:
        return []

    # Numbered lists: take the style whose markers run 1, 2, 3 ... furthest.
    best = max((_numbered_chain(refs_text, p) for p in _MARKERS.values()), key=len)
    if len(best) >= 3:
        ends = [m.start() for m in best[1:]] + [len(refs_text)]
        entries = [refs_text[m.end():end].strip() for m, end in zip(best, ends)]
        return [e for e in entries if len(e) > 20]

    # Fall back: split where a likely year ends one citation and a capitalized
    # author/title begins the next.
    entries = re.split(r'(?<=\b(?:19|20)\d{2}[.;])\s+(?=[A-Z][A-Za-z\-]+[,.;])', refs_text)
    entries = [e.strip() for e in entries if len(e.strip()) > 20]
    return entries


_JUNK_TITLE_RE = re.compile(r"^(available online|accessed|retrieved|https?:|www\.|doi\b)", re.IGNORECASE)


def _plain_title(title) -> str:
    """A title as text: markup tags dropped (Crossref returns "<i>CFTR</i>"), runs of whitespace collapsed."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", str(title or "")))).strip()


def _plausible_title(title: str) -> bool:
    title = (title or "").strip()
    words = re.findall(r"[A-Za-z]{2,}", title)
    return (len(title) >= 12 and len(words) >= 3 and not _JUNK_TITLE_RE.match(title)
            and not re.search(r"\[(?:CrossRef|PubMed)\]", title))


def _title_in_citation(candidate_title: str, year, citation: str) -> bool:
    """Is a search hit's title the paper this citation string names? Nearly every word of the hit's title must appear
    in the citation, and the hit's year must be too (when it has one)."""
    words = [w for w in _normalize_title_text(candidate_title).split() if len(w) > 2]
    cite = _normalize_title_text(citation)
    have = set(cite.split())
    if len(words) < 3 or sum(w in have for w in words) / len(words) < 0.9:
        return False
    return not year or str(year) in cite


def _crossref_citation_search(citation: str) -> Optional[dict]:
    """Search Crossref with a whole citation string (what its bibliographic query is made for) and keep a hit only if
    its title is found in that citation."""
    try:
        r = requests.get("https://api.crossref.org/works",
                         params={"query.bibliographic": citation[:300], "rows": 3,
                                 "select": "DOI,title,author,container-title,published,abstract,URL,is-referenced-by-count"},
                         headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        for item in r.json().get("message", {}).get("items", []):
            cand = (item.get("title") or [""])[0] if isinstance(item.get("title"), list) else item.get("title", "")
            year = (item.get("published", {}).get("date-parts") or [[None]])[0][0]
            if cand and _title_in_citation(cand, year, citation):
                doi = item.get("DOI", "")
                return {
                    "title": cand, "year": year, "abstract": re.sub(r"<[^>]+>", "", item.get("abstract", "") or ""),
                    "doi": doi,
                    "venue": (item.get("container-title") or [""])[0] if isinstance(item.get("container-title"), list)
                    else item.get("container-title", ""),
                    "authors": _crossref_authors(item), "citations": item.get("is-referenced-by-count", 0),
                    "url": item.get("URL") or (f"https://doi.org/{doi}" if doi else ""), "source_api": "crossref_citation",
                }
    except Exception:
        pass
    return None


def _entry_to_reference(entry: str) -> dict:
    """Best-effort citation parser used when DOI/LLM parsing misses a ref."""
    clean = re.sub(r'\s+', ' ', entry or '').strip()
    clean = re.sub(r'^(?:\[\d+\]|\(\d+\)|\d+\.)\s+', '', clean)
    year_match = YEAR_RE.search(clean)
    year = int(year_match.group(0)) if year_match else None
    doi_match = DOI_RE.search(clean)
    doi = doi_match.group(0).rstrip('.,;)').lower() if doi_match else None

    title = ""
    if year_match:
        after_year = clean[year_match.end():].strip(" .;:-")
        before_year = clean[:year_match.start()].strip(" .;:-")
        # Vancouver/MDPI style often has authors first, then title, then journal/year.
        parts = [p.strip() for p in re.split(r'\.\s+', before_year) if p.strip()]
        if len(parts) >= 3:
            # authors. title. journal. -- the journal name is the LAST
            # segment, so parts[-1] would cite the journal as the title.
            title = parts[-2]
        elif len(parts) == 2:
            title = parts[-1]
        elif after_year:
            title = after_year.split(". ")[0].strip()
        else:
            title = before_year
    else:
        parts = [p.strip() for p in re.split(r'\.\s+', clean) if p.strip()]
        title = parts[1] if len(parts) > 1 else clean[:180]

    if not _plausible_title(title):
        title = ""                      # a guess that is not a title would be searched for and matched to the wrong paper

    return {
        "title": html.unescape(title[:240]),
        "authors": [],
        "year": year,
        "doi": doi,
        "journal": None,
        "arxiv_id": None,
        "raw_reference": clean[:1200],
    }


def parse_references_section(paper: dict) -> dict:
    """
    Extract raw reference text and initial DOIs from a parsed paper dict.
    Returns {'raw_text': str, 'dois': list, 'arxiv_ids': list, 'entries': list}
    """
    sections = paper.get("sections", {})

    # Find the references section. Some PDFs produce several table/section
    # headers containing "References"; prefer the longest candidate.
    ref_candidates = []
    for sec_name, sec_text in sections.items():
        if re.search(r'references?|bibliography', sec_name.lower()):
            ref_candidates.append(str(sec_text))
    ref_text = max(ref_candidates, key=len) if ref_candidates else ""

    if not ref_text:
        # Try end of full_text (references usually at the end)
        full = paper.get("full_text", "")
        idx  = max(
            full.lower().rfind("references"),
            full.lower().rfind("bibliography"),
        )
        if idx > 0:
            ref_text = full[idx:][:25000]

    ref_text = clean_reference_text(ref_text)
    return {
        "raw_text":  ref_text[:25000],
        "dois":      _extract_dois_from_text(ref_text),
        "arxiv_ids": _extract_arxiv_ids(ref_text),
        "entries":   _split_reference_entries(ref_text),
    }


# ── LLM-assisted reference parsing ────────────────────────────────────────────

REF_PARSE_PROMPT = """You are a bibliographic parser. Extract structured references 
from this References section text.

For each reference return:
{
  "title": "exact paper title",
  "authors": ["Last FM", "Last FM"],
  "year": 2023,
  "doi": "10.xxxx/xxx or null",
  "journal": "journal name or null",
  "arxiv_id": "XXXX.XXXXX or null"
}

Return ONLY a JSON array. Include up to 30 references.
If title is unclear, skip that entry."""


def parse_references_with_llm(ref_text: str, client, entries: list[str] | None = None, max_refs: int = 30) -> list[dict]:
    """Use LLM to parse messy reference text into structured entries. With `entries` (the split list) the model
    is given the first `max_refs` of them, numbered, so the whole batch it will be asked about is in front of it."""
    if entries and len(entries) >= 3:
        text = "\n".join(f"{i}. {e[:600]}" for i, e in enumerate(entries[:max_refs], 1))
    else:
        text = (ref_text or "")[:6000]
    if not text or len(text) < 50:
        return []
    raw = unwrap(client.chat_json(
        REF_PARSE_PROMPT,
        f"References section:\n\n{text}",
        max_tokens=4000,
    ))
    result, _ = keep_valid("reference", [r for r in _safe_parse_list(raw) if isinstance(r, dict)], client)
    return [clean_reference_fields(r) for r in result]


def clean_reference_fields(ref: dict) -> dict:
    ref = dict(ref)
    ref["title"] = re.sub(r"\s+", " ", clean_reference_text(str(ref.get("title") or ""))).strip()
    if ref.get("doi"):
        ref["doi"] = str(ref["doi"]).strip().lower().removeprefix("https://doi.org/").removeprefix("doi:").strip()
    return ref


def _safe_parse_list(raw: str) -> list:
    raw = raw.strip()
    for attempt in [
        lambda s: s,
        lambda s: re.sub(r'^```(?:json)?\s*|\s*```$', '', s).strip(),
        lambda s: re.sub(r',\s*([}\]])', r'\1', s),
    ]:
        try:
            result = json.loads(attempt(raw))
            if isinstance(result, list):
                return result
        except Exception:
            pass
    m = re.search(r'\[.*\]', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return []


# ── Academic API lookups ───────────────────────────────────────────────────────

def _normalize_title_text(title) -> str:
    t = re.sub(r'[^a-z0-9 ]', ' ', str(title or '').lower())
    return re.sub(r'\s+', ' ', t).strip()


def _title_similarity(a: str, b: str) -> float:
    na, nb = _normalize_title_text(a), _normalize_title_text(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


_SS_KEY = {"value": ""}     # set by extract_and_enrich_references for the duration of a run


def _ss_search_by_title(title: str) -> Optional[dict]:
    """Search Semantic Scholar by title. Returns the best title match or
    None when no candidate clears the similarity threshold -- abstract
    presence breaks near-ties only, it never substitutes for a title match."""
    try:
        params = {"query": title[:200], "limit": 5, "fields": SS_FIELDS}
        headers = {**_HEADERS, **({"x-api-key": _SS_KEY["value"]} if _SS_KEY["value"] else {})}
        r = requests.get(SS_SEARCH, params=params, headers=headers, timeout=_TIMEOUT)
        if r.status_code == 200:
            items = r.json().get("data", [])
            best, best_key = None, None
            for item in items:
                if not item.get("title"):
                    continue
                score = _title_similarity(title, item["title"])
                if score < _TITLE_MATCH_THRESHOLD:
                    continue
                key = (score, bool(item.get("abstract")))
                if best_key is None or key > best_key:
                    best, best_key = item, key
            return best
    except Exception:
        pass
    return None


def _ss_by_doi(doi: str) -> Optional[dict]:
    try:
        url = SS_PAPER.format(id=urllib.parse.quote(f"DOI:{doi}", safe=""))
        r   = requests.get(url, params={"fields": SS_FIELDS},
                           headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _ss_by_arxiv(arxiv_id: str) -> Optional[dict]:
    try:
        url = SS_PAPER.format(id=urllib.parse.quote(f"ARXIV:{arxiv_id}", safe=""))
        r   = requests.get(url, params={"fields": SS_FIELDS},
                           headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _crossref_by_doi(doi: str) -> Optional[dict]:
    try:
        r = requests.get(
            CROSSREF.format(doi=urllib.parse.quote(doi, safe="")),
            headers=_HEADERS, timeout=_TIMEOUT,
        )
        if r.status_code == 200:
            msg = r.json().get("message", {})
            return {
                "title":    (msg.get("title") or [""])[0],
                "year":     (msg.get("published", {}).get("date-parts") or [[None]])[0][0],
                "abstract": msg.get("abstract", ""),
                "doi":      doi,
                "venue":    ((msg.get("container-title") or [""])[0]
                             if isinstance(msg.get("container-title"), list) else msg.get("container-title", "")),
                "authors":  _crossref_authors(msg),
                "citations": msg.get("is-referenced-by-count", 0),
                "url":      msg.get("URL") or f"https://doi.org/{doi}",
                "source_api": "crossref",
            }
    except Exception:
        pass
    return None


def _crossref_authors(item: dict) -> list[str]:
    authors = []
    for a in item.get("author", [])[:6]:
        name = f"{a.get('given','')} {a.get('family','')}".strip()
        if name:
            authors.append(name)
    return authors


def _normalise_authors(authors) -> list[str]:
    names = []
    for a in authors or []:
        if isinstance(a, dict):
            name = a.get("name") or f"{a.get('given','')} {a.get('family','')}".strip()
        else:
            name = str(a)
        if name:
            names.append(name)
    return names[:6]


def _crossref_search(title: str) -> Optional[dict]:
    try:
        params = {
            "query.bibliographic": title[:200],
            "rows": 3,
            "select": "DOI,title,author,container-title,published,abstract,URL,is-referenced-by-count",
        }
        r = requests.get("https://api.crossref.org/works",
                         params=params, headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code == 200:
            items = r.json().get("message", {}).get("items", [])

            def _t(it):
                return (it.get("title") or [""])[0] if isinstance(it.get("title"), list) else it.get("title", "")
            items = [it for it in items if _t(it)]
            items.sort(key=lambda it: _title_similarity(title, _t(it)), reverse=True)
            if items:
                item = items[0]
                cand_title = _t(item)
                if _title_similarity(title, cand_title) < _TITLE_MATCH_THRESHOLD:
                    return None
                doi = item.get("DOI", "")
                return {
                    "title":    ((item.get("title") or [""])[0]
                                 if isinstance(item.get("title"), list) else item.get("title", "")),
                    "year":     (item.get("published", {}).get("date-parts") or [[None]])[0][0],
                    "abstract": re.sub(r'<[^>]+>', '', item.get("abstract", "") or ""),
                    "doi":      doi,
                    "venue":    ((item.get("container-title") or [""])[0]
                                 if isinstance(item.get("container-title"), list) else item.get("container-title", "")),
                    "authors":  _crossref_authors(item),
                    "citations": item.get("is-referenced-by-count", 0),
                    "url":      item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
                    "source_api": "crossref_search",
                }
    except Exception:
        pass
    return None


def _unpaywall_by_doi(doi: str) -> Optional[str]:
    try:
        url = UNPAYWALL.format(doi=urllib.parse.quote(doi, safe=""))
        r = requests.get(url, params={"email": "research@example.com"},
                         headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if data.get("is_oa"):
                loc = data.get("best_oa_location") or {}
                return loc.get("url_for_pdf") or loc.get("url")
    except Exception:
        pass
    return None


def _pubmed_search(doi: str = "", title: str = "") -> Optional[dict]:
    try:
        base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        term = f"{doi}[doi]" if doi else f'"{title[:180]}"[Title]'
        if not term:
            return None
        r = requests.get(
            f"{base}/esearch.fcgi",
            params={"db": "pubmed", "term": term, "retmax": 1, "retmode": "json"},
            headers=_HEADERS, timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return None
        pmid = ids[0]
        r2 = requests.get(
            f"{base}/esummary.fcgi",
            params={"db": "pubmed", "id": pmid, "retmode": "json"},
            headers=_HEADERS, timeout=_TIMEOUT,
        )
        if r2.status_code == 200:
            summ = r2.json().get("result", {}).get(pmid, {})
            if not doi and _title_similarity(title, summ.get("title", "")) < _TITLE_MATCH_THRESHOLD:
                return None                                   # a different paper: never attach its title
            return {
                "title": summ.get("title", ""),
                "year": (summ.get("pubdate", "") or "")[:4],
                "abstract": "",
                "doi": doi,
                "venue": summ.get("source", ""),
                "authors": [a.get("name", "") for a in summ.get("authors", [])[:6]],
                "citations": 0,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "source_api": "pubmed",
            }
    except Exception:
        pass
    return None


def _openalex_by_title(title: str) -> Optional[dict]:
    try:
        params = {
            "search":  title[:150],
            # Clinova B20 fix: request `id` (the OpenAlex work ID, e.g.
            # "https://openalex.org/W1234567890") so canonical reference
            # resolution (pipeline/canonical_resolver.py, ADR-007's
            # DOI->PMID->OpenAlex ID->... priority chain) has something real
            # to resolve against for this provider -- previously not
            # requested at all, so that priority level could never match.
            "select":  "id,title,publication_year,abstract_inverted_index,doi",
            "per-page": 5,
        }
        r = requests.get(OPENALEX, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code == 200:
            # The best-matching TITLE among the hits, and only if it really is the queried title: the first hit
            # for a vague query ("Pharmacol") is an unrelated paper, and its abstract would be attached to the reference.
            results = [x for x in r.json().get("results", []) if x.get("title")]
            results.sort(key=lambda x: _title_similarity(title, x["title"]), reverse=True)
            if results and _title_similarity(title, results[0]["title"]) >= _TITLE_MATCH_THRESHOLD:
                return _openalex_meta(results[0], title)
    except Exception:
        pass
    return None


def _openalex_meta(item: dict, fallback_title: str = "") -> dict:
    # Reconstruct abstract from inverted index
    inv = item.get("abstract_inverted_index") or {}
    words = sorted(
        ((pos, word) for word, positions in inv.items() for pos in positions),
        key=lambda x: x[0],
    )
    abstract = " ".join(w for _, w in words[:200]) if words else ""
    return {
        "title":    item.get("title", fallback_title),
        "year":     item.get("publication_year"),
        "abstract": abstract,
        "doi":      (item.get("doi") or "").replace("https://doi.org/", ""),
        "openalex_id": (item.get("id") or "").replace("https://openalex.org/", ""),
        "venue":    "",
        "authors":  [],
        "citations": 0,
        "url":      item.get("doi") or "",
        "source_api": "openalex",
    }


def _openalex_by_doi(doi: str) -> Optional[dict]:
    """The DOI is exact, so no title check is needed. Used for the abstract, which Crossref rarely has."""
    try:
        r = requests.get(OPENALEX, params={"filter": f"doi:https://doi.org/{doi}", "per-page": 1,
                                           "select": "id,title,publication_year,abstract_inverted_index,doi"},
                         headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code == 200:
            results = r.json().get("results", [])
            if results and results[0].get("title"):
                return _openalex_meta(results[0])
    except Exception:
        pass
    return None


# ── Enrichment ────────────────────────────────────────────────────────────────

def enrich_reference(ref: dict, delay: float = 0.3) -> dict:
    """
    Try multiple APIs to get title + abstract for one reference.
    Priority: Semantic Scholar (DOI) → SS (arxiv) → CrossRef → OpenAlex → SS (title)
    """
    doi      = (ref.get("doi") or "").strip().lower()
    arxiv_id = (ref.get("arxiv_id") or "").strip()
    title    = (ref.get("title") or "").strip()

    # B17 fix: check the cache before calling any external API (Story 2.3 /
    # AD-2 / AD-3). Identity is computed ONCE, from the input `ref` only --
    # never from anything an API call later resolves -- and used for BOTH
    # the read below and the write further down, so they can never diverge.
    # Review fix: tag the identity with its source type before hashing, so a
    # title that happens to equal another ref's DOI/arXiv-ID string can never
    # collide with it on the same cache_key.
    if doi:
        identity = f"doi:{doi}"
    elif arxiv_id:
        identity = f"arxiv:{arxiv_id.lower()}"
    elif title:
        identity = f"title:{title.lower()}"
    else:
        identity = ""
    cacheable = bool(identity)
    if cacheable:
        cache_key, content_hash, _ = compute_cache_key(identity, None, [], REFERENCE_STAGE_VERSION)
        # Review fix: a broken cache must degrade to "no cache", never abort
        # an enrichment that could otherwise succeed -- mirrors this file's
        # own B6/B12 philosophy of never letting one failure kill processing
        # that would otherwise work.
        try:
            cached = get_cached_reference(cache_key)
        except Exception:
            cached = None
        if cached is not None:
            return cached

    meta = None

    if doi:
        meta = _ss_by_doi(doi)
        time.sleep(delay)

    if not meta and arxiv_id:
        meta = _ss_by_arxiv(arxiv_id)
        time.sleep(delay)

    if not meta and doi:
        meta = _crossref_by_doi(doi)
        time.sleep(delay)

    if not meta and doi:
        meta = _pubmed_search(doi=doi)
        time.sleep(delay)

    if not meta and title and len(title) > 10:
        meta = _openalex_by_title(title)
        time.sleep(delay)

    if not meta and title and len(title) > 10:
        meta = _crossref_search(title)
        time.sleep(delay)

    if not meta and title and len(title) > 10:
        meta = _ss_search_by_title(title)
        time.sleep(delay)

    if not meta and title and len(title) > 10:
        meta = _pubmed_search(title=title)
        time.sleep(delay)

    raw_citation = (ref.get("raw_reference") or "").strip()
    if not meta and not doi and len(raw_citation) > 40:
        meta = _crossref_citation_search(raw_citation)
        time.sleep(delay)

    if meta and not meta.get("abstract") and (doi or meta.get("doi")):
        # Crossref and PubMed rarely carry the abstract; OpenAlex usually does, and the DOI makes the lookup exact.
        extra = _openalex_by_doi(doi or meta.get("doi"))
        if extra and extra.get("abstract"):
            meta = {**meta, "abstract": extra["abstract"], "openalex_id": extra.get("openalex_id", "")}
        time.sleep(delay)

    if meta:
        resolved_doi = doi or (meta.get("externalIds") or {}).get("DOI", "") or meta.get("doi", "")
        open_access_url = None
        if resolved_doi:
            open_access_url = _unpaywall_by_doi(resolved_doi)
        # Normalise to our schema
        result = {
            "title":       _plain_title(meta.get("title")) or title,
            "year":        meta.get("year") or meta.get("publication_year") or ref.get("year"),
            "abstract":    (meta.get("abstract") or "")[:1500],
            "doi":         resolved_doi,
            "arxiv_id":    arxiv_id,
            "authors":     _normalise_authors(meta.get("authors") or ref.get("authors", [])),
            "venue":       meta.get("venue", ""),
            "citations":   meta.get("citationCount", meta.get("citations", 0)),
            "ss_paper_id": meta.get("paperId", ""),
            "openalex_id": meta.get("openalex_id", ""),
            "url":         meta.get("url") or (f"https://doi.org/{resolved_doi}" if resolved_doi else ""),
            "open_access_url": open_access_url or meta.get("open_access_url"),
            "tier":        2,
            "source":      meta.get("source_api", "api_lookup"),
        }
        # B17 fix: only cache a genuine Tier-2 metadata hit, keyed by the
        # SAME identity/cache_key computed before any lookups ran above.
        # Review fix: a cache-write failure must not discard the real
        # enrichment we already fetched -- swallow and still return `result`.
        if cacheable:
            try:
                save_cached_reference(cache_key, content_hash, REFERENCE_STAGE_VERSION, result)
            except Exception:
                pass
        return result

    # Fallback: minimal record from what we parsed
    # B17 fix: never cache this path (AD-2) -- every lookup above already
    # swallows its own failures into None, so we can't tell "transient
    # failure" from "genuinely no metadata"; a future retry might succeed.
    return {
        "title":    title or (ref.get("raw_reference") or "")[:140] or "Unknown",
        "year":     ref.get("year"),
        "abstract": "",
        "doi":      doi,
        "arxiv_id": arxiv_id,
        "authors":  ref.get("authors", []),
        "citations": 0,
        "tier":     3,   # Tier 3 — title only, no abstract
        "source":   "parsed_only",
    }


# ── Main pipeline ─────────────────────────────────────────────────────────────

def extract_and_enrich_references(
    papers: list[dict],
    client,
    max_refs_per_paper: int = 30,
    progress_callback=None,
    return_diagnostics: bool = False,
    ss_api_key: str = "",
) -> list[dict]:
    """
    Full reference extraction pipeline for a list of uploaded papers.

    Returns list of enriched reference dicts (Tier 2 and 3).
    Tier 1 papers (uploaded) are NOT included in the output.

    progress_callback: optional fn(current, total, message)
    """
    _SS_KEY["value"] = (ss_api_key or "").strip()
    all_refs  = []
    seen_dois = set()
    seen_titles: set[str] = set()
    diagnostics = {
        "papers": [],
        "raw_entries": 0,
        "structured_entries": 0,
        "fallback_entries": 0,
        "doi_entries": 0,
        "enriched": 0,
        "title_only": 0,
        "unresolved": 0,
        "duplicates_skipped": 0,
        "errors": [],
    }

    def _norm(value) -> str:
        return str(value or "").strip().lower()

    for paper_idx, paper in enumerate(papers):
        filename = paper.get("filename", f"Paper {paper_idx+1}")
        if progress_callback:
            progress_callback(paper_idx + 1, len(papers),
                              f"Parsing references from {filename}…")

        # Step 1: regex extraction (fast, no API)
        parsed = parse_references_section(paper)
        raw_entries = parsed["entries"]
        diagnostics["raw_entries"] += len(raw_entries)

        # Step 2: LLM parsing for structured fields
        if client:
            try:
                structured = parse_references_with_llm(parsed["raw_text"], client, entries=raw_entries,
                                                       max_refs=max_refs_per_paper or 30)
            except Exception as e:
                structured = []
                diagnostics["errors"].append(f"{filename}: LLM reference parse failed: {e}")
        else:
            structured = []
        diagnostics["structured_entries"] += len(structured)

        # Merge: structured entries + DOI-only entries + raw-entry fallback.
        combined: list[dict] = list(structured)

        # The model was shown the first `max_refs_per_paper` entries. If it parsed most of them, those entries are
        # covered (it skips ones it cannot read); only the entries it never saw come from the rule-based parser.
        asked = raw_entries[:max_refs_per_paper or 30] if client else []
        model_covered = bool(asked) and len(structured) >= 0.6 * len(asked)

        for idx, entry in enumerate(raw_entries):
            if model_covered and idx < len(asked):
                continue
            fallback = _entry_to_reference(entry)
            title_key = _norm(fallback.get("title"))[:60]
            doi_key = _norm(fallback.get("doi"))
            if doi_key and any(_norm(e.get("doi")) == doi_key for e in combined):
                continue
            if any(_title_in_citation(e.get("title"), None, entry) for e in structured):
                continue                     # the model already parsed this very entry
            if title_key and len(title_key) > 10 and any(_norm(e.get("title"))[:60] == title_key for e in combined):
                continue
            combined.append(fallback)
            diagnostics["fallback_entries"] += 1

        # DOIs the entries did not account for (a split that lost one) come last.
        for doi in parsed["dois"]:
            if not any(_norm(e.get("doi")) == doi for e in combined):
                combined.append({"doi": doi, "title": "", "year": None, "authors": []})
                diagnostics["doi_entries"] += 1

        diagnostics["papers"].append({
            "filename": filename,
            "raw_entries": len(raw_entries),
            "structured_entries": len(structured),
            "combined_entries": len(combined),
            "dois": len(parsed["dois"]),
        })

        # Step 3: Enrich up to max_refs_per_paper per paper
        refs_to_process = combined if max_refs_per_paper is None else combined[:max_refs_per_paper]
        # The lookups are slow (2-5 s each, several providers per reference) and independent, so they run side by
        # side; the results are used in order below, exactly as before.
        pool = ThreadPoolExecutor(max_workers=_ENRICH_WORKERS)
        futures = {}
        for ref in refs_to_process:
            _dk, _tk = _norm(ref.get("doi")), _norm(ref.get("title"))[:60]
            if (_dk and _dk in seen_dois) or (_tk and len(_tk) > 10 and _tk in seen_titles):
                continue
            futures[id(ref)] = pool.submit(enrich_reference, ref, 0.25)
        for i, ref in enumerate(refs_to_process):
            doi_key   = _norm(ref.get("doi"))
            title_key = _norm(ref.get("title"))[:60]

            # Skip duplicates across papers
            if doi_key and doi_key in seen_dois:
                diagnostics["duplicates_skipped"] += 1
                continue
            if title_key and len(title_key) > 10 and title_key in seen_titles:
                diagnostics["duplicates_skipped"] += 1
                continue

            if progress_callback:
                progress_callback(
                    paper_idx + 1, len(papers),
                    f"Enriching ref {i+1}/{len(refs_to_process)} from {filename}...",
                )

            try:
                enriched = futures[id(ref)].result()
            except Exception as e:
                diagnostics["errors"].append(f"{filename}: enrichment failed for {ref.get('title','Unknown')[:80]}: {e}")
                diagnostics["unresolved"] += 1
                enriched = {
                    **ref,
                    "abstract": "",
                    "citations": 0,
                    "tier": 3,
                    "source": "enrichment_failed",
                }
            enriched["found_in_paper"] = filename
            enriched.setdefault("raw_reference", ref.get("raw_reference", ""))

            # Recompute the dedupe identity from what enrichment actually
            # RESOLVED, not from the raw input: two entries citing the same
            # paper via different titles (or a typo'd DOI) resolve to one
            # DOI and must be emitted once, under the resolved identity.
            out_doi_key   = _norm(enriched.get("doi")) or doi_key
            out_title_key = (_norm(enriched.get("title")) or title_key)[:60]

            if out_doi_key and out_doi_key in seen_dois:
                diagnostics["duplicates_skipped"] += 1
                continue
            if out_title_key and len(out_title_key) > 10 and out_title_key in seen_titles:
                diagnostics["duplicates_skipped"] += 1
                continue

            if out_doi_key:
                seen_dois.add(out_doi_key)
            if out_title_key and len(out_title_key) > 10:
                seen_titles.add(out_title_key)

            if enriched.get("tier") == 2 and enriched.get("abstract"):
                diagnostics["enriched"] += 1
            else:
                diagnostics["title_only"] += 1
            all_refs.append(enriched)
        pool.shutdown(wait=True)

    if return_diagnostics:
        return all_refs, diagnostics
    return all_refs


def summarise_reference_corpus(refs: list[dict]) -> dict:
    """
    Summary stats for display in the UI.

    Handles mixed year formats from different metadata sources:
    - int: 2010
    - str: "2010"
    - partial date strings: "2010 Jan", "2010-05-01"
    - None / invalid values
    """
    refs = refs or []

    tier2 = [r for r in refs if r.get("tier") == 2]
    tier3 = [r for r in refs if r.get("tier") == 3]
    with_abstract = [r for r in refs if r.get("abstract")]

    years = []
    for r in refs:
        raw_year = r.get("year")
        if raw_year is None:
            continue

        try:
            year = int(str(raw_year).strip()[:4])
        except (TypeError, ValueError):
            continue

        if 1800 <= year <= 2100:
            years.append(year)

    return {
        "total": len(refs),
        "tier2_abstract": len(tier2),
        "tier3_title": len(tier3),
        "with_abstract": len(with_abstract),
        "year_range": f"{min(years)}–{max(years)}" if years else "N/A",
    }
