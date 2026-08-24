"""
Real git commit hash, computed once per process (Clinova Phase 5).
Duplicated from app.py's `_git_commit()` rather than imported -- app.py
is a Streamlit script with top-level `st.*` calls and can't be safely
imported by a non-Streamlit process. Same honest-None behavior: no fake
placeholder hash if git isn't on PATH or this isn't a checkout.
"""
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT,
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


GIT_COMMIT = _git_commit()
