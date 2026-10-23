"""PR-22f: faults found by running graph snapshots, diffs and run deletion on real runs."""
import pytest

import utils.database as db
from pipeline import graph_persistence as gp
from tests.fixtures.make_golden_run import golden_results, seed_run
from utils import project_store, run_jobs, run_management


def _graph():
    return {
        "entities": [
            {"id": "cftr", "name": "CFTR modulators", "type": "Intervention", "importance": "high", "papers": ["a.pdf"]},
            {"id": "cbf", "name": "Ciliary beat frequency (CBF)", "type": "Outcome", "importance": "medium", "papers": ["a.pdf"]},
            {"id": "pa", "name": "Pseudomonas aeruginosa", "type": "Organism", "importance": "high", "papers": ["b.pdf"]},
        ],
        "relationships": [
            {"source": "cftr", "target": "cbf", "relation": "improves", "paper": "a.pdf", "evidence": "CBF rose",
             "relationship_id": "r1", "provenance_evidence_ids": ["ev1", "ev2"], "page": 5, "grounded": True},
            {"source": "cftr", "target": "ghost", "relation": "improves", "paper": "a.pdf", "evidence": "x"},   # unknown target
        ],
    }


# ── what a snapshot keeps ──────────────────────────────────────────────────────────────────
def test_a_snapshot_keeps_every_field_including_page_and_evidence_ids(isolated_env):
    out = gp.save_graph_snapshot("run1", "Run", _graph())
    rel = gp.load_graph_snapshot("run1")["relationships"][0]
    assert rel["page"] == 5 and rel["grounded"] is True and rel["provenance_evidence_ids"] == ["ev1", "ev2"]
    assert rel["relationship_id"] == "r1"
    assert out["relationship_count"] == 1 and out["skipped_relationships"] == 1          # the dangling one is counted, not hidden


def test_the_stored_relationship_count_is_the_stored_one(isolated_env):
    gp.save_graph_snapshot("run1", "Run", _graph())
    listed = next(s for s in gp.list_graph_snapshots() if s["run_id"] == "run1")
    assert listed["entity_count"] == 3 and listed["relationship_count"] == 1


# ── recognising the same concept ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("a,b", [
    ("Interleukin-8 (IL-8)", "Interleukin-8"),
    ("Ciliary beat frequency (CBF)", "Ciliary Beat Frequency"),
    ("Ciliary beat frequency (CBF)", "CBF"),
    ("CFTR modulator", "CFTR modulators"),
    ("Airway-on-a-chip", "airway on a chip"),
    ("Pseudomonas  aeruginosa", "pseudomonas aeruginosa"),
])
def test_the_same_concept_written_differently_shares_a_key(a, b):
    assert name_keys(a) & name_keys(b)


@pytest.mark.parametrize("a,b", [
    ("Cystic fibrosis", "Cystic fibrosis lung disease"),
    ("Ivacaftor", "Lumacaftor"),
    ("IL-6", "IL-8"),
])
def test_different_concepts_do_not_share_a_key(a, b):
    assert not (name_keys(a) & name_keys(b))


from pipeline.graph_persistence import name_keys  # noqa: E402  (kept next to its tests)


def _save(run_id, entities, relationships):
    gp.save_graph_snapshot(run_id, run_id, {"entities": entities, "relationships": relationships})


def _e(i, name):
    return {"id": i, "name": name, "type": "T", "importance": "high", "papers": []}


def test_the_diff_matches_renamed_entities_and_lists_them(isolated_env):
    _save("A", [_e("1", "Interleukin-8 (IL-8)"), _e("2", "FEV1"), _e("3", "Gene therapy")], [])
    _save("B", [_e("x", "Interleukin-8"), _e("y", "Forced expiratory volume in 1 s"), _e("z", "gene therapy")], [])
    d = gp.diff_graph_snapshots("A", "B")
    assert sorted(d["entities_common"]) == ["Gene therapy", "Interleukin-8 (IL-8)"]
    assert d["entities_renamed"] == [("Interleukin-8 (IL-8)", "Interleukin-8")]
    assert d["entities_only_in_a"] == ["FEV1"] and d["entities_only_in_b"] == ["Forced expiratory volume in 1 s"]


def test_a_name_shared_by_two_entities_in_one_graph_is_not_used_to_match(isolated_env):
    _save("A", [_e("1", "Cell culture"), _e("2", "Cell cultures")], [])
    _save("B", [_e("x", "cell culture")], [])
    d = gp.diff_graph_snapshots("A", "B")
    assert d["entities_common"] == [] and len(d["entities_only_in_a"]) == 2          # ambiguous: left alone, not guessed


def test_the_same_relationship_between_differently_spelled_entities_is_common(isolated_env):
    rel = lambda s, t, r="improves": {"source": s, "target": t, "relation": r}
    _save("A", [_e("m", "CFTR modulators"), _e("c", "Ciliary beat frequency (CBF)")], [rel("m", "c")])
    _save("B", [_e("m2", "CFTR modulator"), _e("c2", "Ciliary Beat Frequency")], [rel("m2", "c2")])
    d = gp.diff_graph_snapshots("A", "B")
    assert len(d["relationships_common"]) == 1 and not d["relationships_only_in_a"] and not d["relationships_only_in_b"]


