"""
Run-to-run Compare Engine (Clinova Phase 4, Epic 4.4's motivating slice,
FR-28). Diffs two already-saved runs using nothing but data already in
Postgres (utils.database.load_run()/get_run_manifest(), Epic 4.1/4.2) --
no new LLM calls, no ArcadeDB round-trip, since both runs' full graph is
already in their saved `results` blob.

Reuses the identity conventions already established elsewhere in this
codebase rather than inventing new ones: normalized-name entity/
relationship matching from pipeline/graph_persistence.py's
diff_graph_snapshots(), normalized-title gap/proposal matching from
pipeline/repeatability_score.py.

Motivating case (2026-08-23): the model selector feature (utils/
model_providers.py) means two runs of the same corpus can now genuinely
differ by nothing but which LLM produced the output -- this is
deliberately surfaced at both the manifest level (model_bundle_version,
pipeline_version, quality-gate results, duration) and the content level
(what actually changed), so a model swap's real effect is visible, not
just assumed.
"""
import re


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _diff_papers(papers_a: list, papers_b: list) -> dict:
    names_a = {p.get("filename", "") for p in papers_a if p.get("filename")}
    names_b = {p.get("filename", "") for p in papers_b if p.get("filename")}
    return {
        "added": sorted(names_b - names_a),
        "removed": sorted(names_a - names_b),
        "common_count": len(names_a & names_b),
    }


def _diff_graph(graph_a: dict, graph_b: dict) -> dict:
    """Same normalized-name matching as
    pipeline/graph_persistence.py's diff_graph_snapshots() -- applied
    directly to two in-memory graph dicts instead of two ArcadeDB
    snapshots, since both are already fully present in each run's saved
    results."""
    entities_a = graph_a.get("entities", []) or []
    entities_b = graph_b.get("entities", []) or []
    names_a = {_normalize(e.get("name", "")): e for e in entities_a if e.get("name")}
    names_b = {_normalize(e.get("name", "")): e for e in entities_b if e.get("name")}

    only_in_a = set(names_a) - set(names_b)
    only_in_b = set(names_b) - set(names_a)
    common = set(names_a) & set(names_b)

    id_to_name_a = {e.get("id"): e.get("name", "") for e in entities_a}
    id_to_name_b = {e.get("id"): e.get("name", "") for e in entities_b}

    def _rel_sigs(rels, id_to_name):
        sigs = set()
        for r in (rels or []):
            src = id_to_name.get(r.get("source", ""))
            tgt = id_to_name.get(r.get("target", ""))
            if src and tgt:
                sigs.add((_normalize(src), _normalize(tgt), r.get("relation", "")))
        return sigs

    rel_sigs_a = _rel_sigs(graph_a.get("relationships", []), id_to_name_a)
    rel_sigs_b = _rel_sigs(graph_b.get("relationships", []), id_to_name_b)

    return {
        "entities_added": sorted(names_b[n]["name"] for n in only_in_b),
        "entities_removed": sorted(names_a[n]["name"] for n in only_in_a),
        "entities_common_count": len(common),
        "relationships_added": sorted(rel_sigs_b - rel_sigs_a),
        "relationships_removed": sorted(rel_sigs_a - rel_sigs_b),
        "relationships_common_count": len(rel_sigs_a & rel_sigs_b),
    }


def _diff_gaps(gaps_a: list, gaps_b: list) -> dict:
    """Same normalized-title matching as
    pipeline/repeatability_score.py's _matched_pairs()."""
    by_title_a = {_normalize(g.get("title", "")): g for g in gaps_a if g.get("title")}
    by_title_b = {_normalize(g.get("title", "")): g for g in gaps_b if g.get("title")}

    added = set(by_title_b) - set(by_title_a)
    removed = set(by_title_a) - set(by_title_b)
    common = set(by_title_a) & set(by_title_b)

    confidence_changes = []
    for key in sorted(common):
        conf_a = by_title_a[key].get("confidence")
        conf_b = by_title_b[key].get("confidence")
        if conf_a != conf_b:
            confidence_changes.append({
                "title": by_title_b[key].get("title", key),
                "confidence_a": conf_a, "confidence_b": conf_b,
            })

    return {
        "added": sorted(by_title_b[k].get("title", k) for k in added),
        "removed": sorted(by_title_a[k].get("title", k) for k in removed),
        "common_count": len(common),
        "confidence_changes": confidence_changes,
    }


def _diff_proposals(proposals_a: list, proposals_b: list) -> dict:
    titles_a = {_normalize(p.get("title", "")) for p in proposals_a if p.get("title")}
    titles_b = {_normalize(p.get("title", "")) for p in proposals_b if p.get("title")}
    return {
        "added_count": len(titles_b - titles_a),
        "removed_count": len(titles_a - titles_b),
        "common_count": len(titles_a & titles_b),
    }


def compare_runs(run_id_a: str, run_id_b: str) -> dict:
    """FR-28's exact named diff fields: new/removed papers, new evidence,
    changed graph relationships, new/closed gaps, confidence changes,
    proposal changes -- plus a manifest-level diff (model, pipeline
    version, quality-gate results, duration) that directly surfaces
    whether a model/config change is what caused the difference. Reads
    only already-saved data, zero new LLM calls. Raises ValueError if
    either run_id doesn't resolve to a saved run -- never silently
    compares a real run against an empty placeholder."""
    from utils.database import load_run, get_run_manifest

    loaded_a = load_run(run_id_a)
    loaded_b = load_run(run_id_b)
    if not loaded_a or not loaded_b:
        missing = run_id_a if not loaded_a else run_id_b
        raise ValueError(f"Run '{missing}' was not found -- cannot compare.")

    results_a = loaded_a.get("results", {}) or {}
    results_b = loaded_b.get("results", {}) or {}

    manifest_a = get_run_manifest(run_id_a) or {}
    manifest_b = get_run_manifest(run_id_b) or {}

    evidence_a = results_a.get("evidence_objects", {}) or {}
    evidence_b = results_b.get("evidence_objects", {}) or {}
    evidence_count_a = sum(len(v) for v in evidence_a.values())
    evidence_count_b = sum(len(v) for v in evidence_b.values())

    return {
        "run_id_a": run_id_a, "run_id_b": run_id_b,
        "papers": _diff_papers(results_a.get("papers", []), results_b.get("papers", [])),
        "evidence": {
            "count_a": evidence_count_a, "count_b": evidence_count_b,
            "delta": evidence_count_b - evidence_count_a,
        },
        "graph": _diff_graph(results_a.get("graph", {}) or {}, results_b.get("graph", {}) or {}),
        "gaps": _diff_gaps(results_a.get("gaps", []), results_b.get("gaps", [])),
        "proposals": _diff_proposals(results_a.get("proposals", []), results_b.get("proposals", [])),
        "manifest": {
            "model_bundle_version_a": manifest_a.get("model_bundle_version"),
            "model_bundle_version_b": manifest_b.get("model_bundle_version"),
            "pipeline_version_a": manifest_a.get("pipeline_version"),
            "pipeline_version_b": manifest_b.get("pipeline_version"),
            "quality_gate_results_a": manifest_a.get("quality_gate_results"),
            "quality_gate_results_b": manifest_b.get("quality_gate_results"),
            "run_duration_seconds_a": manifest_a.get("run_duration_seconds"),
            "run_duration_seconds_b": manifest_b.get("run_duration_seconds"),
        },
    }
