"""
SQLite Run History + Research Artifact Registry (Clinova Phase 4, Epic
4.1/4.2). A single local file -- no server, no Docker, 0 MB of extra
dependencies (sqlite3 ships with Python), which is what lets the app run on
Streamlit Cloud. This replaced a Postgres backend (psycopg) on 2026-10-09;
every public function below keeps its exact signature (save_run, load_run,
list_runs, delete_run, get_run_papers, the six get_cached_X/save_cached_X
pairs, compute_cache_key, the artifact/manifest functions), so no call site
elsewhere changed.

The file lives at $RESGAP_DB_PATH, default data/run_history.db. On Streamlit
Cloud the local disk is ephemeral (wiped on reboot/redeploy), so history
there lasts only until the app restarts.

Migrations live in migrations/*.sql, applied idempotently and in order by
_apply_migrations() -- forward-only: nothing here drops or rewrites a prior
migration in place. They are SQLite dialect; JSON is stored as TEXT and
encoded/decoded here (_json_dumps / _decode_json_cols), where Postgres used
native JSONB.
"""
import json
import os
import sqlite3
import threading
import uuid
import hashlib
from datetime import datetime, date
from pathlib import Path

from utils.run_storage import restore_sections, split_for_storage, to_utc_iso, utc_now_iso

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "run_history.db"

# Test isolation hook: tests/pg_test_utils.py monkeypatches this (the name is
# historical -- it used to be a Postgres schema) to the path of a throwaway
# SQLite file via patch.object(db, "_SCHEMA", ...), giving each test class its
# own fully-isolated database. None (the default) means "use the real DB
# path," so production behavior is unaffected by this hook existing.
_SCHEMA: str | None = None

# Paths whose migrations have already run in this process -- every public
# function calls init_db(), so without this each call would re-check them.
_INITIALIZED: set[str] = set()
_INIT_LOCK = threading.Lock()

# JSON columns, per table, stored as TEXT and decoded back on read.
_JSON_COLS = {
    "research_artifacts": ("metadata",),
    "run_manifests": ("parser_versions", "search_providers", "output_artifacts",
                      "evaluation_metrics", "warnings", "quality_gate_results", "token_usage"),
}

# SQLite caps bound variables per statement (999 on older builds).
_IN_CHUNK = 500


def _db_path() -> str:
    return _SCHEMA or os.environ.get("RESGAP_DB_PATH") or str(DEFAULT_DB_PATH)


def _get_conn() -> sqlite3.Connection:
    path = _db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")   # off by default in SQLite
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.DatabaseError:
        pass  # some network/virtual filesystems refuse WAL -- default journal is fine
    return conn


def _json_dumps(value) -> str:
    return json.dumps(value, default=str)


def _decode_json_cols(row, table: str) -> dict:
    d = dict(row)
    for col in _JSON_COLS.get(table, ()):
        if isinstance(d.get(col), str):
            try:
                d[col] = json.loads(d[col])
            except json.JSONDecodeError:
                pass
    return d


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Idempotent, forward-only, in filename order. Safe to call every time
    init_db() runs -- an already-applied migration is a no-op."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)
    conn.commit()

    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.name
        if version in applied:
            continue
        try:
            conn.executescript(path.read_text(encoding="utf-8"))
        except sqlite3.OperationalError:
            # Another process may have applied this migration between our
            # SELECT and here (ALTER TABLE ADD COLUMN is not idempotent). If it
            # is now recorded, that is fine; otherwise it is a real failure.
            if conn.in_transaction:
                conn.rollback()
            done = conn.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (version,)).fetchone()
            if not done:
                raise
            continue
        # OR IGNORE: another process (a second Streamlit session) may have
        # recorded the same migration between our SELECT and here. Every
        # migration is CREATE ... IF NOT EXISTS, so re-running it is harmless.
        conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)", (version,))
        conn.commit()


_STORAGE_MIGRATION = "py-0007-slim-runs-and-utc"


