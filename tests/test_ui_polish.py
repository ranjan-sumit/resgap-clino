"""UI-01: defects found in the screen-by-screen audit, one regression test each."""
import re
from pathlib import Path

import pytest

from tests.ui_helpers import PID, next_step, open_wizard, store_papers, texts, tick_stored_papers
from ui import graph_view as gv
from ui.components import shorten, stepper_html

ROOT = Path(__file__).resolve().parent.parent


# ── shorten: a cut never lands inside a word ─────────────────────────────────────────────────
def test_shorten_cuts_at_a_word_boundary_and_leaves_short_text_alone():
    title = "Modeling pulmonary cystic fibrosis in a human lung airway-on-a-chip"
    out = shorten(title, 30)
    assert out.endswith("…") and len(out) <= 30
    assert out[:-1] in title and title[len(out[:-1]):].startswith((" ", "-")), out      # whole words only
    assert shorten("Short title", 30) == "Short title"
    assert shorten(None) == "" and shorten("  spaced   out  ") == "spaced out"


def test_shorten_handles_one_very_long_word():
    out = shorten("x" * 80, 20)
    assert out == "x" * 19 + "…"


# ── the wizard's step indicator is HTML, so no label can become a markdown list ───────────────
def test_stepper_marks_done_current_and_coming_steps():
    h = stepper_html(["Papers", "Research setup", "Options", "Review and run"], 3)
    assert h.count('aria-current="step"') == 1
    assert re.findall(r'class="wz-step (\w+)"', h) == ["done", "done", "current", "todo"]
    assert not re.match(r"\s*\d+\.\s", h)                      # the old text began "1. Papers", which markdown made a list
    assert "&lt;b&gt;" in stepper_html(["<b>x</b>"], 1)        # a label is escaped


def test_the_wizard_shows_the_stepper_on_every_step(app_test, isolated_env):
    ids = store_papers(2)
    at = open_wizard(app_test(timeout=90))
    tick_stored_papers(at, PID, ids)
    assert 'class="wz-step current"' in texts(at)
    next_step(at); next_step(at)                                # step 3, where the old text turned into a list
    t = texts(at)
    assert t.count('aria-current="step"') == 1 and "Options" in t


# ── the relations table can be sent to the browser ───────────────────────────────────────────
_ROWS = [{"source": "a", "relation": "treats", "target": "b", "paper": "P" * 60, "page": 4, "quote": "q" * 200},
         {"source": "c", "relation": "limits", "target": "d", "paper": "P", "page": None, "quote": ""}]


def test_relation_table_cells_are_all_text():
    out = gv.relation_table_rows(_ROWS)
    assert [r["Page"] for r in out] == ["4", "n/a"]
    assert all(isinstance(v, str) for r in out for v in r.values())
    assert len(out[0]["Paper"]) == 40 and out[0]["Quote"].endswith("…") and len(out[0]["Quote"]) == 141


def test_relation_table_converts_to_arrow_without_falling_back():
    pa = pytest.importorskip("pyarrow")
    import pandas as pd
    pa.Table.from_pandas(pd.DataFrame(gv.relation_table_rows(_ROWS)))       # raised ArrowTypeError on a mixed Page column


# ── the sidebar's primary button stays readable when hovered ─────────────────────────────────
def test_sidebar_hover_rule_does_not_touch_the_primary_button():
    css = (ROOT / "app.py").read_text(encoding="utf-8")
    rules = re.findall(r'\[data-testid="stSidebar"\] \.stButton > button([^{]*):hover\s*\{', css)
    bare = [r for r in rules if 'kind="primary"' not in r]       # a hover rule that names no kind hits the primary too
    assert rules and not bare, bare
