from pydantic import BaseModel


class SearchHit(BaseModel):
    """One result. `href` is the real destination the web app should
    navigate to, resolved server-side so the client never has to know how a
    given kind maps to a route."""
    kind: str          # paper | entity | gap | proposal | run
    title: str
    subtitle: str | None = None
    href: str
    # Where the match actually occurred ("title", "description", ...), so the
    # UI can say why a result is here rather than showing an unexplained hit.
    matched_on: str
    score: int


class SearchResponse(BaseModel):
    query: str
    project_id: str
    hits: list[SearchHit]
    total: int
    truncated: bool = False
    basis_note: str
    empty_reason: str | None = None
