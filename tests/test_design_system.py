import re
from pathlib import Path

import pytest

from tests.fixtures.make_golden_run import golden_comp, golden_results, seed_run
from ui import glossary as gl
from ui import theme, tokens
from ui.run_board import status_chip

ROOT = Path(__file__).resolve().parent.parent


# ── one token set, AA contrast ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,fg,bg", tokens.REQUIRED_PAIRS)
def test_every_text_and_background_pair_meets_aa_contrast(name, fg, bg):
    assert tokens.contrast(fg, bg) >= tokens.AA_TEXT, f"{name}: {fg} on {bg} is {tokens.contrast(fg, bg)}:1"


def test_the_contrast_function_matches_known_values():
    assert tokens.contrast("#000000", "#ffffff") == 21.0
    assert tokens.contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.02)
    assert tokens.contrast("#ffffff", "#ffffff") == 1.0


def test_the_colours_that_failed_the_audit_are_gone_from_the_source():
    banned = ("#b7791f", "#8a99ad", "#697689", "#55708f")                              # amber text 3.2:1, grey text 2.5:1, caption 4.36:1
    for path in [ROOT / "app.py", *(ROOT / "ui").glob("*.py")]:
        if path.name == "tokens.py":
            continue                                                         # it names them in comments
        text = path.read_text(encoding="utf-8")
        assert not [c for c in banned if c in text], path.name


def test_the_accessibility_stylesheet_fixes_what_the_audit_found():
    css = theme.CSS_A11Y
    assert ":focus-visible" in css and "outline" in css                      # a visible keyboard focus
    assert "stCaptionContainer" in css and "opacity: 1" in css                # captions are not faded below AA
    assert 'button[role="radio"][aria-checked="true"]' in css and tokens.ACCENT_STRONG in css
    assert "max-width: 640px" in css                                          # phone layout rules
    assert css in {theme.CSS_A11Y} and "CSS_A11Y" in Path(theme.__file__).read_text(encoding="utf-8")


def test_the_sidebar_opens_only_on_wide_screens_and_closes_after_a_choice_on_phones():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'initial_sidebar_state="auto"' in src
    assert 'st.session_state["_collapse_sidebar"] = True' in src and "collapse_sidebar_on_phones()" in src
    assert "stSidebarCollapseButton" in (ROOT / "ui" / "components.py").read_text(encoding="utf-8")


def test_choosing_a_page_from_the_sidebar_requests_the_collapse_once(app_test, isolated_env):
    at = app_test(timeout=90)
    at.button(key="settings_btn").click().run()
    assert at.session_state["view"] == "settings"
    assert "_collapse_sidebar" not in at.session_state                        # consumed on the run that drew the script


# ── shared states ───────────────────────────────────────────────────────────────────────────
def test_shared_states_render_with_roles_and_escape_their_text(app_test, isolated_env):
    from ui import components as c
    html = c._state_box("○", "<b>x</b> title", "hint & <i>more</i>", "#7ab8f5", "status")
    assert 'role="status"' in html and "&lt;b&gt;x&lt;/b&gt; title" in html and "hint &amp; &lt;i&gt;more&lt;/i&gt;" in html
    assert 'role="alert"' in c._state_box("!", "t", "", "#c81e1e", "alert")


def test_empty_evidence_and_gap_screens_use_the_shared_empty_state(app_test, isolated_env):
    r = golden_results()
    r["evidence_objects"], r["gaps"] = {}, []
    seed_run(r)
    at = app_test(timeout=90)
    at.session_state["result_tab"] = "Evidence"
    at.run()
    assert 'role="status"' in " ".join(m.value for m in at.markdown) and "No stored evidence items" in " ".join(m.value for m in at.markdown)
    at.session_state["result_tab"] = "Gaps"
    at.run()
    assert "No gaps in this run" in " ".join(m.value for m in at.markdown)


# ── glossary ────────────────────────────────────────────────────────────────────────────────
def test_every_gap_status_and_challenger_label_has_a_definition():
    labels = ["Open", "Partial", "Solved", "Pending", "Not checked", "Challenger: open", "Partially open", "Contested",
              "Likely closed", "Closed", "Insufficient evidence"]
    assert [l for l in labels if not gl.lookup(l)] == []


def test_every_run_status_the_board_can_show_has_a_definition():
    run = {"archived": 0}
    chips = [status_chip(run, {"warnings": []}), status_chip(run, {"warnings": ["w"]}), status_chip(run, None),
             status_chip(run, {}, gate_blocked=True), status_chip({"archived": 1}, None)]
    assert [c for c in chips if not gl.lookup(c)] == []


def test_the_terms_the_interface_names_are_defined():
    for term in ("orphan signals", "communities", "coverage", "quote rate", "paper coverage", "simulation skipped",
                 "measured", "opinion", "token cap", "fallback model", "agreement with the previous run"):
        assert gl.definition(term), term


def test_definitions_are_plain_sentences():
    for term, text in gl.GLOSSARY.items():
        assert text.endswith(".") and 20 <= len(text) <= 200 and "TODO" not in text, term


def test_lookup_tolerates_case_and_variants_and_unknowns():
    assert gl.lookup("  OPEN ") == gl.GLOSSARY["open"] and gl.lookup("Completed · 3 warning(s)") == gl.GLOSSARY["completed"]
    assert gl.lookup("something unknown") == ""


def test_gap_status_badges_carry_their_definition_as_a_hover_hint(app_test, isolated_env):
    seed_run(golden_results())
    at = app_test(timeout=90)
    at.session_state["result_tab"] = "Gaps"
    at.run()
    text = " ".join(m.value for m in at.markdown)
    assert f'title="{gl.GLOSSARY["open"]}"' in text and f'title="{gl.GLOSSARY["partial"]}"' in text


def test_the_overview_has_a_glossary(app_test, isolated_env):
    seed_run(golden_results())
    at = app_test(timeout=90)
    assert any(e.label == "Glossary: what the labels mean" for e in at.expander)
    assert gl.GLOSSARY["orphan signals"] in " ".join(m.value for m in at.markdown)


def test_graph_counters_carry_definitions(app_test, isolated_env):
    seed_run(golden_results())
    at = app_test(timeout=90)
    at.session_state["result_tab"] = "Graph"
    at.run()
    text = " ".join(m.value for m in at.markdown)
    assert f'title="{gl.GLOSSARY["orphan signals"]}"' in text and f'title="{gl.GLOSSARY["communities"]}"' in text
