"""
Settings for apps/api (Clinova Phase 5, Epic 5.1). Reuses the exact
minimal-.env-loader convention already used by app.py and
evals/benchmarks/baseline/*.py -- no python-dotenv dependency, real
environment variables always win.
"""
import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() and k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip()


_load_dotenv(_REPO_ROOT / ".env")

API_PORT = int(os.environ.get("CLINOVA_API_PORT", "8000"))
CORS_ORIGINS = [
    o.strip() for o in os.environ.get("CLINOVA_API_CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
BRANDING_DIR = _REPO_ROOT / "packages" / "branding"
