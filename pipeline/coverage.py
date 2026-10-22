"""
Per-paper coverage of a finished run: did EVERY uploaded paper make it through each stage?

A run can look fine in aggregate while one paper contributed nothing (an empty wiki page, no
evidence, no graph entities). This table makes that visible, one row per paper.
"""
import re

_WIKI_LISTS = ("contributions", "methods", "datasets", "key_findings", "limitations", "future_work", "key_concepts")


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _is_paper(ref, filename: str, title: str) -> bool:
    """True if `ref` (a title or filename used by some stage) names this paper."""
    r = _norm(ref)
    if not r:
        return False
    for name in (filename, title):
        n = _norm(name)
        if n and (r == n or (min(len(n), len(r)) >= 12 and (n in r or r in n))):
            return True
    return False


def paper_coverage(results: dict) -> list:
    """One dict per paper: study type, wiki items, quoted evidence, graph entities, gaps and
    proposals that rest on it, plus a status ("ok" / "check") and the reasons for "check"."""
    papers = results.get("papers", [])
    evidence = results.get("evidence_objects") or {}
    profiles = results.get("paper_profiles") or {}
    entities = (results.get("graph") or {}).get("entities", [])
    gaps = results.get("gaps", [])
    proposals = results.get("proposals", [])
    rows = []
    for p in papers:
        filename = p.get("filename", "")
        wiki = p.get("wiki") or {}
        title = wiki.get("title") or filename
        ev = evidence.get(filename) or []
        quoted = sum(1 for e in ev if (e.get("provenance") or {}).get("quote"))
        n_wiki = sum(len(wiki.get(k) or []) for k in _WIKI_LISTS)
        n_entities = sum(1 for e in entities if any(_is_paper(ref, filename, title) for ref in (e.get("papers") or [])))
        n_gaps = sum(1 for g in gaps if any(_is_paper(ref, filename, title) for ref in (g.get("supporting_papers") or [])))
        gap_ids = {g.get("gap_id") for g in gaps
                   if any(_is_paper(ref, filename, title) for ref in (g.get("supporting_papers") or []))}
        n_props = sum(1 for pr in proposals if pr.get("addresses_gap_id") in gap_ids
                      or any(_is_paper(ref, filename, title) for ref in (pr.get("builds_on") or [])))
        problems = []
        if n_wiki == 0:
            problems.append("empty wiki page")
        if not ev:
            problems.append("no evidence extracted")
        elif ev and quoted == 0:
            problems.append("evidence has no verified quotes")
        if n_entities == 0:
            problems.append("no graph entities")
        rows.append({
            "filename": filename, "title": title,
            "study_type": (profiles.get(filename) or {}).get("study_type"),
            "wiki_items": n_wiki, "evidence": len(ev), "quoted": quoted,
            "entities": n_entities, "gaps": n_gaps, "proposals": n_props,
            "status": "check" if problems else "ok", "problems": problems,
        })
    return rows
