"""
SQLite Run History Database
Saves every pipeline run so results persist across page refreshes.
Users can click any past run to restore its full results instantly.

Schema:
  runs   — one row per run (metadata + compressed JSON blob)
  papers — one row per paper per run (for quick listing)
"""
import sqlite3
import json
import gzip
import os
import hashlib
from datetime import datetime
from pathlib import Path

# Database lives next to the app so it persists across restarts
DB_DIR  = Path(__file__).parent.parent / "data"
DB_PATH = DB_DIR / "run_history.db"


def _get_conn() -> sqlite3.Connection:
    DB_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call multiple times."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            domain      TEXT,
            interest    TEXT,
            n_papers    INTEGER,
            n_gaps      INTEGER,
            n_proposals INTEGER,
            has_comp    INTEGER DEFAULT 0,
            results_gz  BLOB NOT NULL
        );

        CREATE TABLE IF NOT EXISTS papers (
            run_id    TEXT NOT NULL,
            filename  TEXT,
            title     TEXT,
            tier      INTEGER DEFAULT 1,
            FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS wiki_pages (
            cache_key           TEXT PRIMARY KEY,
            content_hash        TEXT,
            domain_hash         TEXT,
            stage_logic_version INTEGER,
            wiki_json           TEXT
        );

        CREATE TABLE IF NOT EXISTS parameters (
            cache_key           TEXT PRIMARY KEY,
            content_hash        TEXT,
            stage_logic_version INTEGER,
            params_json         TEXT
        );

        CREATE TABLE IF NOT EXISTS docling_extractions (
            cache_key           TEXT PRIMARY KEY,
            content_hash        TEXT,
            stage_logic_version INTEGER,
            extraction_json     TEXT
        );

        CREATE TABLE IF NOT EXISTS evidence_objects (
            cache_key           TEXT PRIMARY KEY,
            content_hash        TEXT,
            stage_logic_version INTEGER,
            evidence_json       TEXT
        );

        CREATE TABLE IF NOT EXISTS "references" (
            cache_key           TEXT PRIMARY KEY,
            doi_or_title_hash   TEXT,
            stage_logic_version INTEGER,
            enriched_json       TEXT
        );

        CREATE TABLE IF NOT EXISTS gap_validations (
            cache_key           TEXT PRIMARY KEY,
            gap_hash            TEXT,
            domain_hash         TEXT,
            stage_logic_version INTEGER,
            validation_json     TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_papers_run   ON papers(run_id);
    """)
    conn.commit()
    conn.close()


def compute_cache_key(
    content: str,
    domain_config: dict | None,
    relevant_domain_keys: list[str],
    stage_logic_version: int,
) -> tuple[str, str, str]:
    """
    Shared cache-key computation for all Epic 2 cache tables (AD-3).
    Returns (cache_key, content_hash, domain_hash).

    domain_hash is only meaningful for domain-conditioned stages: pass the
    exact subset of domain_config keys that actually affect that stage's
    prompt (e.g. ["wiki_focus", "wiki_entity_examples"] for wiki compilation)
    so an unrelated domain_config change doesn't cause a spurious cache miss.
    Pass an empty relevant_domain_keys for a domain-invariant stage —
    domain_hash will be the literal string "none" regardless of domain_config.

    content=None/"" is not special-cased here (it hashes like any other
    string) — callers whose content can legitimately be empty (e.g. a paper
    with no extractable text) must decide for themselves whether an empty
    string is safe to cache under, since every such input collides on the
    same hash. See Story 2.1 Dev Notes / review findings for wiki_compiler's
    handling of this.
    """
    content_hash = hashlib.sha256((content or "").encode()).hexdigest()
    if relevant_domain_keys:
        # Review fix (Story 2.4): sort_keys=True only orders dict keys, not
        # list element order -- a list-valued domain_config field (e.g.
        # search_boost_terms) carrying the same elements in a different
        # order would otherwise hash differently and cause a spurious miss.
        def _canonicalize(value):
            if isinstance(value, list):
                return sorted(value, key=str)
            return value

        subset = {k: _canonicalize((domain_config or {}).get(k)) for k in relevant_domain_keys}
        domain_hash = hashlib.sha256(
            json.dumps(subset, sort_keys=True, default=str).encode()
        ).hexdigest()
    else:
        domain_hash = "none"
    cache_key = f"{content_hash}:{domain_hash}:{stage_logic_version}"
    return cache_key, content_hash, domain_hash


def get_cached_wiki_page(cache_key: str) -> dict | None:
    """Return the cached wiki page for cache_key, or None on a cache miss
    (including a corrupted/unparseable row, treated as a miss rather than
    letting a storage-layer problem crash the caller)."""
    init_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT wiki_json FROM wiki_pages WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row["wiki_json"])
    except json.JSONDecodeError:
        return None


def save_cached_wiki_page(
    cache_key: str, content_hash: str, domain_hash: str,
    stage_logic_version: int, wiki_json: dict,
) -> None:
    """Cache a compiled wiki page. Only call this for a genuine, cleanly-
    parsed success — never for an LLMCallError fallback or a malformed-JSON
    stub (see Story 2.1 Dev Notes)."""
    init_db()
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO wiki_pages
           (cache_key, content_hash, domain_hash, stage_logic_version, wiki_json)
           VALUES (?,?,?,?,?)""",
        (cache_key, content_hash, domain_hash, stage_logic_version,
         json.dumps(wiki_json, default=str)),
    )
    conn.commit()
    conn.close()


def get_cached_parameters(cache_key: str) -> list | None:
    """Return the cached parameter list for cache_key, or None on a cache
    miss (including a corrupted/unparseable row, a NULL row, or a row whose
    JSON parsed but isn't actually a list)."""
    init_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT params_json FROM parameters WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        parsed = json.loads(row["params_json"])
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, list) else None


