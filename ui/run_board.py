"""The run board: one readable row per run (no hash ids), from the run list and the stored manifests."""
from __future__ import annotations

from utils.run_storage import to_local_display


def _minutes(seconds) -> str:
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return "—"
    return f"{int(seconds // 60)} min {int(seconds % 60):02d} s" if seconds >= 60 else f"{int(seconds)} s"


def _tokens(usage) -> str:
    total = (usage or {}).get("total") if isinstance(usage, dict) else None
    return f"{total:,}" if isinstance(total, int) else "—"


def _model(manifest: dict) -> str:
    bundle = str((manifest or {}).get("model_bundle_version") or "")
    # "provider:model" or a role summary: show the model part, shortened
    return bundle.split(":")[-1][:34] if bundle else "—"


def status_chip(run: dict, manifest: dict | None, gate_blocked: bool = False) -> str:
    if run.get("archived"):
        return "Archived"
    if gate_blocked:
        return "Quality check failed"
    if manifest is None:
        return "No manifest"
    warnings = manifest.get("warnings") or []
    return f"Completed · {len(warnings)} warning(s)" if warnings else "Completed"


def board_rows(runs: list[dict], manifests: dict, feedback_counts: dict | None = None,
               gate_blocked: dict | None = None, tz_name: str | None = None) -> list[dict]:
    """Rows for the table, in the order given. Everything is human-readable; run ids stay out of it."""
    feedback_counts = feedback_counts or {}
    gate_blocked = gate_blocked or {}
    rows = []
    for r in runs:
        m = manifests.get(r["id"])
        rows.append({
            "Run": r["name"],
            "Created": to_local_display(r["created_at"], tz_name),
            "Status": status_chip(r, m, bool(gate_blocked.get(r["id"]))),
            "Papers": r["n_papers"], "Gaps": r["n_gaps"], "Proposals": r["n_proposals"],
            "Lab": "✓" if r["has_comp"] else "",
            "Model": _model(m or {}),
            "Duration": _minutes((m or {}).get("run_duration_seconds")),
            "Tokens": _tokens((m or {}).get("token_usage")),
            "Feedback": feedback_counts.get(r["id"], 0),
        })
    return rows


def run_label(run: dict, tz_name: str | None = None) -> str:
    """How a run is named in a picker or sentence: its name and date, never its id."""
    return f"{run['name']} · {to_local_display(run['created_at'], tz_name)}"
