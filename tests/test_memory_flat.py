"""Memory stays flat when many sessions load a run, and big per-session bytes are released when the run changes."""
import gc
import sys

import pytest
from streamlit.testing.v1 import AppTest

from tests.conftest import ROOT
from tests.fixtures.make_golden_run import golden_results, seed_run


def _session(timeout=90):
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=timeout).run()


@pytest.mark.slow
def test_twenty_session_loads_do_not_grow_memory(isolated_env):
    seed_run(golden_results())
    for _ in range(2):                       # warm-up: imports, framework caches, first database open
        _session()
    gc.collect()
    baseline = sys.getallocatedblocks()      # live Python objects; cheap, unlike tracemalloc (5 min for this test)
    samples = []
    for _ in range(20):
        at = _session()
        assert not at.exception
        del at
        gc.collect()
        samples.append(sys.getallocatedblocks() - baseline)
    print("blocks after each load:", samples)
    # flat: the second half of the loads adds (almost) nothing over the first half
    assert samples[-1] - samples[9] < 2000, f"live objects keep growing across session loads: {samples}"


def test_a_generated_report_is_released_when_another_run_is_opened(isolated_env):
    seed_run(golden_results(), name="First")
    seed_run(golden_results(), name="Second")
    at = _session()
    picker = next(s for s in at.sidebar.selectbox if s.label == "Run")
    first = next(o for o in picker.options if "First" in o)
    second = next(o for o in picker.options if "Second" in o)
    picker.select(first).run()
    run_id = at.session_state["current_run_id"]
    at.session_state["report_bundle"] = {"html": b"x" * 5_000_000, "pdf": b"y" * 5_000_000, "run_id": run_id}
    at.run()
    assert at.session_state["report_bundle"] is not None           # same run: kept
    picker = next(s for s in at.sidebar.selectbox if s.label == "Run")
    picker.select(second).run()
    assert at.session_state["report_bundle"] is None               # another run: the megabytes are dropped
