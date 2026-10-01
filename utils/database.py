"""
Postgres Run History + Research Artifact Registry (Clinova Phase 4, Epic
4.1/4.2). Replaces the pre-Phase-4 SQLite backend entirely -- every public
function below keeps its exact pre-migration signature (save_run, load_run,
list_runs, delete_run, get_run_papers, the six get_cached_X/save_cached_X
pairs, compute_cache_key), so no call site anywhere else in the pipeline
needed to change (confirmed: utils/database.py was the only module touching
SQLite directly).

Requires a local PostgreSQL server running -- no Docker, no admin rights
(portable EnterpriseDB ZIP binaries, same no-installer pattern as
ArcadeDB/JDK; see amendments/2026-08-20-environment-constraints.md and
POSTGRES_* in .env). Migrations live in migrations/*.sql, applied
idempotently and in order by _apply_migrations() -- forward-only, per
ADR-005/FR-21: nothing here drops or rewrites a prior migration in place.

One real, deliberate change from the SQLite schema, not just a port: `runs.
results_gz BLOB` (manually gzip-compressed JSON) became `runs.results_json
JSONB` (native). Postgres TOAST-compresses large JSONB internally, so the
manual gzip step was no longer doing useful work -- see migrations/
0001_initial_schema.sql's own comment.
"""
import json
import os
import uuid
import hashlib
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

# Test isolation hook (Epic 4.1): tests/pg_test_utils.py monkeypatches this
# to a throwaway schema name via patch.object(db, "_SCHEMA", ...), giving
# each test class its own fully-isolated set of tables -- the same
# isolation the pre-migration tests got from a fresh tmpdir SQLite file
# per test class, just via a Postgres schema instead of a separate file.
# None (the default) means "use Postgres's normal 'public' schema," i.e.
# real production behavior is completely unaffected by this hook existing.
_SCHEMA: str | None = None


def _config() -> dict:
    return {
        "host_and_port": os.environ.get("POSTGRES_URL", "postgresql://localhost:5433")
                          .removeprefix("postgresql://"),
        "user": os.environ.get("POSTGRES_USER", "clinova_app"),
        "password": os.environ.get("POSTGRES_PASSWORD", ""),
        "database": os.environ.get("POSTGRES_DATABASE", "clinova"),
    }


def _get_conn() -> psycopg.Connection:
    c = _config()
    kwargs = {"row_factory": dict_row}
    if _SCHEMA:
        kwargs["options"] = f"-c search_path={_SCHEMA}"
    return psycopg.connect(
        f"postgresql://{c['user']}:{c['password']}@{c['host_and_port']}/{c['database']}",
        **kwargs,
    )


