"""
Stage 5: Literature Scout. Checks each research gap against the published literature.

What was wrong with the earlier validator (pipeline/academic_search.py::validate_gaps):
  - its query was the gap's whole title (plus a domain word), and arXiv ANDs every word, so
    nothing specific ever matched: in a real run EVERY gap came back "open, no papers found";
  - arXiv covers physics, computing and maths, not biomedicine, and there was no biomedical source;
  - a Semantic Scholar failure (rate limit) was read as "no papers", and "open" was then cached.

The scout:
  1. a Query Planner agent writes 3 SHORT keyword queries per gap, in the field's own vocabulary
     (not the gap's framing), in one batched call;
  2. each query goes to Semantic Scholar (throttled to its rate limit) and Europe PMC (biomedical,
     free, no key); arXiv gets the first query for computing-flavoured corpora; results are merged
     and de-duplicated;
  3. an assessor reads up to 10 titles and abstracts and decides open / partial / solved, naming the
     closest paper;
  4. if the search itself failed, the gap is "unverified", never "open", and nothing is cached.
"""
import json
import re
import threading
import time

import requests

from pipeline import academic_search as acad
from utils.azure_client import LLMCallError, unwrap
from utils.database import compute_cache_key, get_cached_gap_validation, save_cached_gap_validation

SCOUT_STAGE_VERSION = 4            # its own cache namespace: v3 entries include false "open" verdicts
EUROPE_PMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
MAX_PAPERS_ASSESSED = 10
QUERIES_PER_GAP = 3

_JUNK_TITLES = frozenset({"abstract", "introduction", "summary", "editorial", "correction", "erratum",
                          "letter to the editor", "book review"})

_S2_LOCK = threading.Lock()
_S2_LAST = [0.0]


def _s2_wait(has_key: bool) -> None:
    """Semantic Scholar allows about 1 request/second with a key and far fewer without one."""
    interval = 1.15 if has_key else 3.5
    with _S2_LOCK:
        gap = interval - (time.monotonic() - _S2_LAST[0])
        if gap > 0:
            time.sleep(gap)
        _S2_LAST[0] = time.monotonic()


# ── providers ───────────────────────────────────────────────────────────────

def _search_s2(query: str, api_key: str) -> tuple[list, bool]:
    _s2_wait(bool(api_key))
    papers, ok = acad._search_semantic_scholar_with_status(query, limit=6, api_key=api_key)
    if not ok:                                  # one more try after a pause: 429s are usually brief
        time.sleep(4)
        _s2_wait(bool(api_key))
        papers, ok = acad._search_semantic_scholar_with_status(query, limit=6, api_key=api_key)
    return papers, ok


def _search_europepmc(query: str, limit: int = 6) -> tuple[list, bool]:
    """Europe PMC: PubMed-indexed biomedical literature plus preprints; abstracts included."""
    try:
        resp = requests.get(EUROPE_PMC_BASE, params={"query": query, "format": "json", "resultType": "core",
                                                     "pageSize": limit}, timeout=20)
        resp.raise_for_status()
        results = (resp.json().get("resultList") or {}).get("result") or []
    except Exception:
        return [], False
    out = []
    for r in results:
        title = (r.get("title") or "").strip().rstrip(".")
        if len(title) < 12 or title.lower() in _JUNK_TITLES:     # e.g. a record whose title is just "Abstract"
            continue
        year = r.get("pubYear")
        out.append({
            "title": title,
            "year": int(year) if str(year).isdigit() else None,
            "abstract": re.sub(r"<[^>]+>", "", r.get("abstractText") or "")[:600],
            "citations": r.get("citedByCount"),
            "authors": [a.strip() for a in (r.get("authorString") or "").split(",")[:3] if a.strip()],
            "source": "Europe PMC",
        })
    return out, True


def _merge(papers: list) -> list:
    """De-duplicate by normalised title, keeping the entry with the longest abstract."""
    best = {}
    for p in papers:
        key = re.sub(r"[^a-z0-9]+", "", (p.get("title") or "").lower())
        if not key:
            continue
        if key not in best or len(p.get("abstract") or "") > len(best[key].get("abstract") or ""):
            best[key] = p
    return list(best.values())


# ── agents ──────────────────────────────────────────────────────────────────

