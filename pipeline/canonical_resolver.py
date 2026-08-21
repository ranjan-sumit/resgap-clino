"""
Canonical Reference & Paper Identity Resolution (Clinova Phase 1, Epic 1.3):
resolves an enriched reference dict (pipeline/reference_extractor.py's
extract_and_enrich_references() output) to one canonical identity using the
priority chain DOI -> PMID -> OpenAlex ID -> Semantic Scholar ID ->
normalized(title+first-author+year), per 05-data-architecture.md §5 and
ADR-007. Multiple provider records resolving to the same identity are
merged into one canonical entry; each contributing provider's raw record
is preserved separately, never discarded.

Directly targets the reference-contamination and duplicate-reference
findings from Phase 0 (evals/benchmarks/baseline/phase0-findings.md) --
see tests/test_canonical_resolver.py's regression cases against Benchmark
v1's real fixtures (evals/benchmarks/v1/).

Honest about what's actually captured today: OpenAlex work IDs are not
currently stored anywhere in pipeline/reference_extractor.py's enrichment
output (its OpenAlex query requests title/publication_year/
abstract_inverted_index/doi only, no `id` field) -- that priority level is
present in the chain's design but will not match until a future story adds
OpenAlex ID capture upstream. PMID is recoverable from the existing
PubMed enrichment's `url` field via a cheap regex, so it is implemented.

Relevance filtering (is this reference actually on-topic for the corpus'
domain, e.g. Data-17072026's AuDHD reference set including an unrelated
Spanish-textbook citation, evals/benchmarks/v1/
case-reference-contamination-espanol.json) is explicitly OUT OF SCOPE
here -- per 05-data-architecture.md §1's ingestion pipeline, relevance
filtering is a distinct stage that comes AFTER canonicalization and is not
yet built. A real, valid DOI still resolves VERIFIED even if the paper it
points to is off-topic; this module only answers "is this the same
reference as that one," not "does this reference belong in this corpus."
"""
import hashlib
import re

RESOLUTION_STAGE_VERSION = 1

_PMID_URL_PATTERN = re.compile(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)')

# Resolution status model, 05-data-architecture.md §6 / ADR-007.
_STATUS_BY_LEVEL = {
    "doi": "VERIFIED",
    "pmid": "VERIFIED",
    "openalex_id": "ACCEPTED",
    "ss_paper_id": "ACCEPTED",
    "arxiv_id": "ACCEPTED",
    "title_author_year": "ACCEPTED",
    "title_only_partial": "QUARANTINED",
    "none": "UNRESOLVED",
}


def _extract_pmid(ref: dict) -> str | None:
    # Clinova B21 fix: the actual enriched-reference field is `source`
    # (pipeline/reference_extractor.py's enrich_reference() final result
    # dict: `"source": meta.get("source_api", ...)`) -- an earlier version
    # of this function checked `source_api`, a key that only exists on each
    # provider function's own internal dict (e.g. _pubmed_search's return
    # value), never on the final ref dict any real caller actually sees.
    # PMID resolution would have silently never matched on real data; only
    # caught because the unit tests used the same wrong field name as the
    # implementation, rather than the real shape.
    if ref.get("source") != "pubmed":
        return None
    m = _PMID_URL_PATTERN.search(ref.get("url", "") or "")
    return m.group(1) if m else None


def _normalize_title(title) -> str:
    t = str(title or "").strip().lower()
    t = re.sub(r'[^a-z0-9 ]', '', t)
    return re.sub(r'\s+', ' ', t).strip()


def _first_author_surname(authors) -> str:
    if not authors:
        return ""
    first = authors[0]
    if isinstance(first, dict):
        first = first.get("name", "")
    parts = str(first).replace(",", " ").split()
    return parts[0].lower() if parts else ""


def resolve_status(identity_level: str) -> str:
    return _STATUS_BY_LEVEL.get(identity_level, "UNRESOLVED")


