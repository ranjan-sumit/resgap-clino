"""UI-14: rules about what the screens show. A rule that today's UI already breaks is a ratchet (see tests/ui_rules.py):
the known violations live in tests/data/ui_rules_baseline.json, a new one fails, and a fixed one must be removed.

To record the current state after a deliberate change that LOWERS the baseline (never to add to it):
    set UI_RULES_WRITE_BASELINE=1 and run this file once.
"""
import json
import os
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests import ui_rules as R
from tests.fixtures.make_golden_run import golden_comp, golden_results, seed_run
from tests.ui_helpers import PID, click, next_step, open_settings, open_wizard, store_papers, tick_stored_papers

pytestmark = pytest.mark.ui

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "data" / "ui_rules_baseline.json"
SECTIONS = ["Overview", "Gaps", "Proposals", "Evidence", "References", "Graph", "Wiki", "Lab", "Trace", "Export"]
# Warm rerun of one section, on the synthetic project. Generous today; UI-12 tightens it as the reruns get cheaper.
RENDER_BUDGET_S = float(os.environ.get("UI_RENDER_BUDGET_S", "6"))
WRITE = os.environ.get("UI_RULES_WRITE_BASELINE") == "1"


def _baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {"copy": [], "multi_primary": {}}


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """Every screen of the app rendered once against a synthetic project: what is visible, which buttons are solid,
    and how long a warm section rerun took."""
    import utils.database as db
    base = tmp_path_factory.mktemp("ui_rules")
    mp = pytest.MonkeyPatch()
    mp.setenv("RESGAP_DB_PATH", str(base / "ui.db"))
    mp.setenv("RESGAP_PROJECTS_DIR", str(base / "projects"))
    mp.setenv("GEMINI_API_KEY", "k" * 30)
    db._INITIALIZED.clear()
    out = {"copy": [], "primary": {}, "timing": {}}

    def app():
        return AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()

    def grab(name, at):
        out["copy"] += R.copy_problems(R.collect(at), name)
        out["primary"][name] = R.primary_buttons(at)

    try:
        ids = store_papers(2)
        grab("home (empty project)", app())
        seed_run(golden_results(), comp_results=golden_comp())
        at = app()
        for sec in SECTIONS:
            at.session_state["result_tab"] = sec
            at.run()
            t0 = time.perf_counter()
            at.run()
            out["timing"][sec] = time.perf_counter() - t0
            grab(f"results / {sec}", at)
        at = app(); open_settings(at); grab("settings", at)
        at = app(); click(at, "new_project_btn"); grab("new project", at)
        at = app(); open_wizard(at); tick_stored_papers(at, PID, ids); grab("wizard / 1 papers", at)
        for step, name in enumerate(("2 setup", "3 options", "4 review"), 2):
            next_step(at); grab(f"wizard / {name}", at)
        out["copy"] = sorted(set(out["copy"]))
        yield out
    finally:
        mp.undo()
        db._INITIALIZED.clear()


def _maybe_write(rendered) -> bool:
    if not WRITE:
        return False
    multi = {s: len(b) for s, b in rendered["primary"].items() if len(b) > 1}
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps({"copy": rendered["copy"], "multi_primary": multi}, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return True


# ── the rules, on the real screens ───────────────────────────────────────────────────────────────
def test_a_screen_has_at_most_one_solid_button(rendered):
    if _maybe_write(rendered):
        return
    known = _baseline()["multi_primary"]
    now = {s: len(b) for s, b in rendered["primary"].items() if len(b) > 1}
    worse = {s: (n, rendered["primary"][s]) for s, n in now.items() if n > known.get(s, 1)}
    fixed = [s for s in known if now.get(s, 0) <= 1]
    assert not worse, f"more than one solid button (a screen is about one action): {worse}"
    assert not fixed, f"fixed, so remove from the baseline (UI_RULES_WRITE_BASELINE=1): {fixed}"


def test_copy_has_no_long_dashes_and_no_emoji_in_headings_or_labels(rendered):
    if _maybe_write(rendered):
        return
    known = set(_baseline()["copy"])
    new = sorted(set(rendered["copy"]) - known)
    fixed = sorted(known - set(rendered["copy"]))
    assert not new, "new copy that breaks the tone rules:\n  " + "\n  ".join(new)
    assert not fixed, ("fixed, so remove from the baseline (UI_RULES_WRITE_BASELINE=1):\n  " + "\n  ".join(fixed))


def test_every_section_rerenders_within_the_budget(rendered):
    slow = {s: round(t, 1) for s, t in rendered["timing"].items() if t > RENDER_BUDGET_S}
    assert not slow, f"over {RENDER_BUDGET_S} s for a warm rerun: {slow}"


def test_the_baseline_file_is_well_formed():
    b = _baseline()
    assert set(b) == {"copy", "multi_primary"} and b["copy"] == sorted(set(b["copy"]))
    assert all(isinstance(n, int) and n > 1 for n in b["multi_primary"].values())


# ── each rule fails on a deliberate violation ────────────────────────────────────────────────────
def test_the_copy_rule_flags_a_long_dash_and_an_emoji_heading():
    found = R.copy_problems([("heading", "Pipeline Trace — Explainability View"), ("heading", "\U0001F50E Pipeline Trace"),
                             ("label", "✅ Done")], "demo")
    assert [f.split(" | ")[2] for f in found] == ["emoji", "emoji", "long dash"] or len(found) == 3
    assert any("long dash" in f for f in found) and sum("emoji" in f for f in found) == 2


def test_the_copy_rule_allows_status_marks_plain_headings_and_emoji_free_text():
    ok = [("heading", "Pipeline trace"), ("text", "✓ Processed"), ("text", "Next → step"),
          ("text", "An emoji in body text, \U0001F600, is not a heading"), ("label", "Run analysis")]
    assert R.copy_problems(ok, "demo") == []


def test_the_copy_rule_ignores_styles_and_tags_and_finds_html_headings():
    assert R.plain("<style>.a { content: '—' }</style><b>Hello</b> &amp; bye") == "Hello & bye"
    app = ('import streamlit as st\nst.markdown("<h3>\\U0001F4CA Lab</h3>", unsafe_allow_html=True)\n'
           'st.markdown("### Plain heading")\nst.caption("a \\u2014 b")\n')
    at = AppTest.from_string(app).run()
    kinds = R.collect(at)
    assert ("heading", "\U0001F4CA Lab") in kinds and ("heading", "Plain heading") in kinds
    assert len(R.copy_problems(kinds, "demo")) == 2                        # the emoji heading and the caption's long dash


def test_the_button_rule_counts_the_main_area_only():
    app = ('import streamlit as st\nwith st.sidebar:\n    st.button("Side", type="primary")\n'
           'st.button("A", type="primary")\nst.button("B", type="primary")\nst.button("C")\n')
    at = AppTest.from_string(app).run()
    assert R.primary_buttons(at) == ["A", "B"]                              # two solid buttons: the rule would fail this screen


def test_the_button_rule_does_not_count_a_forms_submit_button():
    app = ('import streamlit as st\nst.button("Go", type="primary")\n'
           'with st.expander("Feedback"):\n    with st.form("f"):\n        st.form_submit_button("Save", type="primary")\n')
    at = AppTest.from_string(app).run()
    assert R.primary_buttons(at) == ["Go"]
