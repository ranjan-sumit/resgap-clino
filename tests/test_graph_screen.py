from tests.fixtures.make_golden_run import golden_results, legacy_results, seed_run
from ui import evidence_view as ev
from ui import graph_view as gv


def _rows():
    g = golden_results()
    by_id = {r["id"]: r for r in ev.evidence_rows(g)}
    return gv.relation_rows(g["graph"], by_id), g


def test_rows_resolve_names_and_carry_quote_page_and_section():
    rows, _ = _rows()
    first = rows[0]
    assert (first["source"], first["relation"], first["target"]) == ("airway chip", "limited by", "static culture")
    assert first["quote"] == "Follow-up was 3 months." and first["page"] == 4 and first["evidence_ids"] == ["e1"]
    assert rows[1]["page"] == 2 and rows[1]["section"] == "Methods"            # page taken from the evidence item
    assert rows[2]["grounded"] is False and rows[2]["quote"] == ""             # a paraphrase edge shows no quote


def test_filters_by_relation_paper_entity_and_grounding():
    rows, _ = _rows()
    assert [r["relation"] for r in gv.filter_relations(rows, relations=("compared with",))] == ["compared with"]
    assert len(gv.filter_relations(rows, paper="Alpha trial of drug X")) == 1
    assert len(gv.filter_relations(rows, entity="CHIP")) == 2
    assert len(gv.filter_relations(rows, grounded_only=True)) == 2
    assert gv.filter_relations(rows, entity="no such entity") == []


def test_grounding_summary_counts_cited_relations():
    _, g = _rows()
    assert gv.grounding_summary(g["graph"]) == {"relations": 3, "grounded": 2, "share": 0.667}
    assert gv.grounding_summary({}) == {"relations": 0, "grounded": 0, "share": None}


def test_orphan_explanation_for_grounded_and_older_graphs():
    _, g = _rows()
    text = gv.orphan_explanation(g["graph"])
    assert "3 entities had no relationship" in text and "1 remain unlinked" in text
    older = {"stats": {"orphan_count": 5}, "diagnostics": {}}
    assert "5 entities appear in only one paper" in gv.orphan_explanation(older)
    assert gv.orphan_explanation({"stats": {}, "diagnostics": {}}) == ""


def _texts(at):
    return " ".join(str(getattr(e, "value", "")) for e in (*at.markdown, *at.caption, *at.info, *at.warning))


def _open(app_test, results):
    seed_run(results)
    at = app_test(timeout=90)
    at.session_state["result_tab"] = "Graph"
    return at.run()


def test_graph_section_shows_the_relations_table_with_evidence_and_the_orphan_note(app_test, isolated_env):
    at = _open(app_test, golden_results())
    assert not at.exception
    t = _texts(at)
    assert "Built from the papers' quoted evidence" in t
    assert "2 of 3 relations cite a quoted passage" in t and "3 of 3 relations" in t
    assert "1 remain unlinked" in t
    df = at.dataframe[0].value
    assert "airway chip" in df.to_string() and "Follow-up was 3 months." in df.to_string()


def test_relation_filters_narrow_the_table(app_test, isolated_env):
    at = _open(app_test, golden_results())
    at.multiselect(key="gr_relation").select("limited by").run()
    assert "1 of 3 relations" in _texts(at)
    at.multiselect(key="gr_relation").unselect("limited by").run()
    at.text_input(key="gr_entity").set_value("cohort").run()
    assert "2 of 3 relations" in _texts(at)


def test_graph_section_for_a_run_without_a_graph_still_renders(app_test, isolated_env):
    assert not _open(app_test, legacy_results()).exception
