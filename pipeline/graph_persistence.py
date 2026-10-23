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
import unicodedata
from datetime import datetime, timezone

from utils import database as db

GRAPH_PERSISTENCE_VERSION = 2     # 2: a snapshot keeps every field of an entity and a relationship (page, evidence ids, ...)


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
        stored_entities.append({**e, "id": eid, "name": e.get("name", ""), "type": e.get("type", ""),
                                "importance": e.get("importance", ""), "papers": e.get("papers", [])})
        id_by_key[eid] = eid
        id_by_key.setdefault(_normalize_name(e.get("name", "")), eid)

    stored_relationships = []
    for r in relationships:
        src = id_by_key.get(r.get("source", "")) or id_by_key.get(_normalize_name(str(r.get("source", ""))))
        tgt = id_by_key.get(r.get("target", "")) or id_by_key.get(_normalize_name(str(r.get("target", ""))))
        if not src or not tgt:
            continue  # relationship references an entity not in this graph -- skip, don't guess
        stored_relationships.append({**r, "source": src, "target": tgt, "relation": r.get("relation", ""),
                                     "paper": r.get("paper", ""), "evidence": r.get("evidence", "")})

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
             len(entities), len(stored_relationships), GRAPH_PERSISTENCE_VERSION,
             quality.get("build_status"), quality.get("quality_score"),
             json.dumps({"entities": stored_entities, "relationships": stored_relationships},
                        default=str)),
        )
        conn.commit()
    finally:
        conn.close()

    return {"run_id": run_id, "entity_count": len(entities),
            "relationship_count": len(stored_relationships),
            "skipped_relationships": len(relationships) - len(stored_relationships)}


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


_PAREN = re.compile(r"\(([^()]*)\)")


def _fold(text: str) -> str:
    """Lower case, accents and punctuation removed, simple plurals folded: "Interleukin-8" and "interleukin 8" agree."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in text.split())


def name_keys(name: str) -> set[str]:
    """The ways one entity name can be recognised: the name itself, the name without a bracketed part, and the bracketed
    part when it is an abbreviation. "Ciliary beat frequency (CBF)" is recognised as "Ciliary Beat Frequency" and as "CBF"."""
    name = str(name or "")
    keys = {_fold(name)}
    outside = _fold(_PAREN.sub(" ", name))
    if outside:
        keys.add(outside)
    for inner in _PAREN.findall(name):
        folded = _fold(inner)
        if folded and (inner.strip().isupper() or len(folded) <= 8):
            keys.add(folded)
    return {k for k in keys if k}


def _match_entities(entities_a: list, entities_b: list) -> tuple[dict, dict]:
    """(index in A -> index in B, index in B -> index in A) for entities that are the same concept. An entity is claimed by
    at most one partner; a key that two entities of one graph share is not used to match (it would be ambiguous)."""
    def index(entities):
        by_key: dict = {}
        for i, e in enumerate(entities):
            for k in name_keys(e.get("name", "")):
                by_key.setdefault(k, []).append(i)
        return by_key
    by_a, by_b = index(entities_a), index(entities_b)
    a_to_b, b_to_a = {}, {}
    for pass_exact in (True, False):                    # exact folded names first, then the looser keys
        for i, e in enumerate(entities_a):
            if i in a_to_b or not e.get("name"):
                continue
            keys = [_fold(e["name"])] if pass_exact else sorted(name_keys(e["name"]))
            for k in keys:
                cands = [j for j in by_b.get(k, []) if j not in b_to_a]
                if len(cands) == 1 and len(by_a.get(k, [])) == 1:
                    a_to_b[i], b_to_a[cands[0]] = cands[0], i
                    break
    return a_to_b, b_to_a


def diff_graph_snapshots(run_id_a: str, run_id_b: str, config: dict = None) -> dict:
    """The actual cross-run payoff Epic 3.1 exists for: which entities and relationships are new in B vs. A, which
    disappeared, and which are common to both. Entities are matched by name after folding case, punctuation, plurals and
    bracketed abbreviations; a pair matched under different spellings is listed in `entities_renamed`. Relationships are
    compared between matched entities, so the same relationship between differently-spelled entities is common."""
    graph_a = load_graph_snapshot(run_id_a, config)
    graph_b = load_graph_snapshot(run_id_b, config)
    ents_a = [e for e in graph_a["entities"] if e.get("name")]
    ents_b = [e for e in graph_b["entities"] if e.get("name")]
    a_to_b, b_to_a = _match_entities(ents_a, ents_b)

    common = [ents_a[i]["name"] for i in a_to_b]
    renamed = [(ents_a[i]["name"], ents_b[j]["name"]) for i, j in a_to_b.items()
               if _normalize_name(ents_a[i]["name"]) != _normalize_name(ents_b[j]["name"])]
    only_a = [e["name"] for i, e in enumerate(ents_a) if i not in a_to_b]
    only_b = [e["name"] for j, e in enumerate(ents_b) if j not in b_to_a]

    # a canonical label for each entity: its partner's index if matched, so both sides use the same node name
    label_a = {e.get("id"): (f"#{a_to_b[i]}" if i in a_to_b else f"A:{_fold(e['name'])}") for i, e in enumerate(ents_a)}
    label_b = {e.get("id"): (f"#{j}" if j in b_to_a else f"B:{_fold(e['name'])}") for j, e in enumerate(ents_b)}
    name_a = {e.get("id"): e["name"] for e in ents_a}
    name_b = {e.get("id"): e["name"] for e in ents_b}

    def sigs(rels, labels, names):
        out = {}
        for r in rels:
            s_, t_ = labels.get(r.get("source")), labels.get(r.get("target"))
            if s_ and t_:
                out.setdefault((s_, t_, r.get("relation", "")), (_normalize_name(names[r["source"]]), _normalize_name(names[r["target"]]), r.get("relation", "")))
        return out
    sa, sb = sigs(graph_a["relationships"], label_a, name_a), sigs(graph_b["relationships"], label_b, name_b)

    return {
        "run_id_a": run_id_a, "run_id_b": run_id_b,
        "entities_only_in_a": sorted(only_a, key=str.lower),
        "entities_only_in_b": sorted(only_b, key=str.lower),
        "entities_common": sorted(common, key=str.lower),
        "entities_renamed": sorted(renamed),
        "relationships_only_in_a": sorted(v for k, v in sa.items() if k not in sb),
        "relationships_only_in_b": sorted(v for k, v in sb.items() if k not in sa),
        "relationships_common": sorted(v for k, v in sa.items() if k in sb),
    }