_PLANNER_PROMPT = f"""You are a Query Planner for a literature search. For each research gap, write {QUERIES_PER_GAP} SHORT search queries that would find papers already doing the work the gap proposes.

Rules:
- 3 to 7 content words each, in the field's standard terminology. NOT the gap's title or framing: never use words like missing, lack, no, unexplored, future, gap, novel.
- Query 1: the core intervention or approach + the system or population it would be applied to.
- Query 2: the condition or topic + the key method or measurement.
- Query 3: a broader query on the topic that would surface any closely related work.
Return ONLY JSON: {{"queries": [ {{"id": "G1", "queries": ["...", "...", "..."]}} ]}}"""

_ASSESSOR_PROMPT = """You are a strict research-gap validator. Decide whether the published papers found already cover this gap.

- "solved": one or more papers already do what the gap proposes (the same system or population, the same method, the same outcome).
- "partial": related work exists (a similar system, only part of the question, or a different population) but the specific gap is still unaddressed.
- "open": none of the papers does it.
Be strict about "same": a related topic is NOT the same work. Prefer "partial" over "solved" unless a paper clearly does it.

Return ONLY JSON: {"status": "open|partial|solved", "reasoning": "1-2 sentences naming the closest paper and how it differs", "relevant": [numbers of the up to 3 closest papers]}"""


def _fallback_queries(gap: dict) -> list:
    """Used when the planner fails: key terms from the title, with gap-framing words removed."""
    title = acad._strip_negation_framing(gap.get("title", ""))
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9\-']+", title) if w.lower() not in acad._ARXIV_NOISE_WORDS]
    out = [" ".join(words[:7])]
    if len(words) > 7:
        out.append(" ".join(words[-6:]))
    return [q for q in out if q]


def plan_queries(gaps: list, client) -> tuple[dict, str | None]:
    """{gap_id: [queries]} from one batched planner call, plus an error note (or None)."""
    if not gaps:
        return {}, None
    items = [{"id": f"G{i + 1}", "title": g.get("title"), "description": g.get("description"),
              "missing_connection": g.get("missing_connection")} for i, g in enumerate(gaps)]
    try:
        raw = unwrap(client.chat_json(_PLANNER_PROMPT, "Gaps:\n" + json.dumps(items, indent=1, ensure_ascii=False),
                                      max_tokens=3000))
    except LLMCallError as e:
        return {}, f"query planner failed: {e.error.kind}"
    text = re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$', '', (raw or "").strip())
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        try:
            value = json.loads(m.group()) if m else None
        except json.JSONDecodeError:
            value = None
    rows = value.get("queries") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        return {}, "query planner reply could not be read"
    by_id = {}
    for r in rows:
        if isinstance(r, dict) and isinstance(r.get("queries"), list):
            qs = [re.sub(r"\s+", " ", str(q)).strip() for q in r["queries"] if str(q).strip()]
            by_id[str(r.get("id"))] = qs[:QUERIES_PER_GAP]
    return {g.get("gap_id"): by_id.get(f"G{i + 1}", []) for i, g in enumerate(gaps)}, None


def _assess(gap: dict, papers: list, client) -> tuple[dict, bool]:
    """(result, genuine). genuine=False when the model failed and a heuristic stood in."""
    if not papers:
        return {"status": "open", "reasoning": "The searches returned no related papers.", "relevant": []}, True
    shown = papers[:MAX_PAPERS_ASSESSED]
    listing = "\n".join(f"[{i + 1}] {p['title']} ({p.get('year') or 'n.d.'}) — {(p.get('abstract') or 'no abstract')[:450]}"
                        for i, p in enumerate(shown))
    user = (f"GAP: {gap.get('title')}\nDESCRIPTION: {gap.get('description')}\n"
            f"WHAT IS MISSING: {gap.get('missing_connection') or ''}\n\nPAPERS FOUND:\n{listing}")
    try:
        raw = unwrap(client.chat_json(_ASSESSOR_PROMPT, user, max_tokens=500))
        m = re.search(r'\{.*\}', raw or "", re.DOTALL)
        result = json.loads(m.group()) if m else None
        if isinstance(result, dict) and result.get("status") in ("open", "partial", "solved"):
            rel = [n for n in (result.get("relevant") or []) if isinstance(n, int) and 1 <= n <= len(shown)]
            result["relevant"] = rel[:3]
            return result, True
    except Exception:
        pass
    return {"status": "partial", "reasoning": "Related papers were found; the assessment model did not answer.",
            "relevant": []}, False


