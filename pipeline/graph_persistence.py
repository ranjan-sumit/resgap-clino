"""
Graph Persistence (Clinova Phase 3, Epic 3.1) -- cross-run graph
persistence via ArcadeDB (open source, Apache 2.0, https://arcadedb.com),
running locally with no Docker and no admin rights needed (see
amendments/2026-08-20-environment-constraints.md's 2026-08-22 update).

Why this exists separately from pipeline/graph_structural_gaps.py:
that module's gap detection queries the in-memory graph
pipeline/graph_builder.py already builds for ONE run -- it never needed
persistence. Epic 3.1's actual, different requirement is comparing a
run's graph against a DIFFERENT, EARLIER run's graph (has this entity
appeared before? did this relationship exist last time? how has the
corpus's knowledge graph grown across repeated analyses?) -- an
in-memory single-run structure structurally cannot answer that; it needs
a real store queried across runs.

Deliberately optional and additive: nothing else in the pipeline depends
on this module. ArcadeDB must be running locally
(JAVA_HOME=<jdk21+>; JAVA_OPTS=-Darcadedb.server.rootPassword=<pw>;
bin\\server.bat, from the extracted ArcadeDB distribution) before these
functions are called -- connect_ok() checks that cleanly so a missing
server surfaces as a clear message, not a stack trace deep in a pipeline
stage. Every write uses ArcadeDB's parameterized-query support (`params`
in the command body) -- entity names and relationship text come from
LLM output and must never be interpolated directly into SQL/Cypher.
"""
import os
import re
from datetime import datetime, timezone

import requests

GRAPH_PERSISTENCE_VERSION = 1

_TIMEOUT = 15
_HEALTH_TIMEOUT = 5


def _config() -> dict:
    return {
        "url": os.environ.get("ARCADEDB_URL", "http://localhost:2480").rstrip("/"),
        "user": os.environ.get("ARCADEDB_USER", "root"),
        "password": os.environ.get("ARCADEDB_PASSWORD", ""),
        "database": os.environ.get("ARCADEDB_DATABASE", "clinova_graphs"),
    }


def _auth(config: dict) -> tuple:
    return (config["user"], config["password"])


