"""
Cross-screen content search (Clinova Phase 5, Epic 5.7).

The command palette could previously only find nav destinations and runs by
name -- none of the actual research content the app exists to surface. This
searches the project's basis run for papers, graph entities, gaps and
proposals, plus every run in the project by name/id.

Deliberately a plain substring/token match over the already-loaded run, not a
vector index: the whole searchable corpus for one project is a few hundred
short strings held in one JSONB row. Adding Qdrant (ADR-001) for that would
be infrastructure with nothing to do -- and a substring match is *honest*,
where an embedding match would return near-misses the user can't explain.
"""
from apps.api.models.search import SearchHit, SearchResponse
from apps.api.services.project_runs import get_basis_run, list_project_runs

MAX_HITS = 40

# Ranked so an exact title beats an incidental body mention.
_EXACT = 100
_PREFIX = 60
_WORD = 40
_SUBSTRING = 25
_BODY = 10


def _score(haystack: str, needle: str) -> int:
    h = (haystack or "").lower().strip()
    if not h:
        return 0
    if h == needle:
        return _EXACT
    if h.startswith(needle):
        return _PREFIX
    if any(word.startswith(needle) for word in h.split()):
        return _WORD
    if needle in h:
        return _SUBSTRING
    return 0


def _best(fields: list[tuple[str, str]], needle: str) -> tuple[int, str]:
    """Returns (score, which_field_matched) for the strongest matching field."""
    best_score, best_field = 0, ""
    for label, value in fields:
        s = _score(value, needle)
        if s > best_score:
            best_score, best_field = s, label
    return best_score, best_field


def search_project(project_id: str, query: str, limit: int = MAX_HITS) -> SearchResponse:
    needle = (query or "").lower().strip()
    if len(needle) < 2:
        return SearchResponse(
            query=query, project_id=project_id, hits=[], total=0,
            basis_note="Type at least 2 characters to search.",
            empty_reason="Query too short.",
        )

    basis_row, results = get_basis_run(project_id)
    hits: list[SearchHit] = []

    # Runs are searchable even when the project has no usable basis run.
    for run in list_project_runs(project_id):
        score, field = _best(
            [("name", run.get("name", "")), ("run id", run.get("id", ""))], needle,
        )
        if score:
            hits.append(SearchHit(
                kind="run", title=run.get("name", run["id"]),
                subtitle=f"Run · {str(run.get('created_at', ''))[:16].replace('T', ' ')}",
                href=f"/runs/{run['id']}", matched_on=field, score=score,
            ))

    if basis_row is None:
        return SearchResponse(
            query=query, project_id=project_id, hits=hits[:limit], total=len(hits),
            basis_note="No runs exist for this project yet.",
            empty_reason=None if hits else "No runs in this project yet.",
        )

    basis_note = (
        f"Searching run \"{basis_row['name']}\" ({basis_row['id'][:8]}) — "
        "the most recent run in this project."
    )

    for paper in results.get("papers") or []:
        wiki = paper.get("wiki") or {}
        filename = paper.get("filename", "")
        score, field = _best(
            [("title", wiki.get("title") or ""), ("filename", filename)], needle,
        )
        if not score:
            # A body match is real but weak -- ranked far below a title hit
            # rather than treated as equivalent.
            body = " ".join(
                str(x) for x in (wiki.get("contributions") or []) + (wiki.get("key_findings") or [])
            )
            if needle in body.lower():
                score, field = _BODY, "contributions/findings"
        if score:
            hits.append(SearchHit(
                kind="paper", title=wiki.get("title") or filename,
                subtitle="Paper", href=f"/corpus/papers/{filename}",
                matched_on=field, score=score,
            ))

    for entity in (results.get("graph") or {}).get("entities") or []:
        score, field = _best([("name", entity.get("name", ""))], needle)
        if score:
            hits.append(SearchHit(
                kind="entity", title=entity.get("name", ""),
                subtitle=f"Entity · {entity.get('type', 'unknown')}",
                href="/knowledge-graph", matched_on=field, score=score,
            ))

    for gap in results.get("gaps") or []:
        score, field = _best(
            [("title", gap.get("title", "")), ("description", gap.get("description", ""))], needle,
        )
        if score:
            hits.append(SearchHit(
                kind="gap", title=gap.get("title", ""),
                subtitle=f"Gap · {gap.get('validation_status', 'unknown')}",
                href="/gaps", matched_on=field, score=score,
            ))

    for proposal in results.get("proposals") or []:
        score, field = _best(
            [("title", proposal.get("title", "")),
             ("problem statement", proposal.get("problem_statement", "")),
             ("methodology", proposal.get("methodology", ""))],
            needle,
        )
        if score:
            hits.append(SearchHit(
                kind="proposal", title=proposal.get("title", ""),
                subtitle="Proposal", href="/proposals", matched_on=field, score=score,
            ))

    hits.sort(key=lambda h: (-h.score, h.title.lower()))
    total = len(hits)
    return SearchResponse(
        query=query, project_id=project_id, hits=hits[:limit], total=total,
        truncated=total > limit, basis_note=basis_note,
        empty_reason=None if hits else f"Nothing in this project matches \"{query}\".",
    )