def test_a_different_relation_or_direction_is_a_difference(isolated_env):
    rel = lambda s, t, r: {"source": s, "target": t, "relation": r}
    ents = [_e("m", "CFTR modulators"), _e("c", "Ciliary beat frequency")]
    _save("A", ents, [rel("m", "c", "improves")])
    _save("B", ents, [rel("m", "c", "reduces"), rel("c", "m", "improves")])
    d = gp.diff_graph_snapshots("A", "B")
    assert d["relationships_common"] == [] and len(d["relationships_only_in_a"]) == 1 and len(d["relationships_only_in_b"]) == 2


def test_the_diff_keeps_the_shape_the_screen_reads(isolated_env):
    _save("A", [_e("1", "X thing")], [])
    _save("B", [_e("1", "X thing")], [])
    d = gp.diff_graph_snapshots("A", "B")
    for key in ("run_id_a", "run_id_b", "entities_only_in_a", "entities_only_in_b", "entities_common",
                "relationships_only_in_a", "relationships_only_in_b", "relationships_common"):
        assert key in d


def test_an_old_snapshot_without_the_new_fields_still_diffs(isolated_env):
    db.init_db()
    conn = db._get_conn()
    conn.execute("INSERT INTO graph_snapshots (run_id,name,saved_at,entity_count,relationship_count,version,graph_json) "
                 "VALUES ('old','old','2026-01-01T00:00:00Z',1,0,1,?)",
                 ('{"entities": [{"id": "a", "name": "Gene therapy", "type": "T", "importance": "", "papers": []}], "relationships": []}',))
    conn.commit()
    conn.close()
    _save("new", [_e("g", "gene therapy")], [])
    assert gp.diff_graph_snapshots("old", "new")["entities_common"] == ["Gene therapy"]


# ── deleting a run deletes everything the database holds for it ───────────────────────────
def _fill_everything_for(run_id, project_id):
    gp.save_graph_snapshot(run_id, "r", _graph())
    db.record_run_manifest(run_id, project_id, pipeline_version="x")
    db.record_artifact("art-" + run_id, "report", "1", project_id, "hash-" + run_id, run_id=run_id)
    job = run_jobs.create_job(project_id, "job")
    conn = db._get_conn()
    conn.execute("UPDATE run_jobs SET run_id = ? WHERE id = ?", (run_id, job))
    conn.commit()
    conn.close()


def _has(conn, table, col):
    return col in [c[1] for c in conn.execute(f'PRAGMA table_info("{table}")')]


def _rows_for(run_id):
    """Every table with a run_id column, and how many rows it holds for this run."""
    conn = db._get_conn()
    try:
        out = {}
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            if _has(conn, table, "run_id"):
                out[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE run_id = ?', (run_id,)).fetchone()[0]
        out["runs"] = conn.execute("SELECT COUNT(*) FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
        return out
    finally:
        conn.close()


def test_deleting_a_run_leaves_no_row_for_it_in_any_table(isolated_env):
    keep, gone = seed_run(golden_results(), name="keep"), seed_run(golden_results(), name="gone")
    for rid in (keep, gone):
        _fill_everything_for(rid, db.DEFAULT_PROJECT_ID)
    before = _rows_for(gone)
    assert before["graph_snapshots"] == 1 and before["run_manifests"] == 1 and before["research_artifacts"] == 1
    db.delete_run(gone)
    after = _rows_for(gone)
    assert all(n == 0 for n in after.values()), after
    assert _rows_for(keep)["graph_snapshots"] == 1 and _rows_for(keep)["run_manifests"] == 1       # others untouched


def test_the_screens_delete_also_clears_the_graph_snapshot_manifest_and_artifacts(isolated_env):
    project = project_store.create_project("P", "d", "healthcare", "")
    rid = seed_run(golden_results(), name="x", project_id=project["id"])
    _fill_everything_for(rid, project["id"])
    run_management.delete_run(project["id"], rid) if hasattr(run_management, "delete_run") else db.delete_run(rid)
    assert all(n == 0 for n in _rows_for(rid).values())


def test_deleting_a_project_clears_what_is_keyed_by_the_project_as_well(isolated_env):
    project = project_store.create_project("P", "d", "healthcare", "")
    rid = seed_run(golden_results(), name="x", project_id=project["id"])
    _fill_everything_for(rid, project["id"])
    db.delete_project_rows(project["id"])
    assert all(n == 0 for n in _rows_for(rid).values())
    conn = db._get_conn()
    try:
        for table in ("research_artifacts", "run_manifests", "run_jobs"):
            assert conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE project_id = ?', (project["id"],)).fetchone()[0] == 0
    finally:
        conn.close()
