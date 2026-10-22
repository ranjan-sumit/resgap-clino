"""
Graph Persistence (Clinova Phase 3, Epic 3.1) -- cross-run knowledge-graph
snapshots, stored in the same SQLite file as the run history
(utils/database.py, migrations/0004_graph_snapshots.sql).

Why this exists separately from pipeline/graph_structural_gaps.py: that
module's gap detection queries the in-memory graph pipeline/graph_builder.py
already builds for ONE run -- it never needed persistence. Epic 3.1's actual,
different requirement is comparing a run's graph against a DIFFERENT, EARLIER
run's graph (has this entity appeared before? did this relationship exist
last time?) -- an in-memory single-run structure cannot answer that; it needs
a store that outlives the run.

History: this used to run on ArcadeDB (a JVM server). The graph is only ever
saved, loaded, listed and diffed -- never queried natively -- so each
snapshot is now one JSON row in SQLite: no server, no JVM, no extra
dependency. The public functions keep their names, return shapes and the
(now ignored) `config` parameter, so callers did not change.

Deliberately optional and additive: nothing else in the pipeline depends on
this module. Saving is a single upsert, so a failure mid-save can never
destroy the last good snapshot or leave a half-written one.
"""
import json
import re
from datetime import datetime, timezone

from utils import database as db

GRAPH_PERSISTENCE_VERSION = 1


def connect_ok(config: dict = None) -> tuple[bool, str]:
    """Health check -- returns (ok, message), never raises. Kept from the
    ArcadeDB era so the UI/pipeline gate (`if not ok: warn`) still works;
    the store is a local file, so it only fails if SQLite itself cannot open."""
    try:
        db.init_db()
        return True, f"Graph snapshots stored in SQLite at {db._db_path()}"
    except Exception as e:
        return False, f"Cannot open the SQLite graph store ({type(e).__name__}: {e})"


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def save_graph_snapshot(run_id: str, run_name: str, graph: dict, config: dict = None,
                         quality: dict = None) -> dict:
    """Persists one run's graph (the same dict shape
    pipeline/graph_builder.py's build_knowledge_graph() already returns)
    under `run_id`. Idempotent per run_id -- re-saving the same run_id
    replaces its prior snapshot rather than duplicating it.

    `quality` is pipeline/graph_quality.py's score_graph_quality() output
    (optional -- callers that haven't computed it yet still save fine;
    build_status/quality_score are just stored as None). Persisting it here
    is what makes "Compare Graph Version" possible instead of only comparing
    entity/relationship counts.

    Relationships may reference an entity by id or by (normalized) name --
    the same dual-lookup convention pipeline/graph_builder.py uses. They are
    stored resolved to entity ids; one referencing an entity not in this
    graph is skipped, not guessed.

    Returns a small summary dict {run_id, entity_count, relationship_count}
    (relationship_count = relationships actually stored)."""
    db.init_db()
    entities = graph.get("entities", [])
    relationships = graph.get("relationships", [])
    quality = quality or {}

    stored_entities = []
    id_by_key = {}
    for e in entities:
        eid = e.get("id") or e.get("name", "")
        stored_entities.append({
            "id": eid, "name": e.get("name", ""), "type": e.get("type", ""),
            "importance": e.get("importance", ""), "papers": e.get("papers", []),
        })
        id_by_key[eid] = eid
        id_by_key.setdefault(_normalize_name(e.get("name", "")), eid)

    stored_relationships = []
    for r in relationships:
        src = id_by_key.get(r.get("source", "")) or id_by_key.get(_normalize_name(str(r.get("source", ""))))
        tgt = id_by_key.get(r.get("target", "")) or id_by_key.get(_normalize_name(str(r.get("target", ""))))
        if not src or not tgt:
            continue  # relationship references an entity not in this graph -- skip, don't guess
        stored_relationships.append({
            "source": src, "target": tgt, "relation": r.get("relation", ""),
            "paper": r.get("paper", ""), "evidence": r.get("evidence", ""),
        })

    conn = db._get_conn()
    try:
        conn.execute(
            """INSERT INTO graph_snapshots
               (run_id, name, saved_at, entity_count, relationship_count, version,
                build_status, quality_score, graph_json)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT (run_id) DO UPDATE SET
                   name = EXCLUDED.name, saved_at = EXCLUDED.saved_at,
                   entity_count = EXCLUDED.entity_count,
                   relationship_count = EXCLUDED.relationship_count,
                   version = EXCLUDED.version, build_status = EXCLUDED.build_status,
                   quality_score = EXCLUDED.quality_score, graph_json = EXCLUDED.graph_json""",
            (run_id, run_name, datetime.now(timezone.utc).isoformat(),
             len(entities), len(relationships), GRAPH_PERSISTENCE_VERSION,
             quality.get("build_status"), quality.get("quality_score"),
             json.dumps({"entities": stored_entities, "relationships": stored_relationships},
                        default=str)),
        )
        conn.commit()
    finally:
        conn.close()

    return {"run_id": run_id, "entity_count": len(entities),
            "relationship_count": len(stored_relationships)}


