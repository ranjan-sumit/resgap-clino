"""The group control and section pills: a click and a jump from code are told apart, and every click takes effect.

The regression these guard: after the controls' keys started to change with each click, the browser's NEXT click went to a
widget the new run no longer drew, so it was dropped (the last pill of a row, such as Proposals or Wiki, appeared dead).
"""
import pytest

from tests.fixtures.make_golden_run import golden_comp, golden_results, seed_run
from ui.navigation import ALL_TABS, TAB_GROUPS, adopt_click, group_of, valid_tab


class FakeApp:
    """The app's per-run navigation block, with the browser's widget state in a dict (the same calls, in the same order)."""

    def __init__(self):
        self.s = {"result_tab": "Overview"}
        self.run()

    def run(self):
        s = self.s
        s["result_tab"] = valid_tab(s.get("result_tab"))
        g = group_of(s["result_tab"])
        s["result_tab"] = adopt_click(s["result_tab"], s.get("result_group"), s.get(f"result_pill_{g}"),
                                      s.get("_nav_group"), s.get("_nav_tab"))
        tab = s["result_tab"]
        g = group_of(tab)
        s["result_group"], s[f"result_pill_{g}"] = g, tab           # what the controls show after this run
        s["_nav_group"], s["_nav_tab"] = g, tab
        return tab

    def click_pill(self, name):
        self.s[f"result_pill_{group_of(self.s['_nav_tab'])}"] = name   # the browser changes the control the run drew
        return self.run()

    def click_group(self, name):
        self.s["result_group"] = name
        return self.run()

    def jump(self, tab):
        self.s["result_tab"] = tab                                      # a button callback, or a test, sets it directly
        return self.run()


def test_successive_pill_clicks_each_take_effect():
    app = FakeApp()
    assert [app.click_pill(t) for t in ("Gaps", "Proposals", "Overview", "Proposals", "Gaps")] == \
           ["Gaps", "Proposals", "Overview", "Proposals", "Gaps"]       # the second click used to be lost


def test_clicks_across_groups_and_back():
    app = FakeApp()
    assert app.click_group("Evidence") == "Evidence"                     # a group opens on its first section
    assert [app.click_pill(t) for t in ("Graph", "Wiki", "References", "Wiki")] == ["Graph", "Wiki", "References", "Wiki"]
    assert app.click_group("Audit") == "Lab"
    assert app.click_pill("Export") == "Export"
    assert app.click_group("Results") == "Overview"
    assert app.click_pill("Gaps") == "Gaps"


def test_a_jump_from_code_wins_over_a_control_that_still_shows_the_old_section():
    app = FakeApp()
    app.click_pill("Gaps")
    assert app.jump("Evidence") == "Evidence" and app.s["result_group"] == "Evidence"        # another group
    assert app.jump("Wiki") == "Wiki" and app.s["result_pill_Evidence"] == "Wiki"           # the same group
    assert app.jump("Overview") == "Overview"
    assert app.click_pill("Proposals") == "Proposals"                                       # and clicks still work afterwards


def test_clicking_the_open_pill_or_group_again_does_not_blank_the_screen():
    app = FakeApp()
    app.click_pill("Gaps")
    app.s["result_pill_Results"] = None                                  # Streamlit reports a de-selection as None
    assert app.run() == "Gaps" and app.s["result_pill_Results"] == "Gaps"
    app.s["result_group"] = None
    assert app.run() == "Gaps" and app.s["result_group"] == "Results"


def test_an_unknown_section_falls_back_to_the_overview():
    app = FakeApp()
    assert app.jump("No such section") == "Overview"
    assert valid_tab(None) == "Overview"


def test_the_groups_cover_every_section_once():
    assert len(ALL_TABS) == len(set(ALL_TABS)) == 10
    assert all(group_of(t) in TAB_GROUPS for t in ALL_TABS)


# ── the same thing in the real app, driven the way a person drives it ────────────────────────────
@pytest.mark.ui
def test_clicking_through_the_real_app_takes_effect_every_time(app_test, isolated_env):
    seed_run(golden_results(), comp_results=golden_comp())
    at = app_test(timeout=90)

    def pills():
        return next(g for g in at.get("button_group") if (g.key or "").startswith("result_pill_"))

    def group():
        return next(g for g in at.get("button_group") if g.key == "result_group")

    def tab():
        return at.session_state["result_tab"]

    for target in ("Gaps", "Proposals", "Overview", "Proposals"):
        pills().set_value(target).run()
        assert tab() == target and pills().value == target and not at.exception
    group().set_value("Evidence").run()
    assert tab() == "Evidence" and group().value == "Evidence"
    for target in ("Graph", "Wiki", "References", "Wiki"):
        pills().set_value(target).run()
        assert tab() == target and pills().value == target and not at.exception
    group().set_value("Audit").run()
    assert tab() == "Lab"
    pills().set_value("Export").run()
    assert tab() == "Export"
    group().set_value("Results").run()
    assert tab() == "Overview"
    at.button(key="ov_all_gaps").click().run()                           # a jump from a button inside the page
    assert tab() == "Gaps" and pills().value == "Gaps"