def save_cached_parameters(
    cache_key: str, content_hash: str, stage_logic_version: int, params_json: list,
) -> None:
    """Cache a paper's extracted parameters. No domain_hash column — param
    extraction is domain-invariant (AD-3). Only call this for a genuine
    Success result — never for an LLMCallError path (see Story 2.2 Dev Notes)."""
    init_db()
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO parameters
           (cache_key, content_hash, stage_logic_version, params_json)
           VALUES (?,?,?,?)""",
        (cache_key, content_hash, stage_logic_version, json.dumps(params_json, default=str)),
    )
    conn.commit()
    conn.close()


def get_cached_docling_extraction(cache_key: str) -> dict | None:
    """Return the cached Docling extraction for cache_key, or None on a
    cache miss (including a corrupted/unparseable row). Docling is measured
    at ~1.1GB RSS / ~90s per paper on CPU (Clinova Story 1.1.1a,
    evals/benchmarks/baseline/docling-resource-measurement.md) -- caching is
    a binding requirement, not an optimization, at that cost."""
    init_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT extraction_json FROM docling_extractions WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        parsed = json.loads(row["extraction_json"])
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def save_cached_docling_extraction(
    cache_key: str, content_hash: str, stage_logic_version: int, extraction_json: dict,
) -> None:
    """Cache a paper's Docling extraction. No domain_hash column -- PDF
    structural extraction is domain-invariant, same as `parameters`."""
    init_db()
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO docling_extractions
           (cache_key, content_hash, stage_logic_version, extraction_json)
           VALUES (?,?,?,?)""",
        (cache_key, content_hash, stage_logic_version, json.dumps(extraction_json, default=str)),
    )
    conn.commit()
    conn.close()


def get_cached_evidence_objects(cache_key: str) -> list | None:
    """Return the cached Evidence Object list for cache_key, or None on a
    cache miss (including a corrupted/unparseable row, or a row whose JSON
    parsed but isn't actually a list). Clinova Phase 2, Story 2.2.1."""
    init_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT evidence_json FROM evidence_objects WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        parsed = json.loads(row["evidence_json"])
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, list) else None


