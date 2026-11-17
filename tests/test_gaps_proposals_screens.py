import pytest

from tests.fixtures.make_golden_run import golden_results, legacy_results, seed_run
from ui import gaps_view as gv


# ── view-models ─────────────────────────────────────────────────────────────────────────────
def rows():
    return gv.gap_rows(golden_results())


def test_rows_expose_status_finder_papers_score_and_links():
    r = {x["gap_id"]: x for x in rows()}
    assert r["g1"]["status"] == "open" and r["g1"]["finder"] == "Limitation miner"
    assert r["g1"]["n_papers"] == 2 and r["g1"]["score"] == 4.2 and r["g1"]["n_evidence"] == 2
    assert r["g1"]["links"][0] == {"title": "A related long-term study", "year": 2020, "url": "https://doi.org/10.1/rel"}
    assert r["g1"]["links"][1]["url"] is None
    assert r["g2"]["status"] == "partial" and r["g2"]["finder"] == "Methodology audit"


def test_a_doi_alone_becomes_a_link():
    g = golden_results()
    g["gaps"][0]["existing_papers"] = [{"title": "T", "year": 2021, "doi": "10.9/zzz"}]
    assert gv.gap_rows(g)[0]["links"][0]["url"] == "https://doi.org/10.9/zzz"


def test_sorting_by_rank_score_status_and_papers():
    rs = rows()
    assert [r["gap_id"] for r in gv.sort_gaps(rs, "Rank")] == ["g1", "g2"]
    assert [r["gap_id"] for r in gv.sort_gaps(rs, "Score (high first)")] == ["g1", "g2"]
    assert [r["gap_id"] for r in gv.sort_gaps(rs, "Status (open first)")] == ["g1", "g2"]
    assert [r["gap_id"] for r in gv.sort_gaps(rs, "Most papers")] == ["g1", "g2"]
    flipped = [dict(r, rank=3 - r["rank"]) for r in rs]
    assert [r["gap_id"] for r in gv.sort_gaps(flipped, "Rank")] == ["g2", "g1"]


def test_ranks_missing_sort_last_and_unknown_sort_falls_back_to_rank():
    rs = [dict(r) for r in rows()]
    rs[0]["rank"] = None
    assert gv.sort_gaps(rs, "Rank")[-1]["gap_id"] == "g1"
    assert [r["gap_id"] for r in gv.sort_gaps(rows(), "no such sort")] == ["g1", "g2"]


def test_filtering_by_status_finder_paper_and_text():
    rs = rows()
    ids = lambda x: [r["gap_id"] for r in x]               # noqa: E731
    assert ids(gv.filter_gaps(rs, statuses=("partial",))) == ["g2"]
    assert ids(gv.filter_gaps(rs, finders=("Limitation miner",))) == ["g1"]
    assert ids(gv.filter_gaps(rs, paper="beta.pdf")) == ["g1", "g2"] or ids(gv.filter_gaps(rs, paper="Beta cohort study of drug X")) == ["g1", "g2"]
    assert ids(gv.filter_gaps(rs, paper="Alpha trial of drug X")) == ["g1"]
    assert ids(gv.filter_gaps(rs, query="single-centre")) == ["g2"]
    assert ids(gv.filter_gaps(rs, query="six months")) == []
    assert ids(gv.filter_gaps(rs, statuses=("open",), query="follow-up")) == ["g1"]


def test_proposal_rows_link_to_their_gap_and_carry_the_review():
    ps = gv.proposal_rows(golden_results())
    assert ps[0]["gap_title"] == "No long-term follow-up" and ps[0]["gap_rank"] == 1 and ps[0]["verdict"] == "accept"
    assert ps[1]["verdict"] == "" and ps[1]["key"] == "g2:1"


def test_compare_proposals_lists_each_field_side_by_side():
    a, b = gv.proposal_rows(golden_results())
    table = {r["field"]: r for r in gv.compare_proposals(a, b)}
    assert table["Confidence"] == {"field": "Confidence", "a": "high", "b": "medium"}
    assert table["Methodology"]["b"] == "Enrol three sites."
    assert table["Review verdict"]["b"] == "n/a"


# ── Gaps screen ─────────────────────────────────────────────────────────────────────────────
def _texts(at):
    return " ".join(str(getattr(e, "value", "")) for e in (*at.markdown, *at.caption, *at.info, *at.warning,
                                                            *at.success, *at.error))


def _open(app_test, name, results=None):
    seed_run(results or golden_results())
    at = app_test(timeout=90)
    at.session_state["result_tab"] = name
    return at.run()


def test_gaps_screen_shows_compact_cards_with_status_finder_score_and_paper_chips(app_test, isolated_env):
    at = _open(app_test, "Gaps")
    t = _texts(at)
    assert not at.exception
    assert "2 gaps · 1 open · 1 partial" in t
    assert "#1 No long-term follow-up" in t and "Limitation miner · 4.2/5" in t
    assert "Alpha trial of drug X" in t                      # paper chip
    assert "Showing 2 of 2" in t