def _command(config: dict, sql: str, params: dict = None, language: str = "sql") -> list:
    """Runs one command against the configured database, parameterized.
    Raises requests.HTTPError on failure -- callers that need a clean
    Failure instead (e.g. app.py's UI) should catch this, matching this
    codebase's existing convention of not silently swallowing an error
    that the caller needs to see."""
    body = {"language": language, "command": sql}
    if params:
        body["params"] = params
    resp = requests.post(
        f"{config['url']}/api/v1/command/{config['database']}",
        json=body, auth=_auth(config), timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


def connect_ok(config: dict = None) -> tuple[bool, str]:
    """Health check -- returns (ok, message), never raises. Callers use
    this to show a clear "ArcadeDB not running at <url>" message instead
    of an unhandled connection-error stack trace."""
    config = config or _config()
    try:
        r = requests.get(f"{config['url']}/api/v1/ready",
                          auth=_auth(config), timeout=_HEALTH_TIMEOUT)
        if r.status_code in (200, 204):
            return True, f"Connected to ArcadeDB at {config['url']}"
        return False, f"ArcadeDB at {config['url']} returned unexpected status {r.status_code}"
    except requests.exceptions.RequestException as e:
        return False, (f"Cannot reach ArcadeDB at {config['url']} -- is the server running? "
                        f"({type(e).__name__}: {e})")


def ensure_schema(config: dict = None) -> None:
    """Idempotent -- safe to call every time before a write. Creates the
    database if missing, then the vertex/edge types and the run_id index
    that every query below relies on."""
    config = config or _config()
    try:
        requests.post(f"{config['url']}/api/v1/server",
                       json={"command": f"create database {config['database']}"},
                       auth=_auth(config), timeout=_TIMEOUT)
    except requests.exceptions.RequestException:
        pass  # already exists, or server unreachable -- the _command() calls below will raise clearly if so

    _command(config, "CREATE VERTEX TYPE GraphEntity IF NOT EXISTS")
    _command(config, "CREATE EDGE TYPE GraphRelation IF NOT EXISTS")
    _command(config, "CREATE VERTEX TYPE GraphRun IF NOT EXISTS")
    _command(config, "CREATE PROPERTY GraphEntity.run_id IF NOT EXISTS STRING")
    _command(config, "CREATE PROPERTY GraphEntity.name_normalized IF NOT EXISTS STRING")
    _command(config, "CREATE PROPERTY GraphRun.run_id IF NOT EXISTS STRING")
    _command(config, "CREATE INDEX IF NOT EXISTS ON GraphEntity (run_id) NOTUNIQUE")
    _command(config, "CREATE INDEX IF NOT EXISTS ON GraphRun (run_id) UNIQUE")


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def save_graph_snapshot(run_id: str, run_name: str, graph: dict, config: dict = None,
                         quality: dict = None) -> dict:
    """Persists one run's graph (the same dict shape
    pipeline/graph_builder.py's build_knowledge_graph() already returns)
    under `run_id`. Idempotent per run_id -- re-saving the same run_id
    replaces its prior snapshot rather than duplicating it, so a re-run
    of the same analysis doesn't accumulate stale copies.

    `quality` is pipeline/graph_quality.py's score_graph_quality() output
    (optional -- callers that haven't computed it yet still save fine;
    build_status/quality_score are just stored as None). Persisting it
    here is what makes "Compare Graph Version" (ADR-002's own stated
    reason a persisted store is needed for FR-7) actually possible instead
    of only comparing entity/relationship counts.

    Returns a small summary dict {run_id, entity_count, relationship_count}."""
    config = config or _config()
    ensure_schema(config)

    entities = graph.get("entities", [])
    relationships = graph.get("relationships", [])
    quality = quality or {}

    # Replace any prior snapshot for this run_id (edges first -- ArcadeDB
    # won't delete a vertex that still has edges attached).
    _command(config, "DELETE VERTEX FROM GraphEntity WHERE run_id = :run_id", {"run_id": run_id})
    _command(config, "DELETE VERTEX FROM GraphRun WHERE run_id = :run_id", {"run_id": run_id})

    _command(config, """
        INSERT INTO GraphRun SET run_id = :run_id, name = :name,
            saved_at = :saved_at, entity_count = :entity_count,
            relationship_count = :relationship_count,
            graph_persistence_version = :version,
            build_status = :build_status, quality_score = :quality_score
    """, {
        "run_id": run_id, "name": run_name,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "entity_count": len(entities), "relationship_count": len(relationships),
        "version": GRAPH_PERSISTENCE_VERSION,
        "build_status": quality.get("build_status"),
        "quality_score": quality.get("quality_score"),
    })

    # entity_id -> ArcadeDB @rid, needed to wire up edges below.
    rid_by_entity_id = {}
    for e in entities:
        eid = e.get("id") or e.get("name", "")
        result = _command(config, """
            INSERT INTO GraphEntity SET run_id = :run_id, entity_id = :entity_id,
                name = :name, name_normalized = :name_normalized, type = :type,
                importance = :importance, papers = :papers
        """, {
            "run_id": run_id, "entity_id": eid, "name": e.get("name", ""),
            "name_normalized": _normalize_name(e.get("name", "")),
            "type": e.get("type", ""), "importance": e.get("importance", ""),
            "papers": e.get("papers", []),
        })
        if result:
            rid_by_entity_id[eid] = result[0]["@rid"]
            # Names are also used to resolve relationships (LLM output
            # sometimes references entities by name, not id -- same
            # dual-lookup convention pipeline/graph_builder.py already uses).
            rid_by_entity_id.setdefault(_normalize_name(e.get("name", "")), result[0]["@rid"])

    edge_count = 0
    for r in relationships:
        src_rid = rid_by_entity_id.get(r.get("source", "")) or rid_by_entity_id.get(_normalize_name(str(r.get("source", ""))))
        tgt_rid = rid_by_entity_id.get(r.get("target", "")) or rid_by_entity_id.get(_normalize_name(str(r.get("target", ""))))
        if not src_rid or not tgt_rid:
            continue  # relationship references an entity not in this graph -- skip, don't guess
        _command(config, f"""
            CREATE EDGE GraphRelation FROM {src_rid} TO {tgt_rid}
            SET run_id = :run_id, relation = :relation, paper = :paper, evidence = :evidence
        """, {
            "run_id": run_id, "relation": r.get("relation", ""),
            "paper": r.get("paper", ""), "evidence": r.get("evidence", ""),
        })
        edge_count += 1

    return {"run_id": run_id, "entity_count": len(entities), "relationship_count": edge_count}


def load_graph_snapshot(run_id: str, config: dict = None) -> dict:
    """Reconstructs a saved run's graph, in the same {entities,
    relationships} shape build_knowledge_graph() produces, so it can be
    fed into pipeline/graph_structural_gaps.py or compared like any other
    graph dict. Returns {"entities": [], "relationships": []} (not an
    error) if run_id was never saved -- an honest "nothing here", the
    same convention this codebase uses elsewhere for a genuine absence."""
    config = config or _config()
    entities_raw = _command(config, "SELECT FROM GraphEntity WHERE run_id = :run_id",
                             {"run_id": run_id})
    entities = [{
        "id": e.get("entity_id", ""), "name": e.get("name", ""),
        "type": e.get("type", ""), "importance": e.get("importance", ""),
        "papers": e.get("papers", []),
    } for e in entities_raw]

    # Real-data finding (2026-08-22): ArcadeDB SQL needs the @-prefixed
    # @out/@in edge-link properties to dereference the connected vertex's
    # field (`out.entity_id`/`in.entity_id`, without the @, silently
    # returns null instead of erroring -- confirmed live, not assumed).
    relationships_raw = _command(config, """
        SELECT @out.entity_id AS source, @in.entity_id AS target,
               relation, paper, evidence
        FROM GraphRelation WHERE run_id = :run_id
    """, {"run_id": run_id})
    relationships = [{
        "source": r.get("source", ""), "target": r.get("target", ""),
        "relation": r.get("relation", ""), "paper": r.get("paper", ""),
        "evidence": r.get("evidence", ""),
    } for r in relationships_raw]

    return {"entities": entities, "relationships": relationships}


def list_graph_snapshots(config: dict = None) -> list[dict]:
    """Every persisted run, newest first."""
    config = config or _config()
    rows = _command(config, "SELECT FROM GraphRun ORDER BY saved_at DESC")
    return [{
        "run_id": r.get("run_id", ""), "name": r.get("name", ""),
        "saved_at": r.get("saved_at", ""),
        "entity_count": r.get("entity_count", 0),
        "relationship_count": r.get("relationship_count", 0),
        # None for any run saved before this field existed -- honest
        # "not scored", not a fabricated 0/CLEAN.
        "build_status": r.get("build_status"),
        "quality_score": r.get("quality_score"),
    } for r in rows]


def diff_graph_snapshots(run_id_a: str, run_id_b: str, config: dict = None) -> dict:
    """The actual cross-run payoff Epic 3.1 exists for: which entities
    and relationships are new in B vs. A, which disappeared, and which
    are common to both -- matched by normalized entity name (the same
    identity key used throughout this codebase's dedup logic elsewhere),
    since raw entity_id/@rid values are never comparable across separate
    saves."""
    config = config or _config()
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