def resolve_canonical_identity(ref: dict) -> dict:
    """Resolve one reference dict to a canonical identity via the priority
    chain. Returns {"identity_key": str|None, "identity_level": str}."""
    doi = str(ref.get("doi") or "").strip().lower()
    if doi:
        return {"identity_key": hashlib.sha256(f"doi:{doi}".encode()).hexdigest(),
                "identity_level": "doi"}

    pmid = _extract_pmid(ref)
    if pmid:
        return {"identity_key": hashlib.sha256(f"pmid:{pmid}".encode()).hexdigest(),
                "identity_level": "pmid"}

    openalex_id = str(ref.get("openalex_id") or "").strip()
    if openalex_id:
        return {"identity_key": hashlib.sha256(f"openalex:{openalex_id}".encode()).hexdigest(),
                "identity_level": "openalex_id"}

    ss_id = str(ref.get("ss_paper_id") or "").strip()
    if ss_id:
        return {"identity_key": hashlib.sha256(f"ss:{ss_id}".encode()).hexdigest(),
                "identity_level": "ss_paper_id"}

    arxiv_id = str(ref.get("arxiv_id") or "").strip().lower()
    if arxiv_id:
        return {"identity_key": hashlib.sha256(f"arxiv:{arxiv_id}".encode()).hexdigest(),
                "identity_level": "arxiv_id"}

    norm_title = _normalize_title(ref.get("title"))
    author = _first_author_surname(ref.get("authors"))
    year = str(ref.get("year") or "").strip()

    if norm_title and author and year:
        composite = f"title:{norm_title}|author:{author}|year:{year}"
        return {"identity_key": hashlib.sha256(composite.encode()).hexdigest(),
                "identity_level": "title_author_year"}

    if norm_title:
        # Partial match only (title alone, missing author and/or year) --
        # exactly the fallback-resolution shape that must NOT be silently
        # trusted (Problem C). Flagged QUARANTINED, never auto-promoted.
        return {"identity_key": hashlib.sha256(f"title_only:{norm_title}".encode()).hexdigest(),
                "identity_level": "title_only_partial"}

    return {"identity_key": None, "identity_level": "none"}


def merge_canonical_references(refs: list[dict]) -> list[dict]:
    """Merge a list of enriched reference dicts into canonical papers:
    multiple provider records resolving to the same identity become one
    canonical entry, with each contributing provider's raw record preserved
    under `provider_records` (never discarded). References with no usable
    identity are kept as individual UNRESOLVED entries, never silently
    dropped."""
    by_identity: dict[str, dict] = {}
    unresolved: list[dict] = []

    for ref in refs:
        resolution = resolve_canonical_identity(ref)
        identity_key = resolution["identity_key"]
        identity_level = resolution["identity_level"]
        status = resolve_status(identity_level)

        if identity_key is None:
            entry = dict(ref)
            entry["resolution_status"] = status
            entry["identity_level"] = identity_level
            entry["provider_records"] = [dict(ref)]
            unresolved.append(entry)
            continue

        if identity_key not in by_identity:
            by_identity[identity_key] = {
                "identity_key": identity_key,
                "identity_level": identity_level,
                "resolution_status": status,
                # Canonical fields seeded from the first record to resolve
                # to this identity -- the representative view. Provider-
                # specific values remain fully available in provider_records.
                "title": ref.get("title"),
                "doi": ref.get("doi"),
                "year": ref.get("year"),
                "authors": ref.get("authors"),
                "provider_records": [],
            }
        by_identity[identity_key]["provider_records"].append(dict(ref))

    return list(by_identity.values()) + unresolved


def filter_and_dedupe_references(refs: list[dict]) -> tuple[list[dict], dict]:
    """Application-facing helper (Story 1.3.3's default-safe corpus
    filtering, wired into app.py): filters an enriched reference list down
    to VERIFIED/ACCEPTED entries only, deduplicating by canonical identity,
    while preserving each surviving entry's ORIGINAL flat shape (title,
    doi, abstract, tier, ... ) rather than merge_canonical_references()'s
    wrapper shape -- so downstream code that already expects a flat
    reference list (summarise_reference_corpus, assign_tiers, etc. in
    pipeline/paper_manager.py and pipeline/reference_extractor.py) keeps
    working unchanged. QUARANTINED/UNRESOLVED entries and duplicates are
    dropped from the returned list but counted in the returned
    diagnostics -- never silently discarded without a trace."""
    seen_identities: set[str] = set()
    trusted: list[dict] = []
    status_counts = {"VERIFIED": 0, "ACCEPTED": 0, "QUARANTINED": 0, "UNRESOLVED": 0}
    duplicates_removed = 0

    for ref in refs:
        resolution = resolve_canonical_identity(ref)
        status = resolve_status(resolution["identity_level"])
        status_counts[status] = status_counts.get(status, 0) + 1

        if status not in ("VERIFIED", "ACCEPTED"):
            continue

        identity_key = resolution["identity_key"]
        if identity_key and identity_key in seen_identities:
            duplicates_removed += 1
            continue
        if identity_key:
            seen_identities.add(identity_key)

        entry = dict(ref)
        entry["resolution_status"] = status
        trusted.append(entry)

    return trusted, {
        "input_count": len(refs),
        "trusted_count": len(trusted),
        "status_counts": status_counts,
        "duplicates_removed": duplicates_removed,
    }