def _migrate_run_storage(conn: sqlite3.Connection, db_path: str) -> None:
    """One-time, idempotent: runs saved before this change get their duplicate paper text
    dropped, section text moved to run_blobs, and naive local timestamps converted to UTC.
    The database file is copied first (<name>.bak-<time>) whenever anything is changed.
    A run that cannot be converted is left exactly as it was."""
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (_STORAGE_MIGRATION,)).fetchone():
        return
    rows = conn.execute("SELECT id, created_at, results_json FROM runs").fetchall()
    todo = []
    for r in rows:
        stale_ts = bool(r["created_at"]) and not str(r["created_at"]).endswith("Z")
        try:
            blob = json.loads(r["results_json"])
        except (TypeError, json.JSONDecodeError):
            blob = None
        results = blob.get("results") if isinstance(blob, dict) else None
        heavy = isinstance(results, dict) and (
            any(isinstance(c, dict) and ("full_text" in c or "text_segments" in c or "sections" in c)
                for c in results.get("corpus") or [])
            or any(isinstance(p, dict) and p.get("sections") for p in results.get("papers") or []))
        if stale_ts or heavy:
            todo.append((r["id"], r["created_at"], blob, stale_ts, heavy))
    if todo and Path(db_path).exists():
        import shutil
        shutil.copy2(db_path, f"{db_path}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    for run_id, created_at, blob, stale_ts, heavy in todo:
        try:
            new_ts = to_utc_iso(created_at) if stale_ts else created_at
            if heavy:
                lean, side = split_for_storage(blob["results"])
                blob = {**blob, "results": lean}
                for name_, data_ in side.items():
                    conn.execute("INSERT OR REPLACE INTO run_blobs (run_id, name, data) VALUES (?,?,?)",
                                 (run_id, name_, _json_dumps(data_)))
                conn.execute("UPDATE runs SET results_json = ? WHERE id = ?", (_json_dumps(blob), run_id))
            if stale_ts:
                conn.execute("UPDATE runs SET created_at = ? WHERE id = ?", (new_ts, run_id))
            conn.commit()
        except Exception:
            conn.rollback()
    conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)", (_STORAGE_MIGRATION,))
    conn.commit()


def init_db() -> None:
    """Create/upgrade tables if needed. Safe to call multiple times and from
    several threads at once (the pipeline's worker threads all reach this on a
    fresh database): the lock makes the first caller do the work while the
    others wait, then skip it."""
    path = _db_path()
    if path in _INITIALIZED and Path(path).exists():
        return
    with _INIT_LOCK:
        if path in _INITIALIZED and Path(path).exists():
            return
        conn = _get_conn()
        try:
            _apply_migrations(conn)
            _migrate_run_storage(conn, path)
        finally:
            conn.close()
        _INITIALIZED.add(path)


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
    cur.execute("SELECT wiki_json FROM wiki_pages WHERE cache_key = ?", (cache_key,))
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
           VALUES (?,?,?,?,?)
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
    cur.execute("SELECT params_json FROM parameters WHERE cache_key = ?", (cache_key,))
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
           VALUES (?,?,?,?)
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
    cur.execute("SELECT extraction_json FROM docling_extractions WHERE cache_key = ?", (cache_key,))
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
           VALUES (?,?,?,?)
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
    cur.execute("SELECT evidence_json FROM evidence_objects WHERE cache_key = ?", (cache_key,))
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
           VALUES (?,?,?,?)
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
    cur.execute('SELECT enriched_json FROM "references" WHERE cache_key = ?', (cache_key,))
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
           VALUES (?,?,?,?)
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
    cur.execute("SELECT validation_json FROM gap_validations WHERE cache_key = ?", (cache_key,))
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
           VALUES (?,?,?,?,?)
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


DEFAULT_PROJECT_ID = "default"