def test_gap_details_link_to_closest_published_work(app_test, isolated_env):
    t = _texts(_open(app_test, "Gaps"))
    assert "[A related long-term study](https://doi.org/10.1/rel) (2020)" in t
    assert "A related paper without a link (2019) · no link" in t
    assert "Literature check:" in t and "No paper follows patients for two years." in t


def test_gap_filters_and_sort_change_what_is_listed(app_test, isolated_env):
    at = _open(app_test, "Gaps")
    at.multiselect(key="gap_status").select("partial").run()
    t = _texts(at)
    assert "Showing 1 of 2" in t and "Single-centre data" in t and "#1 No long-term follow-up" not in t
    at.multiselect(key="gap_status").unselect("partial").run()
    at.text_input(key="gap_query").set_value("nothing matches this").run()
    assert "Showing 0 of 2" in _texts(at)


def test_gap_screen_buttons_jump_to_the_evidence_filtered_by_citation(app_test, isolated_env):
    at = _open(app_test, "Gaps")
    at.button(key="gap_ev_0").click().run()
    assert at.session_state["result_tab"] == "Evidence" and at.session_state["ev_cited"] is True
    assert "of 3 items" in _texts(at) and "2 of 3 items" in _texts(at)


def test_gaps_text_is_escaped(app_test, isolated_env):
    r = golden_results()
    r["gaps"][0]["title"] = "p < 0.05 <script>x</script>"
    t = _texts(_open(app_test, "Gaps", r))
    assert "&lt;script&gt;" in t and "<script>" not in t


def test_empty_and_legacy_gap_lists_render(app_test, isolated_env):
    r = golden_results()
    r["gaps"] = []
    assert "no gaps" in _texts(_open(app_test, "Gaps", r)).lower()
    assert not _open(app_test, "Gaps", legacy_results()).exception


# ── Proposals screen ────────────────────────────────────────────────────────────────────────
def test_proposals_are_collapsible_with_a_gap_link_and_review(app_test, isolated_env):
    at = _open(app_test, "Proposals")
    assert not at.exception
    labels = [e.label for e in at.expander]
    assert any(l.startswith("#1 Two-year extension cohort · accept") for l in labels)
    assert any(l.startswith("#2 Multi-centre replication") for l in labels)
    t = _texts(at)
    assert "Addresses gap #1:** No long-term follow-up" in t or "Addresses gap #1:" in t
    assert "specificity 4" in t and "Annual spirometry" in t


def test_proposal_button_jumps_to_the_gaps(app_test, isolated_env):
    at = _open(app_test, "Proposals")
    at.button(key="prop_gap_0").click().run()
    assert at.session_state["result_tab"] == "Gaps"


def test_starring_a_proposal_stores_feedback_and_marks_it(app_test, isolated_env):
    import utils.database as db
    at = _open(app_test, "Proposals")
    at.button(key="star_0").click().run()
    saved = db.list_feedback(target_type="proposal")
    assert len(saved) == 1 and saved[0]["rating"] == 1 and saved[0]["target_label"] == "Two-year extension cohort"
    assert any(e.label.startswith("★ #1") for e in at.expander)
    at.button(key="star_0").click().run()                      # un-star
    assert db.list_feedback(target_type="proposal") == []


def test_two_proposals_can_be_compared(app_test, isolated_env):
    at = _open(app_test, "Proposals")
    at.multiselect(key="prop_compare").select(0).select(1).run()
    assert not at.exception
    df = at.dataframe[0].value
    assert "Enrol three sites." in df.to_string() and "Follow the cohort for two years." in df.to_string()


def test_proposals_screen_with_none_and_with_legacy(app_test, isolated_env):
    r = golden_results()
    r["proposals"] = []
    t = _texts(_open(app_test, "Proposals", r))
    assert "no proposals" in t.lower()
    assert not _open(app_test, "Proposals", legacy_results()).exception


# ── option: minimum gaps per paper ──────────────────────────────────────────────────────────
def test_minimum_gaps_per_paper_is_a_setting_a_wizard_option_and_reaches_the_run(app_test, isolated_env, monkeypatch):
    from tests.ui_helpers import open_settings, store_papers, wizard_to_review, click
    from pipeline import run_pipeline as rp
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 30)
    seen = {}

    def fake_run(papers, options, **kw):
        seen["min"] = options.min_gaps_per_paper
        raise rp.PipelineInputError("stop")
    monkeypatch.setattr(rp, "run_full_pipeline", fake_run)
    ids = store_papers(2)
    at = app_test(timeout=90)
    open_settings(at)
    at.number_input(key="set_mingaps").set_value(2).run()
    click(at, "settings_back")
    wizard_to_review(at, ids=ids)
    at.checkbox(key="wiz_bg").uncheck().run()
    click(at, "wiz_run")
    assert seen["min"] == 2
