"""
Shared "most recent run in this project" lookup (Clinova Phase 5, Epic 5.2-5.4).
Every project-scoped screen (Dashboard, Corpus, Evidence, Knowledge Graph,
Research Gaps, Proposals) needs the same basis-run resolution dashboard_service.py
originally implemented inline -- centralized here once a 5th caller made the
duplication real, not speculative.
"""
from utils.database import list_runs, load_run


def list_project_runs(project_id: str) -> list[dict]:
    """Newest-first, matching list_runs()'s own ordering."""
    return [r for r in list_runs(limit=200) if (r.get("domain") or "default") == project_id]


def get_basis_run(project_id: str) -> tuple[dict, dict] | tuple[None, None]:
    """Returns (run_row, results_dict) for the most recent run in this
    project, or (None, None) if the project has no runs."""
    runs = list_project_runs(project_id)
    if not runs:
        return None, None
    basis_row = runs[0]
    loaded = load_run(basis_row["id"]) or {}
    return basis_row, (loaded.get("results", {}) or {})
