"""
Shared "which run is this screen showing" resolution (Clinova Phase 5,
Epic 5.2-5.4, extended in Slice 15).

Every project-scoped screen (Dashboard, Corpus, Data Quality, Evidence,
Knowledge Graph, Gap Challenger, Council, Search) resolves its basis run the
same way, and every one of them prints a sentence naming that run. Both live
here exactly once.
"""
from dataclasses import dataclass

from utils.database import list_runs, load_run


def list_project_runs(project_id: str) -> list[dict]:
    """Newest-first, matching list_runs()'s own ordering."""
    return [r for r in list_runs(limit=200) if (r.get("domain") or "default") == project_id]


@dataclass(frozen=True)
class Basis:
    """The run a project-scoped view is built from, plus whether it is the
    newest one. `is_latest` exists because the sentence every screen prints
    ("the most recent run in this project") stopped being true the moment
    the workspace gained a run switcher -- and it was hardcoded in seven
    services, so it would have gone on lying in all seven."""
    row: dict
    results: dict
    is_latest: bool

    def note(self, subject: str) -> str:
        """`subject` must be grammatically singular -- it is rendered as
        "{subject} reflects run ...", so "Counts" yields "Counts reflects"."""
        where = (
            "the most recent run in this project" if self.is_latest
            else "an earlier run you selected; the newest run is shown by default"
        )
        return f"{subject} reflects run \"{self.row['name']}\" ({self.row['id'][:8]}) — {where}."


def get_basis(project_id: str, run_id: str | None = None) -> Basis | None:
    """The run a project-scoped view should show, or None if the project has
    no runs at all.

    Defaults to the most recent run. Pass `run_id` to pin a specific one --
    that is what lets the workspace's run switcher change every tab at once
    instead of every screen independently showing "whatever ran last".

    An unknown or out-of-project run_id falls back to the most recent run
    rather than raising: the id arrives from a URL the user can edit or
    bookmark, and a stale bookmark should land on real data rather than a
    404. The fallback is not silent -- `is_latest` drives a note naming the
    run actually shown.
    """
    runs = list_project_runs(project_id)
    if not runs:
        return None
    row = next((r for r in runs if r["id"] == run_id), runs[0]) if run_id else runs[0]
    loaded = load_run(row["id"]) or {}
    return Basis(row=row, results=(loaded.get("results", {}) or {}), is_latest=row["id"] == runs[0]["id"])


def get_basis_run(project_id: str, run_id: str | None = None) -> tuple[dict, dict] | tuple[None, None]:
    """Tuple form of get_basis(), kept for callers that do not need
    `is_latest`. Prefer get_basis() in new code."""
    basis = get_basis(project_id, run_id)
    return (None, None) if basis is None else (basis.row, basis.results)
