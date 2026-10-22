"""Entry script for browser tests: the real app, but background jobs run a scripted
fake pipeline (a few slow stages, then a saved golden run) instead of calling models."""
import runpy
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import utils.database as db  # noqa: E402
from tests.fixtures.make_golden_run import golden_results  # noqa: E402
from utils import run_jobs  # noqa: E402

STAGE_SECONDS = 3


def _fake_runner(**kw):
    for msg, pct in [("Stage 1 — Parsing PDFs…", 5), ("Stage 2 — Compiling LLM Wiki pages…", 25),
                     ("Stage 4 — Finding research gaps", 55), ("Stage 6 — Generating proposals…", 70)]:
        kw["progress"](msg, pct)
        kw["trace"](msg, "in", "out")
        time.sleep(STAGE_SECONDS)
    run_id = db.save_run("Background e2e run", golden_results(), project_id=kw["options"].project_id)
    return SimpleNamespace(run_id=run_id, name="Background e2e run", n_papers=3, n_gaps=2, n_proposals=1,
                           n_evidence=0, gate_blocked=False, gate_block_reasons=[], duration_seconds=12.0)


if not getattr(run_jobs, "_e2e_patched", False):
    _real = run_jobs.start_job
    run_jobs.start_job = lambda **kw: _real(**kw, runner=_fake_runner)
    run_jobs._e2e_patched = True

runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