def save_run(
    name: str,
    results: dict,
    comp_results: dict | None = None,
    project_id: str | None = None,
) -> str:
    """
    Persist a full pipeline run to the database, under `project_id` (the
    always-present default project when omitted).
    Returns the run_id for later retrieval.
    """
    init_db()
    ts  = utc_now_iso()          # stored in UTC; the UI converts to the viewer's time zone
    # Two runs with the same name started in the same second (API double
    # submit, two tabs) must never share a run_id -- the uuid makes the
    # hash input unique while the 12-hex-char output format is unchanged.
    rid = _run_id(name, f"{ts}:{uuid.uuid4().hex}")

    context     = results.get("context", {})
    gaps        = results.get("gaps", [])
    proposals   = results.get("proposals", [])
    papers_list = results.get("papers", [])

    # Pack everything into one JSON text value (see migrations/0001). Duplicate paper text is
    # dropped and the section text goes to run_blobs (see utils/run_storage.py).
    lean_results, side_blobs = split_for_storage(results)
    blob_data = {"results": lean_results}
    if comp_results:
        blob_data["comp_results"] = comp_results

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO runs
               (id, name, created_at, domain, interest, n_papers, n_gaps,
                n_proposals, has_comp, results_json, project_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT (id) DO UPDATE SET
                   name = EXCLUDED.name, created_at = EXCLUDED.created_at,
                   domain = EXCLUDED.domain, interest = EXCLUDED.interest,
                   n_papers = EXCLUDED.n_papers, n_gaps = EXCLUDED.n_gaps,
                   n_proposals = EXCLUDED.n_proposals, has_comp = EXCLUDED.has_comp,
                   results_json = EXCLUDED.results_json, project_id = EXCLUDED.project_id""",
            (
                rid, name, ts,
                context.get("domain", ""),
                context.get("interest", "")[:120],
                len(papers_list),
                len(gaps),
                len(proposals),
                1 if comp_results else 0,
                _json_dumps(blob_data),
                project_id or DEFAULT_PROJECT_ID,
            ),
        )
        # Idempotent re-save (same run_id): clear any prior papers rows
        # before re-inserting.
        cur.execute("DELETE FROM papers WHERE run_id = ?", (rid,))
        cur.execute("DELETE FROM run_blobs WHERE run_id = ?", (rid,))
        for name_, data_ in side_blobs.items():
            cur.execute("INSERT INTO run_blobs (run_id, name, data) VALUES (?,?,?)", (rid, name_, _json_dumps(data_)))
        for p in papers_list:
            wiki  = p.get("wiki", {})
            title = wiki.get("title") or p.get("filename", "")
            cur.execute(
                "INSERT INTO papers (run_id, filename, title, tier) VALUES (?,?,?,?)",
                (rid, p.get("filename", ""), title, p.get("tier", 1)),
            )
        conn.commit()
    finally:
        conn.close()

    return rid


def attach_comp_results(run_id: str, comp_results: dict) -> bool:
    """Stores Computational Lab results on the run they were computed from, so
    one analysis is one run (rather than a second, near-identical run).
    Replaces earlier Lab results on that run. Returns False if the run does
    not exist."""
    init_db()
    conn = _get_conn()
    try:
        row = conn.execute("SELECT results_json FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return False
        blob = json.loads(row["results_json"])
        blob["comp_results"] = comp_results
        conn.execute("UPDATE runs SET results_json = ?, has_comp = 1 WHERE id = ?",
                     (_json_dumps(blob), run_id))
        conn.commit()
        return True
    finally:
        conn.close()


def update_run_proposals(run_id: str, proposals: list) -> bool:
    """Replaces a saved run's proposals (and its proposal count), for a run
    whose proposal step failed and was repeated on its own. False if the run
    does not exist."""
    init_db()
    conn = _get_conn()
    try:
        row = conn.execute("SELECT results_json FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return False
        blob = json.loads(row["results_json"])
        blob.setdefault("results", {})["proposals"] = proposals
        conn.execute("UPDATE runs SET results_json = ?, n_proposals = ? WHERE id = ?",
                     (_json_dumps(blob), len(proposals), run_id))
        conn.commit()
        return True
    finally:
        conn.close()


def list_runs(limit: int = 20, project_id: str | None = None) -> list[dict]:
    """Return recent runs (metadata only, no blob), newest first. With
    `project_id`, only that project's runs."""
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    where, params = ("WHERE project_id = ?", [project_id]) if project_id else ("", [])
    cur.execute(
        f"""SELECT id, name, created_at, domain, n_papers, n_gaps,
                   n_proposals, has_comp, project_id
            FROM runs {where} ORDER BY created_at DESC, rowid DESC LIMIT ?""",
        (*params, limit),
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
                  n_proposals, has_comp, project_id
           FROM runs WHERE id = ?""",
        (run_id,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def load_run(run_id: str, sections: bool = True) -> dict:
    """
    Load full results for one run.
    Returns {'results': {...}, 'comp_results': {...} | None}
    `sections=False` leaves the per-paper section text out (only the Computational Lab
    needs it; use `load_paper_sections` / `with_sections` to add it later).
    """
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT results_json FROM runs WHERE id = ?", (run_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {}
    blob = json.loads(row["results_json"])
    if sections and isinstance(blob.get("results"), dict):
        blob["results"] = restore_sections(blob["results"], load_paper_sections(run_id))
    return blob


def load_paper_sections(run_id: str) -> dict:
    """{filename: sections} stored beside the run ({} for runs saved with the text inline)."""
    init_db()
    conn = _get_conn()
    try:
        row = conn.execute("SELECT data FROM run_blobs WHERE run_id = ? AND name = 'paper_sections'",
                           (run_id,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data"]) if row else {}


def with_sections(run_id: str, results: dict) -> dict:
    """`results` (loaded without sections) with each paper's section text restored."""
    return restore_sections(results, load_paper_sections(run_id))


def load_run_gate_fields_bulk(run_ids: list[str]) -> dict[str, dict]:
    """The two `results` keys run-status derivation needs, for many runs in
    ONE query (Clinova Phase 5, Slice 15).

    Additive: load_run() is unchanged and remains what app.py and every
    full-run reader use.

    Deriving a run's status reads only results.gate_blocked /
    results.gate_block_reasons, while load_run() returns the whole results
    JSON (papers, sections, graph, evidence) -- so this extracts just those
    keys inside SQLite with json_extract, in one query for the whole list.
    """
    if not run_ids:
        return {}
    init_db()
    run_ids = list(run_ids)
    conn = _get_conn()
    rows = []
    for i in range(0, len(run_ids), _IN_CHUNK):
        chunk = run_ids[i:i + _IN_CHUNK]
        rows += conn.execute(
            "SELECT id, "
            "       json_extract(results_json, '$.results.gate_blocked')       AS gate_blocked, "
            "       json_extract(results_json, '$.results.gate_block_reasons') AS gate_block_reasons "
            f"FROM runs WHERE id IN ({','.join('?' * len(chunk))})",
            chunk,
        ).fetchall()
    conn.close()

    def _reasons(raw):
        # json_extract returns arrays/objects as JSON text.
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return []
        return raw or []

    return {
        r["id"]: {
            # json_extract returns JSON true/false as 1/0; None stays None.
            "gate_blocked": None if r["gate_blocked"] is None else bool(r["gate_blocked"]),
            "gate_block_reasons": _reasons(r["gate_block_reasons"]),
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
    run_ids = list(run_ids)
    conn = _get_conn()
    rows = []
    for i in range(0, len(run_ids), _IN_CHUNK):
        chunk = run_ids[i:i + _IN_CHUNK]
        rows += conn.execute(
            f"SELECT * FROM run_manifests WHERE run_id IN ({','.join('?' * len(chunk))})", chunk,
        ).fetchall()
    conn.close()
    return {r["run_id"]: _decode_json_cols(r, "run_manifests") for r in rows}


def delete_run(run_id: str) -> None:
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    # papers.run_id is ON DELETE CASCADE and _get_conn() turns foreign_keys
    # on, so this manual delete is defensive-but-redundant.
    cur.execute("DELETE FROM papers WHERE run_id = ?", (run_id,))
    cur.execute("DELETE FROM runs   WHERE id     = ?", (run_id,))
    conn.commit()
    conn.close()


def get_run_papers(run_id: str) -> list[dict]:
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT filename, title, tier FROM papers WHERE run_id = ?", (run_id,))
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
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT (artifact_id) DO UPDATE SET
               artifact_version = EXCLUDED.artifact_version,
               schema_version = EXCLUDED.schema_version,
               parent_artifact = EXCLUDED.parent_artifact,
               project_id = EXCLUDED.project_id, run_id = EXCLUDED.run_id,
               content_hash = EXCLUDED.content_hash, storage_uri = EXCLUDED.storage_uri,
               status = EXCLUDED.status, metadata = EXCLUDED.metadata""",
        (artifact_id, artifact_type, artifact_version, schema_version,
         parent_artifact, project_id, run_id, content_hash, storage_uri,
         status, _json_dumps(metadata) if metadata is not None else None),
    )
    conn.commit()
    conn.close()
    return artifact_id


def get_artifact(artifact_id: str) -> dict | None:
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM research_artifacts WHERE artifact_id = ?", (artifact_id,))
    row = cur.fetchone()
    conn.close()
    return _decode_json_cols(row, "research_artifacts") if row else None


def list_artifacts(artifact_type: str = None, project_id: str = None, status: str = None) -> list[dict]:
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    clauses, params = [], []
    if artifact_type:
        clauses.append("artifact_type = ?"); params.append(artifact_type)
    if project_id:
        clauses.append("project_id = ?"); params.append(project_id)
    if status:
        clauses.append("status = ?"); params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    # rowid breaks ties between rows created within the same millisecond.
    cur.execute(f"SELECT * FROM research_artifacts {where} ORDER BY created_at DESC, rowid DESC", params)
    rows = cur.fetchall()
    conn.close()
    return [_decode_json_cols(r, "research_artifacts") for r in rows]


def promote_artifact(artifact_id: str, new_status: str) -> dict:
    """Transitions an artifact's status per §2's lifecycle. Raises
    InvalidArtifactTransitionError on an illegal transition (e.g.
    EXPERIMENTAL -> CHAMPION directly) -- never silently applies it."""
    if new_status not in _ARTIFACT_STATUS_ORDER:
        raise ValueError(f"Unknown artifact status: {new_status}")
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT status FROM research_artifacts WHERE artifact_id = ?", (artifact_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"No artifact found with id {artifact_id}")
    current = row["status"]
    if new_status not in _ARTIFACT_LEGAL_TRANSITIONS.get(current, set()):
        conn.close()
        raise InvalidArtifactTransitionError(current, new_status)
    cur.execute(
        "UPDATE research_artifacts SET status = ? WHERE artifact_id = ?",
        (new_status, artifact_id),
    )
    updated = conn.execute(
        "SELECT * FROM research_artifacts WHERE artifact_id = ?", (artifact_id,),
    ).fetchone()
    conn.commit()
    conn.close()
    return _decode_json_cols(updated, "research_artifacts")


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
    json_fields = set(_JSON_COLS["run_manifests"])

    def _encode(k, v):
        if v is None:
            return None
        if k in json_fields:
            return _json_dumps(v)
        if isinstance(v, (date, datetime)):  # academic_search_date is stored as ISO text
            return v.isoformat()
        return v

    columns = ["run_id", "project_id"] + list(fields.keys())
    values = [run_id, project_id] + [_encode(k, v) for k, v in fields.items()]
    placeholders = ", ".join(["?"] * len(values))
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
    cur.execute("SELECT * FROM run_manifests WHERE run_id = ?", (run_id,))
    row = cur.fetchone()
    conn.close()
    return _decode_json_cols(row, "run_manifests") if row else None


# ── Projects, project files and feedback ────────────────────────────────────
# Schema: migrations/0005_projects.sql. Filesystem work (creating the folder,
# writing papers and artifacts) lives in utils/project_store.py; this module is
# only the database side.

FEEDBACK_TARGETS = ("gap", "proposal", "run")


def insert_project(project_id: str, name: str, description: str, folder: str,
                   domain: str = "", interest: str = "") -> dict:
    """Records a project row. The folder itself is created by project_store."""
    init_db()
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO projects (id, name, description, folder, domain, interest) VALUES (?,?,?,?,?,?)",
            (project_id, name.strip(), (description or "").strip(), folder, domain or "", (interest or "").strip()),
        )
        conn.commit()
    finally:
        conn.close()
    return get_project(project_id)


# ── Cached stage results: what is stored, and clearing it ────────────────────
# One table per cached stage (keyed by content + model + stage version). Clearing a stage
# makes the next run recompute it.
CACHE_STAGES = {
    "wiki_pages": "Paper summaries (wiki)",
    "evidence_objects": "Evidence extraction",
    "parameters": "Lab parameters",
    "docling_extractions": "Second-parser check",
    "gap_validations": "Gap literature checks",
}


def cache_stats() -> list[dict]:
    """[{table, label, rows, bytes}] for each cached stage."""
    init_db()
    conn = _get_conn()
    out = []
    try:
        for table, label in CACHE_STAGES.items():
            cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
            payload = [c for c in cols if c.endswith("_json")]
            size = " + ".join(f"COALESCE(length({c}), 0)" for c in payload) or "0"
            row = conn.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM({size}), 0) AS b FROM {table}").fetchone()
            out.append({"table": table, "label": label, "rows": row["n"], "bytes": row["b"]})
    finally:
        conn.close()
    return out


def clear_cache(table: str) -> int:
    """Deletes every cached result of one stage; returns how many rows went."""
    if table not in CACHE_STAGES:
        raise ValueError(f"Unknown cache: {table}")
    init_db()
    conn = _get_conn()
    try:
        n = conn.execute(f"DELETE FROM {table}").rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def get_project(project_id: str) -> dict | None:
    init_db()
    conn = _get_conn()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_projects(include_archived: bool = False) -> list[dict]:
    """Projects with their run and file counts, default project first, then
    newest first."""
    init_db()
    conn = _get_conn()
    rows = conn.execute(
        f"""SELECT p.*,
                   (SELECT COUNT(*) FROM runs r WHERE r.project_id = p.id)          AS run_count,
                   (SELECT COUNT(*) FROM project_files f WHERE f.project_id = p.id
                                                        AND f.kind = 'paper')       AS paper_count
            FROM projects p
            {'' if include_archived else 'WHERE p.archived = 0'}
            ORDER BY (p.id = ?) DESC, p.created_at DESC, p.rowid DESC""",
        (DEFAULT_PROJECT_ID,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_project_file(project_id: str, kind: str, filename: str, rel_path: str,
                     sha256: str, size_bytes: int) -> int:
    """Records a file stored under the project's folder and returns its id.
    Idempotent per (project, rel_path): re-saving returns the existing row's
    id, and refreshes its hash and size when the file at that path was
    rewritten (a regenerated report)."""
    init_db()
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO project_files
               (project_id, kind, filename, rel_path, sha256, size_bytes)
               VALUES (?,?,?,?,?,?)""",
            (project_id, kind, filename, rel_path, sha256, size_bytes),
        )
        conn.execute(
            "UPDATE project_files SET sha256 = ?, size_bytes = ? WHERE project_id = ? AND rel_path = ?",
            (sha256, size_bytes, project_id, rel_path),
        )
        row = conn.execute(
            "SELECT id FROM project_files WHERE project_id = ? AND rel_path = ?",
            (project_id, rel_path),
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    return row["id"]


def link_run_file(run_id: str, file_id: int) -> None:
    init_db()
    conn = _get_conn()
    try:
        conn.execute("INSERT OR IGNORE INTO run_files (run_id, file_id) VALUES (?,?)", (run_id, file_id))
        conn.commit()
    finally:
        conn.close()


def list_project_files(project_id: str, kind: str | None = None, run_id: str | None = None) -> list[dict]:
    """A project's files, optionally only one kind and/or only those a given
    run used or produced."""
    init_db()
    clauses, params = ["f.project_id = ?"], [project_id]
    if kind:
        clauses.append("f.kind = ?"); params.append(kind)
    join = ""
    if run_id:
        join = "JOIN run_files rf ON rf.file_id = f.id"
        clauses.append("rf.run_id = ?"); params.append(run_id)
    conn = _get_conn()
    rows = conn.execute(
        f"SELECT f.* FROM project_files f {join} WHERE {' AND '.join(clauses)} ORDER BY f.id",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_feedback(project_id: str, run_id: str, target_type: str, target_id: str = "",
                    *, rating: int | None = None, reason: str = "", comment: str = "",
                    target_label: str = "") -> dict | None:
    """Saves the user's feedback on a gap, proposal or run. One row per
    (run, target): calling again updates it. A call with no rating, reason or
    comment clears the feedback instead (returns None). `rating` is 1 (useful),
    -1 (not useful) or None."""
    if target_type not in FEEDBACK_TARGETS:
        raise ValueError(f"Unknown feedback target type: {target_type}")
    if rating not in (1, -1, None):
        raise ValueError("rating must be 1, -1 or None")
    target_id = target_id or ""
    reason, comment = (reason or "").strip(), (comment or "").strip()
    init_db()
    conn = _get_conn()
    try:
        if rating is None and not reason and not comment:
            conn.execute("DELETE FROM feedback WHERE run_id = ? AND target_type = ? AND target_id = ?",
                         (run_id, target_type, target_id))
            conn.commit()
            return None
        conn.execute(
            """INSERT INTO feedback
               (project_id, run_id, target_type, target_id, target_label, rating, reason, comment)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT (run_id, target_type, target_id) DO UPDATE SET
                   target_label = EXCLUDED.target_label, rating = EXCLUDED.rating,
                   reason = EXCLUDED.reason, comment = EXCLUDED.comment,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
            (project_id, run_id, target_type, target_id, target_label, rating, reason, comment),
        )
        row = conn.execute(
            "SELECT * FROM feedback WHERE run_id = ? AND target_type = ? AND target_id = ?",
            (run_id, target_type, target_id),
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    return dict(row)


def list_feedback(*, run_id: str | None = None, project_id: str | None = None,
                  target_type: str | None = None) -> list[dict]:
    """Feedback for one run and/or a whole project, newest first."""
    init_db()
    clauses, params = [], []
    for col, val in (("run_id", run_id), ("project_id", project_id), ("target_type", target_type)):
        if val:
            clauses.append(f"{col} = ?"); params.append(val)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = _get_conn()
    rows = conn.execute(f"SELECT * FROM feedback {where} ORDER BY updated_at DESC, id DESC", params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
