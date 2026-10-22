import re

import utils.database as db
from tests.fixtures.make_golden_run import golden_comp, golden_results
from tests.test_run_management import PID, _saved_run
from utils import project_store


def _project_view(app_test, project_id=PID, selected_rows=()):
    at = app_test(timeout=90)
    if project_id != PID:
        at.session_state["project_select"] = project_id
    at.session_state["main_view"] = "Project"
    if selected_rows:
        at.session_state[f"project_runs_{project_id}"] = {"selection": {"rows": list(selected_rows), "columns": []}}
    return at.run()


def _texts(at):
    return " ".join(str(getattr(e, "value", "")) for e in (*at.markdown, *at.caption, *at.info, *at.warning, *at.success))


def test_the_board_has_readable_columns_and_no_id(app_test, isolated_env):
    _saved_run("Alpha run")
    at = _project_view(app_test)
    assert not at.exception, [e.value for e in at.exception]
    cols = list(at.dataframe[0].value.columns)
    assert cols == ["Run", "Created", "Status", "Papers", "Gaps", "Proposals", "Lab", "Model", "Duration", "Tokens", "Feedback"]
    assert "ID" not in cols


def test_archived_runs_are_hidden_until_asked_for(app_test, isolated_env):
    a, b = _saved_run("visible"), _saved_run("hidden")
    db.set_run_archived(b, True)
    at = _project_view(app_test)
    assert list(at.dataframe[0].value["Run"]) == ["visible"]
    at.checkbox(key=f"show_archived_{PID}").check().run()
    df = at.dataframe[0].value
    assert set(df["Run"]) == {"visible", "hidden"} and df[df["Run"] == "hidden"]["Status"].iloc[0] == "Archived"


def test_the_sidebar_run_list_hides_archived_runs(app_test, isolated_env):
    _saved_run("shown")
    gone = _saved_run("gone")
    db.set_run_archived(gone, True)
    at = app_test(timeout=90)
    picker = next(s for s in at.sidebar.selectbox if s.label == "Run")
    assert len(picker.options) == 1 and "shown" in picker.options[0]


def test_a_selected_run_can_be_renamed_and_archived(app_test, isolated_env):
    rid = _saved_run("original")
    at = _project_view(app_test, selected_rows=[0])
    at.text_input(key=f"rename_{rid}").set_value("Renamed run").run()
    at.button(key=f"rename_btn_{rid}").click().run()
    assert db.get_run_row(rid)["name"] == "Renamed run"
    at = _project_view(app_test, selected_rows=[0])
    at.button(key=f"archive_{rid}").click().run()
    assert db.get_run_row(rid)["archived"] == 1


def test_the_rename_button_is_off_until_the_name_changes(app_test, isolated_env):
    rid = _saved_run("same")
    at = _project_view(app_test, selected_rows=[0])
    assert at.button(key=f"rename_btn_{rid}").disabled


def test_delete_lists_what_will_go_and_needs_confirmation(app_test, isolated_env):
    rid = _saved_run("doomed")
    db.upsert_feedback(PID, rid, "gap", "g1", rating=1, target_label="x")
    at = _project_view(app_test, selected_rows=[0])
    t = _texts(at)
    assert "doomed" in t and "saved file(s)" in t and "1 feedback item(s)" in t
    assert not any(b.key == "delete_runs_btn" for b in at.button)    # the button only appears once confirmed
    at.checkbox(key="confirm_delete_runs").check().run()
    at.button(key="delete_runs_btn").click().run()
    assert db.get_run_row(rid) is None


def test_duplicates_are_offered_for_merging(app_test, isolated_env):
    keep = _saved_run("one")
    dup = _saved_run("two", comp=golden_comp())
    at = _project_view(app_test)
    assert any("duplicate runs" in e.label for e in at.expander)
    at.button(key=f"merge_{PID}_0").click().run()
    assert db.get_run_row(keep)["archived"] + db.get_run_row(dup)["archived"] == 1
    assert [r["has_comp"] for r in db.list_runs()] == [1]          # the one with Lab results is kept


def test_project_settings_are_saved(app_test, isolated_env):
    p = project_store.create_project("Editable", "old", "healthcare", "old interest")
    at = _project_view(app_test, p["id"])
    assert not at.exception
    form_inputs = [t for t in at.text_input if t.label == "Project name"]
    form_inputs[0].set_value("Edited name")
    [t for t in at.text_area if t.label == "Description"][0].set_value("edited description")
    next(b for b in at.button if b.label == "Save settings").click().run()
    row = db.get_project(p["id"])
    assert row["name"] == "Edited name" and row["description"] == "edited description"


def test_the_default_project_offers_no_delete(app_test, isolated_env):
    at = _project_view(app_test)
    assert not any(e.label == "Delete this project" for e in at.expander)


def test_a_project_can_be_deleted_after_confirmation(app_test, isolated_env):
    p = project_store.create_project("Short lived")
    rid = _saved_run("inside", project=p["id"])
    at = _project_view(app_test, p["id"])
    assert any(e.label == "Delete this project" for e in at.expander)
    assert "1 run(s)" in _texts(at) and "inside" in _texts(at)
    at.checkbox(key=f"confirm_delete_project_{p['id']}").check().run()
    at.button(key=f"delete_project_btn_{p['id']}").click().run()
    assert db.get_project(p["id"]) is None and db.get_run_row(rid) is None
    assert at.session_state["current_project_id"] == PID


def test_no_run_id_appears_on_the_project_screen(app_test, isolated_env):
    a, b = _saved_run("first"), _saved_run("second", {**golden_results(), "gaps": golden_results()["gaps"][:1]})
    at = _project_view(app_test, selected_rows=[0, 1])
    text = _texts(at) + " ".join(str(x.value) for x in at.dataframe[0:1])
    for rid in (a, b):
        assert rid not in text and rid[:8] not in text


def test_two_selected_runs_show_a_named_comparison_with_cards(app_test, isolated_env):
    _saved_run("older run")
    _saved_run("newer run", {**golden_results(), "gaps": golden_results()["gaps"][:1]}, comp=golden_comp())
    at = _project_view(app_test, selected_rows=[0, 1])
    assert not at.exception
    t = _texts(at)
    assert "Compare:" in t and "older run" in t and "newer run" in t
    assert "Papers in common" in t and "New gaps" in t
