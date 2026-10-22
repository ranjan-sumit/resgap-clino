"""Display data for the screens, computed from a saved run (pure functions: no Streamlit).

Moved out of app.py so the numbers and labels shown can be unit-tested and the
same view-model can feed a different front end later.
"""
from __future__ import annotations

import html


def run_header(run_meta: dict | None, fallback_name: str = "", res: dict | None = None,
               manifest: dict | None = None) -> dict:
    """What the run header displays. `run_meta` is a list_runs() row; `res` and
    `manifest` (both optional) add the status chips. Missing pieces are left out."""
    run_meta = run_meta or {}
    name = html.escape(run_meta.get("name", "") or fallback_name or "Saved run")
    when = (run_meta.get("created_at", "") or "")[:16].replace("T", " ")
    stats = (f" · {run_meta['n_papers']} papers · {run_meta['n_gaps']} gaps" if run_meta else "")
    chips: list[str] = []
    if res is not None:
        status = stage_status(res.get("pipeline_trace"))
        chips.append({"ok": "Completed", "degraded": "Completed with warnings", "failed": "Had failures"}[status]
                     if res.get("pipeline_trace") else "No stage trace")
        if res.get("gate_blocked"):
            chips.append("Quality gate failed")
        main = ((res.get("models") or {}).get("roles") or {}).get("extraction") or {}
        if isinstance(main, dict) and main.get("model"):
            chips.append(html.escape(str(main["model"])))
    secs = (manifest or {}).get("run_duration_seconds")
    if isinstance(secs, (int, float)) and secs > 0:
        chips.append(f"{int(secs // 60)} min {int(secs % 60)} s")
    return {"name": name, "when": when, "stats": stats, "chips": chips}


def keys_line(found: list[str], semantic_scholar: bool) -> str:
    """The one-line key status under the API keys panel."""
    llm = ("Keys found: " + " · ".join(found)) if found else \
        "No API keys found. Add one above, or set it in the environment."
    s2 = ("Semantic Scholar: key set." if semantic_scholar
          else "Semantic Scholar: no key (slower free tier).")
    return f"{llm}  \n{s2}"


def off_note(res: dict) -> str | None:
    """None when the reference stage ran; otherwise the single note that replaces the 'Off' cards."""
    if res.get("ref_diagnostics"):
        return None
    return ("Cited references were not fetched for this run, so the corpus is the uploaded papers only. "
            "Turn on “Include cited references” in the sidebar under Analysis to widen it.")


def saved_trace(res: dict, session_trace: list | None = None) -> list[dict]:
    """The stage trace to show: this session's live one, else the one stored with the run."""
    return list(session_trace or res.get("pipeline_trace") or [])


def trace_summary(res: dict, manifest: dict | None = None) -> dict:
    """Models, fallbacks, tokens and agent diagnostics stored with a run, for the Trace tab.
    Every field is optional: a run saved before they existed simply omits them."""
    out: dict = {}
    models = res.get("models")
    if isinstance(models, dict):
        roles = models.get("roles") if isinstance(models.get("roles"), dict) else models
        out["models"] = {k: (v.get("model") if isinstance(v, dict) else str(v))
                         for k, v in roles.items() if isinstance(v, (dict, str)) and k != "fallback"}
    fb = res.get("model_fallbacks") or []
    if fb:
        out["fallbacks"] = [f"{f.get('stage')}: {f.get('from')} → {f.get('to')}" for f in fb[:20]]
        out["fallback_count"] = len(fb)
    tokens = (manifest or {}).get("token_usage")
    if isinstance(tokens, dict) and tokens.get("by_stage"):
        out["tokens_by_stage"] = dict(tokens["by_stage"])
        out["tokens_total"] = tokens.get("total")
    diag = res.get("gap_agent_diagnostics")
    if isinstance(diag, dict) and diag:
        out["agent_diagnostics"] = diag
    return out


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