# ── orchestration ───────────────────────────────────────────────────────────

def scout_gaps(gaps: list, client, domain_config: dict = None, ss_api_key: str = "", use_arxiv: bool = False,
               progress_callback=None) -> dict:
    """Validates `gaps` in place (validation_status, validation_reasoning, existing_papers,
    search_query_used, search_providers). Returns {"gaps": gaps, "diagnostics": {...}}."""
    diag = {"planner_error": None, "unverified": 0, "cache_hits": 0, "searched": 0}
    cached_ids, to_search = set(), []
    keyed = {}
    for g in gaps:
        content = f"{g.get('title') or ''}\n{g.get('description') or ''}"
        if not content.strip():
            to_search.append(g)
            continue
        key, gap_hash, domain_hash = compute_cache_key(content, domain_config, ["search_boost_terms"],
                                                       SCOUT_STAGE_VERSION)
        keyed[id(g)] = (key, gap_hash, domain_hash)
        hit = get_cached_gap_validation(key)
        if hit is not None:
            g["validation_status"] = hit.get("validation_status", "open")
            g["validation_reasoning"] = hit.get("validation_reasoning", "")
            g["existing_papers"] = hit.get("existing_papers", [])
            g["search_query_used"] = hit.get("search_query_used", "")
            g["search_providers"] = hit.get("search_providers", {})
            cached_ids.add(id(g))
            diag["cache_hits"] += 1
        else:
            to_search.append(g)

    queries_by_gap, planner_error = plan_queries(to_search, client) if to_search else ({}, None)
    diag["planner_error"] = planner_error

    for idx, g in enumerate(gaps):
        if progress_callback:
            try:
                progress_callback(idx, len(gaps))
            except Exception:
                pass
        if id(g) in cached_ids:
            continue
        queries = queries_by_gap.get(g.get("gap_id")) or _fallback_queries(g)
        flags = {"semantic_scholar": [], "europe_pmc": [], "arxiv": []}
        found = []
        for q in queries:
            papers, ok = _search_s2(q, ss_api_key)
            found += papers
            flags["semantic_scholar"].append(ok)
            papers, ok = _search_europepmc(q)
            found += papers
            flags["europe_pmc"].append(ok)
        if use_arxiv and queries:
            papers, ok = acad._search_arxiv_with_status(queries[0], limit=3)
            found += papers
            flags["arxiv"].append(ok)
            time.sleep(0.4)
        flags = {name: v for name, v in flags.items() if v}
        providers = {name: (all(v) if v else None) for name, v in flags.items()}
        any_ok = any(any(v) for v in flags.values())
        degraded = any(not all(v) for v in flags.values())
        merged = _merge(found)
        diag["searched"] += 1

        g["search_query_used"] = " | ".join(queries)
        g["search_providers"] = providers
        if not any_ok:
            g["validation_status"] = "unverified"
            g["validation_reasoning"] = ("The literature search was unavailable (all providers failed), "
                                         "so this gap could not be checked against published work.")
            g["existing_papers"] = []
            diag["unverified"] += 1
            continue

        result, genuine = _assess(g, merged, client)
        shown = merged[:MAX_PAPERS_ASSESSED]
        relevant = [shown[n - 1] for n in result.get("relevant", [])]
        rest = [p for p in shown if p not in relevant]
        g["validation_status"] = result["status"]
        reasoning = result.get("reasoning", "")
        if degraded:
            failed = [n.replace("_", " ") for n, ok in providers.items() if ok is False]
            reasoning += f" (Search was incomplete: {', '.join(failed)} did not respond.)"
        g["validation_reasoning"] = reasoning
        g["existing_papers"] = (relevant + rest)[:5]
        g["papers_considered"] = len(merged)

        key = keyed.get(id(g))
        if key and genuine and not degraded:
            save_cached_gap_validation(key[0], key[1], key[2], SCOUT_STAGE_VERSION, {
                "validation_status": g["validation_status"], "validation_reasoning": g["validation_reasoning"],
                "existing_papers": g["existing_papers"], "search_query_used": g["search_query_used"],
                "search_providers": providers,
            })
    return {"gaps": gaps, "diagnostics": diag}