def _apply_migrations(conn: psycopg.Connection) -> None:
    """Idempotent, forward-only, in filename order. Safe to call every time
    init_db() runs -- an already-applied migration is a no-op, matching the
    same discipline as pipeline/graph_persistence.py's ensure_schema()."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.commit()

    cur.execute("SELECT version FROM schema_migrations")
    applied = {row["version"] for row in cur.fetchall()}

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.name
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        cur.execute(sql)
        cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        conn.commit()


def init_db() -> None:
    """Create/upgrade tables if needed. Safe to call multiple times."""
    conn = _get_conn()
    try:
        _apply_migrations(conn)
    finally:
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

    Unchanged by the Phase 4 migration -- pure hashing logic, no database
    dependency. domain_hash is only meaningful for domain-conditioned
    stages: pass the exact subset of domain_config keys that actually
    affect that stage's prompt (e.g. ["wiki_focus", "wiki_entity_examples"]
    for wiki compilation) so an unrelated domain_config change doesn't
    cause a spurious cache miss. Pass an empty relevant_domain_keys for a
    domain-invariant stage -- domain_hash will be the literal string "none"
    regardless of domain_config.

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
    cur = conn.cursor()
    cur.execute("SELECT wiki_json FROM wiki_pages WHERE cache_key = %s", (cache_key,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row["wiki_json"])
    except (json.JSONDecodeError, TypeError):
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
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO wiki_pages
           (cache_key, content_hash, domain_hash, stage_logic_version, wiki_json)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (cache_key) DO UPDATE SET
               content_hash = EXCLUDED.content_hash,
               domain_hash = EXCLUDED.domain_hash,
               stage_logic_version = EXCLUDED.stage_logic_version,
               wiki_json = EXCLUDED.wiki_json""",
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
    cur = conn.cursor()
    cur.execute("SELECT params_json FROM parameters WHERE cache_key = %s", (cache_key,))
    row = cur.fetchone()
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
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO parameters (cache_key, content_hash, stage_logic_version, params_json)
           VALUES (%s,%s,%s,%s)
           ON CONFLICT (cache_key) DO UPDATE SET
               content_hash = EXCLUDED.content_hash,
               stage_logic_version = EXCLUDED.stage_logic_version,
               params_json = EXCLUDED.params_json""",
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
    cur = conn.cursor()
    cur.execute("SELECT extraction_json FROM docling_extractions WHERE cache_key = %s", (cache_key,))
    row = cur.fetchone()
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
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO docling_extractions (cache_key, content_hash, stage_logic_version, extraction_json)
           VALUES (%s,%s,%s,%s)
           ON CONFLICT (cache_key) DO UPDATE SET
               content_hash = EXCLUDED.content_hash,
               stage_logic_version = EXCLUDED.stage_logic_version,
               extraction_json = EXCLUDED.extraction_json""",
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
    cur = conn.cursor()
    cur.execute("SELECT evidence_json FROM evidence_objects WHERE cache_key = %s", (cache_key,))
    row = cur.fetchone()
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
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO evidence_objects (cache_key, content_hash, stage_logic_version, evidence_json)
           VALUES (%s,%s,%s,%s)
           ON CONFLICT (cache_key) DO UPDATE SET
               content_hash = EXCLUDED.content_hash,
               stage_logic_version = EXCLUDED.stage_logic_version,
               evidence_json = EXCLUDED.evidence_json""",
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
    cur = conn.cursor()
    cur.execute('SELECT enriched_json FROM "references" WHERE cache_key = %s', (cache_key,))
    row = cur.fetchone()
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
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO "references" (cache_key, doi_or_title_hash, stage_logic_version, enriched_json)
           VALUES (%s,%s,%s,%s)
           ON CONFLICT (cache_key) DO UPDATE SET
               doi_or_title_hash = EXCLUDED.doi_or_title_hash,
               stage_logic_version = EXCLUDED.stage_logic_version,
               enriched_json = EXCLUDED.enriched_json""",
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
    cur = conn.cursor()
    cur.execute("SELECT validation_json FROM gap_validations WHERE cache_key = %s", (cache_key,))
    row = cur.fetchone()
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
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO gap_validations
           (cache_key, gap_hash, domain_hash, stage_logic_version, validation_json)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (cache_key) DO UPDATE SET
               gap_hash = EXCLUDED.gap_hash,
               domain_hash = EXCLUDED.domain_hash,
               stage_logic_version = EXCLUDED.stage_logic_version,
               validation_json = EXCLUDED.validation_json""",
        (cache_key, gap_hash, domain_hash, stage_logic_version, json.dumps(validation_json, default=str)),
    )
    conn.commit()
    conn.close()


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
    # Two runs with the same name started in the same second (API double
    # submit, two tabs) must never share a run_id -- the uuid makes the
    # hash input unique while the 12-hex-char output format is unchanged.
    rid = _run_id(name, f"{ts}:{uuid.uuid4().hex}")

    context     = results.get("context", {})
    gaps        = results.get("gaps", [])
    proposals   = results.get("proposals", [])
    papers_list = results.get("papers", [])

    # Pack everything into one JSONB value -- native, no manual gzip (see
    # migrations/0001_initial_schema.sql's comment for why).
    blob_data = {"results": results}
    if comp_results:
        blob_data["comp_results"] = comp_results

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO runs
               (id, name, created_at, domain, interest, n_papers, n_gaps,
                n_proposals, has_comp, results_json)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                   name = EXCLUDED.name, created_at = EXCLUDED.created_at,
                   domain = EXCLUDED.domain, interest = EXCLUDED.interest,
                   n_papers = EXCLUDED.n_papers, n_gaps = EXCLUDED.n_gaps,
                   n_proposals = EXCLUDED.n_proposals, has_comp = EXCLUDED.has_comp,
                   results_json = EXCLUDED.results_json""",
            (
                rid, name, ts,
                context.get("domain", ""),
                context.get("interest", "")[:120],
                len(papers_list),
                len(gaps),
                len(proposals),
                1 if comp_results else 0,
                Jsonb(json.loads(json.dumps(blob_data, default=str))),
            ),
        )
        # Idempotent re-save (same run_id): clear any prior papers rows
        # before re-inserting, same intent as SQLite's INSERT OR REPLACE.
        cur.execute("DELETE FROM papers WHERE run_id = %s", (rid,))
        for p in papers_list:
            wiki  = p.get("wiki", {})
            title = wiki.get("title") or p.get("filename", "")
            cur.execute(
                "INSERT INTO papers (run_id, filename, title, tier) VALUES (%s,%s,%s,%s)",
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
    cur = conn.cursor()
    cur.execute(
        """SELECT id, name, created_at, domain, n_papers, n_gaps,
                  n_proposals, has_comp
           FROM runs ORDER BY created_at DESC LIMIT %s""",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_run_row(run_id: str) -> dict | None:
    """Clinova Phase 5, Epic 5.1: the single-run counterpart to
    list_runs() -- load_run() only returns the results_json blob, not the
    row's own name/created_at/domain columns, and apps/api's Run Detail
    endpoint needs both. Additive; no existing caller's signature changed."""
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT id, name, created_at, domain, n_papers, n_gaps,
                  n_proposals, has_comp
           FROM runs WHERE id = %s""",
        (run_id,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def load_run(run_id: str) -> dict:
    """
    Load full results for one run.
    Returns {'results': {...}, 'comp_results': {...} | None}
    """
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT results_json FROM runs WHERE id = %s", (run_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {}
    return row["results_json"]


def load_run_gate_fields_bulk(run_ids: list[str]) -> dict[str, dict]:
    """The two `results` keys run-status derivation needs, for many runs in
    ONE query (Clinova Phase 5, Slice 15).

    Additive: load_run() is unchanged and remains what app.py and every
    full-run reader use.

    Two separate savings, and the second is the one that mattered. Deriving a
    run's status reads only results.gate_blocked / results.gate_block_reasons,
    while load_run() ships the whole results JSONB (papers, sections, graph,
    evidence) to get them -- so this extracts just those keys server-side.
    But measurement showed payload was NOT the bottleneck: _get_conn() opens
    and closes a fresh connection per call at ~0.75s each, so a 5-run list
    spent ~7.5s in connection setup alone. Hence bulk: one connection and one
    query for the whole list instead of one per run.
    """
    if not run_ids:
        return {}
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, "
        "       results_json->'results'->'gate_blocked'       AS gate_blocked, "
        "       results_json->'results'->'gate_block_reasons' AS gate_block_reasons "
        "FROM runs WHERE id = ANY(%s)",
        (list(run_ids),),
    )
    rows = cur.fetchall()
    conn.close()
    return {
        r["id"]: {
            "gate_blocked": r["gate_blocked"],
            "gate_block_reasons": r["gate_block_reasons"] or [],
        }
        for r in rows
    }


def get_run_manifests_bulk(run_ids: list[str]) -> dict[str, dict]:
    """Manifests for many runs in one query. Same reasoning as
    load_run_gate_fields_bulk: get_run_manifest() costs a connection per call.
    Runs with no manifest are simply absent from the result, which callers
    must treat as None (a missing manifest is a real, meaningful state -- see
    derive_run_status's NO_MANIFEST branch)."""
    if not run_ids:
        return {}
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM run_manifests WHERE run_id = ANY(%s)", (list(run_ids),))
    rows = cur.fetchall()
    conn.close()
    return {r["run_id"]: dict(r) for r in rows}


def delete_run(run_id: str) -> None:
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    # Postgres enforces the papers.run_id FK (ON DELETE CASCADE) for real,
    # unlike SQLite -- this manual delete is now defensive-but-redundant,
    # kept for clarity/symmetry with the pre-migration behavior rather than
    # relying solely on the cascade.
    cur.execute("DELETE FROM papers WHERE run_id = %s", (run_id,))
    cur.execute("DELETE FROM runs   WHERE id     = %s", (run_id,))
    conn.commit()
    conn.close()


def get_run_papers(run_id: str) -> list[dict]:
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT filename, title, tier FROM papers WHERE run_id = %s", (run_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Research Artifact Registry (Clinova Phase 4, Epic 4.1, FR-22) ───────────
# Exact schema: migrations/0002_artifact_registry.sql /
# 06-versioning-lineage-architecture.md §2. New this pass -- no pre-Phase-4
# equivalent existed.

_ARTIFACT_STATUS_ORDER = ["EXPERIMENTAL", "CANDIDATE", "CHAMPION", "ARCHIVED"]
# Legal transitions per §2's lifecycle diagram: EXPERIMENTAL -> CANDIDATE ->
# CHAMPION, and either CANDIDATE or CHAMPION -> ARCHIVED. No transition
# skips a step forward (EXPERIMENTAL cannot jump straight to CHAMPION), and
# nothing leaves ARCHIVED (terminal).
_ARTIFACT_LEGAL_TRANSITIONS = {
    "EXPERIMENTAL": {"CANDIDATE"},
    "CANDIDATE": {"CHAMPION", "ARCHIVED"},
    "CHAMPION": {"ARCHIVED"},
    "ARCHIVED": set(),
}


class InvalidArtifactTransitionError(Exception):
    """Raised by promote_artifact() on an illegal status transition -- the
    lifecycle in 06-versioning-lineage-architecture.md §2 is a hard
    constraint, not just documentation (mirrors pipeline/graph_quality.py's
    "a degraded score must actually matter" discipline: an invalid
    transition must be rejected, not silently applied)."""

    def __init__(self, from_status: str, to_status: str):
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Cannot transition artifact from {from_status} to {to_status}")


def record_artifact(
    artifact_id: str, artifact_type: str, artifact_version: str, project_id: str,
    content_hash: str, schema_version: str = None, parent_artifact: str = None,
    run_id: str = None, storage_uri: str = None, status: str = "EXPERIMENTAL",
    metadata: dict = None,
) -> str:
    """Records one ResearchArtifact row. Idempotent per artifact_id (a
    content-addressed SHA-256 id naturally re-saving identical content is a
    no-op update, not a duplicate). Returns artifact_id."""
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO research_artifacts
           (artifact_id, artifact_type, artifact_version, schema_version,
            parent_artifact, project_id, run_id, content_hash, storage_uri,
            status, metadata)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (artifact_id) DO UPDATE SET
               artifact_version = EXCLUDED.artifact_version,
               schema_version = EXCLUDED.schema_version,
               parent_artifact = EXCLUDED.parent_artifact,
               project_id = EXCLUDED.project_id, run_id = EXCLUDED.run_id,
               content_hash = EXCLUDED.content_hash, storage_uri = EXCLUDED.storage_uri,
               status = EXCLUDED.status, metadata = EXCLUDED.metadata""",
        (artifact_id, artifact_type, artifact_version, schema_version,
         parent_artifact, project_id, run_id, content_hash, storage_uri,
         status, Jsonb(metadata) if metadata is not None else None),
    )
    conn.commit()
    conn.close()
    return artifact_id


def get_artifact(artifact_id: str) -> dict | None:
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM research_artifacts WHERE artifact_id = %s", (artifact_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def list_artifacts(artifact_type: str = None, project_id: str = None, status: str = None) -> list[dict]:
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    clauses, params = [], []
    if artifact_type:
        clauses.append("artifact_type = %s"); params.append(artifact_type)
    if project_id:
        clauses.append("project_id = %s"); params.append(project_id)
    if status:
        clauses.append("status = %s"); params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur.execute(f"SELECT * FROM research_artifacts {where} ORDER BY created_at DESC", params)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def promote_artifact(artifact_id: str, new_status: str) -> dict:
    """Transitions an artifact's status per §2's lifecycle. Raises
    InvalidArtifactTransitionError on an illegal transition (e.g.
    EXPERIMENTAL -> CHAMPION directly) -- never silently applies it."""
    if new_status not in _ARTIFACT_STATUS_ORDER:
        raise ValueError(f"Unknown artifact status: {new_status}")
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT status FROM research_artifacts WHERE artifact_id = %s", (artifact_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"No artifact found with id {artifact_id}")
    current = row["status"]
    if new_status not in _ARTIFACT_LEGAL_TRANSITIONS.get(current, set()):
        conn.close()
        raise InvalidArtifactTransitionError(current, new_status)
    cur.execute(
        "UPDATE research_artifacts SET status = %s WHERE artifact_id = %s RETURNING *",
        (new_status, artifact_id),
    )
    updated = cur.fetchone()
    conn.commit()
    conn.close()
    return dict(updated)


# ── Run Manifest (Clinova Phase 4, Epic 4.2, FR-23) ─────────────────────────
# Exact field list: migrations/0003_run_manifest.sql /
# 06-versioning-lineage-architecture.md §3. New this pass.

def record_run_manifest(run_id: str, project_id: str, **fields) -> str:
    """Records one immutable RunManifest row. `fields` accepts any subset
    of the schema's optional columns (input_corpus_version, pipeline_version,
    git_commit, parser_versions, reference_resolver_version,
    embedding_model_version, reranker_version, graph_builder_version,
    graph_version, prompt_bundle_version, model_bundle_version,
    search_strategy_version, academic_search_date, search_providers,
    output_artifacts, evaluation_metrics, warnings, quality_gate_results,
    run_duration_seconds, token_usage) -- callers pass only what they
    actually have; anything omitted is stored as NULL, never fabricated
    (see module docstring on token_usage specifically)."""
    init_db()
    jsonb_fields = {"parser_versions", "search_providers", "output_artifacts",
                     "evaluation_metrics", "warnings", "quality_gate_results", "token_usage"}
    columns = ["run_id", "project_id"] + list(fields.keys())
    values = [run_id, project_id] + [
        Jsonb(v) if k in jsonb_fields and v is not None else v
        for k, v in fields.items()
    ]
    placeholders = ", ".join(["%s"] * len(values))
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""INSERT INTO run_manifests ({', '.join(columns)})
            VALUES ({placeholders})
            ON CONFLICT (run_id) DO UPDATE SET
                {', '.join(f'{c} = EXCLUDED.{c}' for c in columns if c != 'run_id')}""",
        values,
    )
    conn.commit()
    conn.close()
    return run_id


def get_run_manifest(run_id: str) -> dict | None:
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM run_manifests WHERE run_id = %s", (run_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None
