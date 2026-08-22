"""
Embedding + reranking (Clinova Phase 3, Epic 3.5; resolves PRD FR-17/FR-18)
via NVIDIA NIM hosted models, not local BGE-M3/BGE-reranker as
04-ai-research-architecture.md's port table originally named. Same
"superseded, not silently rewritten" treatment as ADR-002 (Neo4j ->
ArcadeDB): this machine has no GPU, so local inference would be CPU-only
and slow, and NVIDIA NIM already hosts equivalent embedding/reranking
models on the same integrate.api.nvidia.com / ai.api.nvidia.com endpoints
this app already calls for every other AI step, using the same
NVIDIA_API_KEY already in .env -- zero new credentials, zero local model
downloads.

Model choice, checked live against the real API before picking, not just
docs (docs proved stale twice in a row here): BAAI's bge-m3 is hosted on
NVIDIA NIM but scheduled for deprecation 2026-08-24. The next two models
tried by name from NVIDIA's own docs/model-card pages --
nvidia/llama-3.2-nv-embedqa-1b-v2 + nvidia/llama-3.2-nv-rerankqa-1b-v2,
then nvidia/llama-3.2-nemoretriever-300m-embed-v2 -- both live-returned
HTTP 410 Gone ("reached its end of life on 2026-05-18" / "2026-02-26")
despite the docs pages showing no deprecation notice. Resolved by
querying GET https://integrate.api.nvidia.com/v1/models (the same
OpenAI-compatible model-listing endpoint every NVIDIA-hosted call in
this app already has access to) for what is CURRENTLY actually hosted,
then live-testing candidates from that list directly against the real
API. nvidia/llama-nemotron-embed-1b-v2 (embedding, confirmed 200,
2048-dim) and nvidia/llama-nemotron-rerank-1b-v2 (reranking, confirmed
200) are what's live as of 2026-08-22 -- if NVIDIA retires these too,
re-run the same GET /v1/models + live-probe process, don't guess a new
name from a docs page again.

No vector database (Qdrant or otherwise) is used or needed: Gap
Challenger's candidate pool per gap challenge is Semantic Scholar/arXiv
results for a handful of query families -- tens of candidates, not a
corpus to index. NVIDIA's rerank endpoint accepts passages directly (up
to 512); there is nothing here for a persistent ANN vector store to do
that a single stateless rerank call doesn't already cover at this scale.

llama-3.2-nv-embedqa-1b-v2 is an asymmetric embedding model -- NVIDIA's
API rejects a call missing `input_type` ("query" for the one search
query being embedded, "passage" for documents being searched over).
embed_texts() is exposed for completeness / a future embedding-similarity
use, but Epic 3.5's actual current integration (pipeline/gap_challenger.py)
only needs rerank_candidates() -- the rerank endpoint scores query-passage
relevance directly without the caller computing cosine similarity itself.
"""
import requests
from openai import OpenAI

from utils.azure_client import NVIDIA_BASE_URL

EMBEDDING_MODEL = "nvidia/llama-nemotron-embed-1b-v2"
RERANK_MODEL = "nvidia/llama-nemotron-rerank-1b-v2"
RERANK_URL = f"https://ai.api.nvidia.com/v1/retrieval/{RERANK_MODEL}/reranking"
_TIMEOUT = 30


def embed_texts(texts: list[str], api_key: str, input_type: str = "passage") -> list[list[float]]:
    """input_type must be "query" for a search query, "passage" for
    documents -- see module docstring. Returns [] for empty input without
    an API call (honest no-op, not a wasted request)."""
    if not texts:
        return []
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key)
    response = client.embeddings.create(
        input=texts, model=EMBEDDING_MODEL, extra_body={"input_type": input_type},
    )
    return [d.embedding for d in response.data]


def rerank_candidates(query: str, passages: list[str], api_key: str) -> list[dict]:
    """Returns [{"index": i, "score": float}, ...] sorted descending by
    score, `index` referring to `passages`' original position. Raises on
    a genuine HTTP failure (network error, non-2xx, timeout) rather than
    swallowing it -- callers degrade to unranked order on failure,
    matching this codebase's existing per-stage failure-isolation
    convention (e.g. pipeline/gap_challenger.py's per-gap Challenger
    isolation) rather than hiding the failure in this module."""
    if not passages or not query:
        return []
    resp = requests.post(
        RERANK_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": RERANK_MODEL,
            "query": {"text": query},
            "passages": [{"text": p} for p in passages],
            "truncate": "END",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    rankings = resp.json().get("rankings", [])
    return [{"index": r["index"], "score": r["logit"]} for r in rankings]
