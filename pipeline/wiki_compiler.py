"""
Stage 3: LLM Wiki Compiler — Karpathy Pattern
Compiles raw paper content into a structured, LLM-maintained wiki.
Instead of naive RAG (query → retrieve chunks → answer),
this compiles knowledge once at ingestion time.
"""
import json
from pipeline.pdf_parser import get_smart_excerpt
from pipeline.page_index import tree_to_summary
from domain_config import inject_domain_into_wiki_prompt
from utils.azure_client import unwrap, LLMCallError
from utils.database import compute_cache_key, get_cached_wiki_page, save_cached_wiki_page

# Bumped whenever WIKI_SYSTEM_PROMPT or the wiki-domain-injection logic changes,
# so old cached entries don't silently keep serving stale-logic results (AD-3).
# 2: the excerpt now keeps oversize sections (truncated) instead of dropping them,
# so pages cached at version 1 for papers with one huge section are empty and wrong.
# 3: the model now sees up to WIKI_EXCERPT_CHARS of the paper (was 10,000, i.e. 12-20%
# of a typical paper: e.g. a survey's own "Limitations" section never reached it).
WIKI_STAGE_VERSION = 3

# Gemini flash-lite has a 1M-token window and ~60k characters is about 15k tokens, so
# the whole of a normal paper fits for pennies. Anything longer is cut by priority.
WIKI_EXCERPT_CHARS = 60000


def _page_is_empty(page: dict) -> bool:
    """A page with no findings, contributions, methods or concepts carries no
    information; it must never be cached or served from the cache."""
    return not any(page.get(f) for f in ("key_findings", "contributions", "methods", "key_concepts"))
WIKI_DOMAIN_KEYS = ["wiki_focus", "wiki_entity_examples"]  # only keys inject_domain_into_wiki_prompt reads


WIKI_SYSTEM_PROMPT = """You are a research analyst compiling a structured knowledge wiki from a research paper.

Your task is to extract and organize the key information into a structured wiki page.
Be precise, specific, and evidence-based. Do not generalize or hallucinate.

Return ONLY a JSON object with this exact structure:
{
  "title": "Full paper title or best guess from content",
  "year": "Publication year if found, else null",
  "domain": "Primary research domain (e.g., NLP, Computer Vision, Healthcare AI)",
  "contributions": ["List of 3-6 specific technical contributions"],
  "methods": ["List of methods, models, algorithms used"],
  "datasets": ["List of datasets, cohorts or study populations used (with sample sizes where given)"],
  "key_findings": ["List of 5-10 specific findings. Include the actual numbers, effect sizes and p-values the paper reports"],
  "limitations": ["List of EXPLICITLY stated limitations — check the Limitations, Discussion and Conclusion sections; be specific, use the paper's own words"],
  "future_work": ["List of future work directions mentioned by authors"],
  "key_concepts": ["List of 8-12 important technical terms, acronyms, concepts"],
  "evaluated_on": ["Tasks or benchmarks the paper evaluates on"],
  "comparison_gap": "Any methods the paper acknowledges it did NOT compare against"
}"""


CROSS_LINK_SYSTEM_PROMPT = """You are a research analyst identifying connections between research papers.

Given wiki pages from multiple papers, identify:
1. Shared concepts, methods, or datasets across papers
2. Where one paper's limitation could be addressed by another paper's method
3. Where papers work on complementary problems
4. Contradictions or conflicting findings between papers

Return ONLY a JSON object:
{
  "shared_concepts": [{"concept": "name", "papers": ["paper1", "paper2"], "context": "how they relate"}],
  "limitation_bridges": [{"limitation_in": "paper name", "limitation": "text", "potential_solution_in": "paper name", "solution": "text"}],
  "complementary_pairs": [{"paper1": "name", "paper2": "name", "relationship": "explanation"}],
  "conflicts": [{"paper1": "name", "paper2": "name", "conflict": "explanation"}]
}"""