def save_cached_evidence_objects(
    cache_key: str, content_hash: str, stage_logic_version: int, evidence_json: list,
) -> None:
    """Cache a paper's extracted Evidence Objects. No domain_hash column --
    evidence extraction is domain-invariant (it reads the paper's own wiki
    fields, not domain_config), same reasoning as `parameters`."""
    init_db()
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO evidence_objects
           (cache_key, content_hash, stage_logic_version, evidence_json)
           VALUES (?,?,?,?)""",
        (cache_key, content_hash, stage_logic_version, json.dumps(evidence_json, default=str)),
    )
    conn.commit()
    conn.close()


def get_cached_reference(cache_key: str) -> dict | None:
    """Return the cached enriched-reference dict for cache_key, or None on a
    cache miss (including a corrupted/unparseable row, a NULL row, or a row
    whose JSON parsed but isn't actually a dict)."""
    init_db()
    conn = _get_conn()
    row = conn.execute(
        'SELECT enriched_json FROM "references" WHERE cache_key = ?', (cache_key,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        parsed = json.loads(row["enriched_json"])
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def save_cached_reference(
    cache_key: str, doi_or_title_hash: str, stage_logic_version: int, enriched_json: dict,
) -> None:
    """Cache one reference's enriched metadata. No domain_hash column --
    reference enrichment is domain-invariant (AD-3). Only call this for a
    genuine Tier-2 metadata hit -- never for the Tier-3 "parsed_only"
    fallback (see Story 2.3 Dev Notes)."""
    init_db()
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO "references"
           (cache_key, doi_or_title_hash, stage_logic_version, enriched_json)
           VALUES (?,?,?,?)""",
        (cache_key, doi_or_title_hash, stage_logic_version, json.dumps(enriched_json, default=str)),
    )
    conn.commit()
    conn.close()


_GAP_VALIDATION_REQUIRED_KEYS = {
    "validation_status", "validation_reasoning", "existing_papers", "search_query_used",
}


def get_cached_gap_validation(cache_key: str) -> dict | None:
    """Return the cached gap-validation dict for cache_key, or None on a
    cache miss (including a corrupted/unparseable row, a NULL row, a row
    whose JSON parsed but isn't actually a dict, or a dict missing one of
    the four fields callers rely on -- a structurally-incomplete row must
    degrade to a miss, not crash the caller)."""
    init_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT validation_json FROM gap_validations WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        parsed = json.loads(row["validation_json"])
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict) or not _GAP_VALIDATION_REQUIRED_KEYS <= parsed.keys():
        return None
    return parsed


def save_cached_gap_validation(
    cache_key: str, gap_hash: str, domain_hash: str, stage_logic_version: int, validation_json: dict,
) -> None:
    """Cache one gap's validation result. Only call this for a genuine,
    confident result (empty found_papers, or a cleanly-parsed LLM
    assessment) -- never for the degraded heuristic fallback (see Story 2.4
    Dev Notes)."""
    init_db()
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO gap_validations
           (cache_key, gap_hash, domain_hash, stage_logic_version, validation_json)
           VALUES (?,?,?,?,?)""",
        (cache_key, gap_hash, domain_hash, stage_logic_version, json.dumps(validation_json, default=str)),
    )
    conn.commit()
    conn.close()


def _compress(data: dict) -> bytes:
    return gzip.compress(json.dumps(data, default=str).encode())


def _decompress(blob: bytes) -> dict:
    return json.loads(gzip.decompress(blob).decode())


def _run_id(name: str, ts: str) -> str:
    return hashlib.md5(f"{name}{ts}".encode()).hexdigest()[:12]


def save_run(
    name: str,
    results: dict,
    comp_results: dict | None = None,
) -> str:
    """
    Persist a full pipeline run to the database.
    Returns the run_id for later retrieval.
    """
    init_db()
    ts  = datetime.now().isoformat(timespec="seconds")
    rid = _run_id(name, ts)

    context     = results.get("context", {})
    gaps        = results.get("gaps", [])
    proposals   = results.get("proposals", [])
    papers_list = results.get("papers", [])

    # Pack everything into one blob
    blob_data = {"results": results}
    if comp_results:
        blob_data["comp_results"] = comp_results
    compressed = _compress(blob_data)

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO runs
               (id, name, created_at, domain, interest, n_papers, n_gaps,
                n_proposals, has_comp, results_gz)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                rid, name, ts,
                context.get("domain", ""),
                context.get("interest", "")[:120],
                len(papers_list),
                len(gaps),
                len(proposals),
                1 if comp_results else 0,
                compressed,
            ),
        )
        for p in papers_list:
            wiki  = p.get("wiki", {})
            title = wiki.get("title") or p.get("filename", "")
            conn.execute(
                "INSERT INTO papers (run_id, filename, title, tier) VALUES (?,?,?,?)",
                (rid, p.get("filename", ""), title, p.get("tier", 1)),
            )
        conn.commit()
    finally:
        conn.close()

    return rid


def list_runs(limit: int = 20) -> list[dict]:
    """Return recent runs (metadata only, no blob)."""
    init_db()
    conn = _get_conn()
    rows = conn.execute(
        """SELECT id, name, created_at, domain, n_papers, n_gaps,
                  n_proposals, has_comp
           FROM runs ORDER BY created_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_run(run_id: str) -> dict:
    """
    Load full results for one run.
    Returns {'results': {...}, 'comp_results': {...} | None}
    """
    init_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT results_gz FROM runs WHERE id = ?", (run_id,)
    ).fetchone()
    conn.close()
    if not row:
        return {}
    return _decompress(row["results_gz"])


def delete_run(run_id: str) -> None:
    init_db()
    conn = _get_conn()
    conn.execute("DELETE FROM papers WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM runs    WHERE id     = ?", (run_id,))
    conn.commit()
    conn.close()


def get_run_papers(run_id: str) -> list[dict]:
    init_db()
    conn = _get_conn()
    rows = conn.execute(
        "SELECT filename, title, tier FROM papers WHERE run_id = ?", (run_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
