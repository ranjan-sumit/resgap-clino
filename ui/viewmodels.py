"""Display data for the screens, computed from a saved run (pure functions: no Streamlit).

Moved out of app.py so the numbers and labels shown can be unit-tested and the
same view-model can feed a different front end later.
"""
from __future__ import annotations

import html


def run_header(run_meta: dict | None, fallback_name: str = "") -> dict:
    """What the 'Showing saved run' strip displays. `run_meta` is a list_runs() row."""
    run_meta = run_meta or {}
    name = html.escape(run_meta.get("name", "") or fallback_name or "Saved run")
    when = (run_meta.get("created_at", "") or "")[:16].replace("T", " ")
    stats = (f" · {run_meta['n_papers']} papers · {run_meta['n_gaps']} gaps" if run_meta else "")
    return {"name": name, "when": when, "stats": stats}


def overview(res: dict) -> list[tuple]:
    """The five summary numbers on top of a run, as (value, label)."""
    graph = res.get("graph", {}) or {}
    stats = graph.get("stats", {}) or {}
    return [
        (len(res.get("papers", [])), "Papers Analysed"),
        (stats.get("entity_count", 0), "Graph Entities"),
        (stats.get("community_count", 0), "Communities"),
        (len(res.get("gaps", [])), "Gaps Found"),
        (len(res.get("proposals", [])), "Proposals"),
    ]


def trace_rows(trace: list[dict] | None) -> list[dict]:
    """Numbered stage rows for the Pipeline Trace tab."""
    return [{"n": i, "status": e.get("status", "✅"), "stage": e["stage"],
             "inputs": e["inputs"], "outputs": e["outputs"]}
            for i, e in enumerate(trace or [], 1)]


def stage_status(trace: list[dict] | None) -> str:
    """One word for the whole run: 'failed' if any row is ❌, 'degraded' if any ⚠️, else 'ok'."""
    statuses = {(e.get("status") or "✅") for e in (trace or [])}
    if "❌" in statuses:
        return "failed"
    if "⚠️" in statuses:
        return "degraded"
    return "ok"