def compile_wiki_page(paper: dict, tree, client, domain_config: dict = None) -> dict:
    """
    Compile a wiki page for one paper using LLM.
    The wiki is the compiled, structured version — not raw text.
    """
    # B14 fix: check the cache before doing any work (Story 2.1 / AD-2 / AD-3).
    # B15 fix (review, 2026-08-04): an empty/whitespace-only full_text (e.g. a
    # scanned or image-only PDF) hashes identically for every such paper --
    # reading or writing the cache under that shared key would silently serve
    # one paper's cached wiki page to a completely different paper. Skip the
    # cache entirely (never read, never write) whenever there's no real
    # content to key on -- these always recompile, same as before this story.
    content = paper.get("full_text", "") or ""
    cacheable = bool(content.strip())
    cache_key = content_hash = domain_hash = None
    if cacheable:
        cache_key, content_hash, domain_hash = compute_cache_key(
            content, domain_config, WIKI_DOMAIN_KEYS, WIKI_STAGE_VERSION
        )
        cached = get_cached_wiki_page(cache_key)
        if cached is not None and not _page_is_empty(cached):
            # B15 fix (review): a cache hit means the CONTENT matched -- but
            # this call's own paper dict (e.g. a renamed re-upload of the same
            # PDF) still owns the filename/char_count attribution, not
            # whichever paper first populated this cache entry.
            cached = dict(cached)
            cached["source_file"] = paper["filename"]
            cached["char_count"] = paper.get("char_count", 0)
            return cached

    # Build a smart excerpt prioritizing key sections
    excerpt = get_smart_excerpt(paper, max_chars=WIKI_EXCERPT_CHARS)
    tree_outline = tree_to_summary(tree, max_chars=1500)

    user_prompt = f"""Paper filename: {paper['filename']}

Document Structure (PageIndex tree):
{tree_outline}

Paper Content (prioritizing Limitations, Future Work, Results, Abstract):
{excerpt}

Compile a structured wiki page from this paper."""

    try:
        raw = unwrap(client.chat_json(
            inject_domain_into_wiki_prompt(WIKI_SYSTEM_PROMPT, domain_config or {}),
            user_prompt, max_tokens=5000
        ))
    except LLMCallError as e:
        # B12 fix: don't let one paper's failed LLM call abort build_wiki()'s
        # whole batch — degrade to the same stub shape used for a JSON-parse failure.
        # B14 fix: never cache this fallback — a transient failure must not be
        # permanently frozen into the cache (AD-2).
        wiki = {"title": paper['filename'], "raw_response": f"[LLM call failed: {e.error.kind}] {e.error.detail}"}
        wiki["source_file"] = paper["filename"]
        wiki["char_count"] = paper.get("char_count", 0)
        return wiki

    cache_write_ok = False
    try:
        wiki = json.loads(raw)
        cache_write_ok = True  # genuine, cleanly-parsed success — the only case we cache
    except json.JSONDecodeError:
        # Attempt to extract JSON if wrapped in text
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                wiki = json.loads(match.group())
            except Exception:
                wiki = {"title": paper['filename'], "raw_response": raw}
        else:
            wiki = {"title": paper['filename'], "raw_response": raw}
        # B14 fix: even the recovered-from-text case above is still a malformed
        # stub, not confidently structured JSON from the primary path — never cache it.

    # Attach source reference
    wiki["source_file"] = paper["filename"]
    wiki["char_count"] = paper.get("char_count", 0)

    if cacheable and cache_write_ok and not _page_is_empty(wiki):
        save_cached_wiki_page(cache_key, content_hash, domain_hash, WIKI_STAGE_VERSION, wiki)
    return wiki


def compile_cross_links(wiki_pages: list, client) -> dict:
    """
    Identify cross-paper links and relationships.
    This is where gaps start to emerge — connections that don't exist yet.
    """
    # Build a compact summary of all wikis for the cross-link prompt
    wiki_summaries = []
    for w in wiki_pages:
        summary = {
            "title": w.get("title", w.get("source_file", "Unknown")),
            "contributions": w.get("contributions", []),
            "methods": w.get("methods", []),
            "limitations": w.get("limitations", []),
            "future_work": w.get("future_work", []),
            "key_concepts": w.get("key_concepts", []),
        }
        wiki_summaries.append(summary)

    user_prompt = f"""Here are wiki pages from {len(wiki_pages)} research papers:

{json.dumps(wiki_summaries, indent=2)}

Identify connections, bridges, and gaps between these papers."""

    raw = unwrap(client.chat_json(CROSS_LINK_SYSTEM_PROMPT, user_prompt, max_tokens=3000))

    try:
        cross_links = json.loads(raw)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                cross_links = json.loads(match.group())
            except Exception:
                cross_links = {}
        else:
            cross_links = {}

    return cross_links


def build_wiki(papers: list, trees: list, client, domain_config: dict = None) -> dict:
    """
    Build the full wiki: individual pages + cross-paper links.
    Returns: {pages: [...], cross_links: {...}, index: {...}}
    """
    # The papers are independent, so compile them in parallel (the calls were made
    # one after another before, so a slow call stalled everything behind it).
    # Order is preserved: pages[i] is always papers[i].
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, min(len(papers), 4))) as pool:
        pages = list(pool.map(
            lambda pt: compile_wiki_page(pt[0], pt[1], client, domain_config=domain_config),
            zip(papers, trees)))

    # Cross-links are a bonus on top of the per-paper pages: if that one call
    # fails the run carries on with no links and says so.
    warnings: list[str] = []
    try:
        cross_links = compile_cross_links(pages, client)
    except Exception as e:
        cross_links = {}
        warnings.append(f"Cross-paper links were skipped because the model call failed "
                        f"({type(e).__name__}: {e}).")

    # Build the index (table of contents)
    index = {
        "total_papers": len(pages),
        "domains": list(set(p.get("domain", "Unknown") for p in pages)),
        "all_concepts": [],
        "all_methods": [],
        "all_limitations": [],
        "all_future_work": [],
    }
    for p in pages:
        index["all_concepts"].extend(p.get("key_concepts", []))
        index["all_methods"].extend(p.get("methods", []))
        index["all_limitations"].extend(p.get("limitations", []))
        index["all_future_work"].extend(p.get("future_work", []))

    # Deduplicate
    for key in ["all_concepts", "all_methods", "all_limitations", "all_future_work"]:
        seen = set()
        deduped = []
        for item in index[key]:
            if item.lower() not in seen:
                seen.add(item.lower())
                deduped.append(item)
        index[key] = deduped

    return {
        "pages": pages,
        "cross_links": cross_links,
        "index": index,
        "warnings": warnings,
    }