def load_graph_snapshot(run_id: str, config: dict = None) -> dict:
    """Reconstructs a saved run's graph, in the same {entities,
    relationships} shape build_knowledge_graph() produces, so it can be
    fed into pipeline/graph_structural_gaps.py or compared like any other
    graph dict. Returns {"entities": [], "relationships": []} (not an
    error) if run_id was never saved -- an honest "nothing here", the
    same convention this codebase uses elsewhere for a genuine absence."""
    db.init_db()
    conn = db._get_conn()
    try:
        row = conn.execute("SELECT graph_json FROM graph_snapshots WHERE run_id = ?",
                           (run_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return {"entities": [], "relationships": []}
    try:
        graph = json.loads(row["graph_json"])
    except (json.JSONDecodeError, TypeError):
        return {"entities": [], "relationships": []}
    return {"entities": graph.get("entities", []), "relationships": graph.get("relationships", [])}


def list_graph_snapshots(config: dict = None) -> list[dict]:
    """Every persisted run, newest first."""
    db.init_db()
    conn = db._get_conn()
    try:
        rows = conn.execute(
            """SELECT run_id, name, saved_at, entity_count, relationship_count,
                      build_status, quality_score
               FROM graph_snapshots ORDER BY saved_at DESC"""
        ).fetchall()
    finally:
        conn.close()
    # build_status/quality_score are None for any run saved without scoring --
    # honest "not scored", not a fabricated 0/CLEAN.
    return [dict(r) for r in rows]


def diff_graph_snapshots(run_id_a: str, run_id_b: str, config: dict = None) -> dict:
    """The actual cross-run payoff Epic 3.1 exists for: which entities
    and relationships are new in B vs. A, which disappeared, and which
    are common to both -- matched by normalized entity name (the same
    identity key used throughout this codebase's dedup logic elsewhere),
    since raw entity ids are never comparable across separate saves."""
    graph_a = load_graph_snapshot(run_id_a, config)
    graph_b = load_graph_snapshot(run_id_b, config)

    names_a = {_normalize_name(e["name"]): e for e in graph_a["entities"] if e.get("name")}
    names_b = {_normalize_name(e["name"]): e for e in graph_b["entities"] if e.get("name")}

    only_in_a = sorted(set(names_a) - set(names_b))
    only_in_b = sorted(set(names_b) - set(names_a))
    common = sorted(set(names_a) & set(names_b))

    def _rel_signature(rels, entities_by_norm_id):
        sigs = set()
        for r in rels:
            src = entities_by_norm_id.get(r.get("source", ""))
            tgt = entities_by_norm_id.get(r.get("target", ""))
            if src and tgt:
                sigs.add((_normalize_name(src), _normalize_name(tgt), r.get("relation", "")))
        return sigs

    id_to_name_a = {e.get("id"): e.get("name", "") for e in graph_a["entities"]}
    id_to_name_b = {e.get("id"): e.get("name", "") for e in graph_b["entities"]}
    rel_sigs_a = _rel_signature(graph_a["relationships"], id_to_name_a)
    rel_sigs_b = _rel_signature(graph_b["relationships"], id_to_name_b)

    return {
        "run_id_a": run_id_a, "run_id_b": run_id_b,
        "entities_only_in_a": [names_a[n]["name"] for n in only_in_a],
        "entities_only_in_b": [names_b[n]["name"] for n in only_in_b],
        "entities_common": [names_a[n]["name"] for n in common],
        "relationships_only_in_a": sorted(rel_sigs_a - rel_sigs_b),
        "relationships_only_in_b": sorted(rel_sigs_b - rel_sigs_a),
        "relationships_common": sorted(rel_sigs_a & rel_sigs_b),
    }
