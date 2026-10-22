import time

import pytest

from tests.fixtures.make_golden_run import golden_results, legacy_results, seed_run
from ui import evidence_view as ev


# ── view-models (pure) ──────────────────────────────────────────────────────────────────────
def test_rows_carry_citation_data_and_the_gaps_that_cite_them():
    rows = {r["id"]: r for r in ev.evidence_rows(golden_results())}
    assert len(rows) == 3
    assert rows["e1"]["page"] == 4 and rows["e1"]["quote"] == "Follow-up was 3 months."
    assert rows["e1"]["cited_by"] == [{"title": "No long-term follow-up", "rank": 1}]
    assert rows["e2"]["cited_by"] == [] and rows["e2"]["page"] is None
    assert rows["e1"]["paper_title"] == "Alpha trial of drug X"


def test_motivating_ids_stored_as_a_repr_string_are_still_read():
    r = golden_results()
    r["gaps"][0]["motivating_evidence_ids"] = "['e1', 'e3']"
    assert set(ev.reverse_index(r)) == {"e1", "e3"}
    r["gaps"][0]["motivating_evidence_ids"] = "garbage"
    assert ev.reverse_index(r) == {}


def test_filters_by_paper_type_page_quote_citation_and_text():
    rows = ev.evidence_rows(golden_results())
    ids = lambda rs: sorted(r["id"] for r in rs)       # noqa: E731
    assert ids(ev.filter_evidence(rows, paper="beta.pdf")) == ["e3"]
    assert ids(ev.filter_evidence(rows, types=("Limitation", "Result"))) == ["e1", "e2"]
    assert ids(ev.filter_evidence(rows, has_page=True)) == ["e1", "e3"]
    assert ids(ev.filter_evidence(rows, has_page=False)) == ["e2"]
    assert ids(ev.filter_evidence(rows, has_quote=False)) == ["e2"]
    assert ids(ev.filter_evidence(rows, cited_only=True)) == ["e1", "e3"]
    assert ids(ev.filter_evidence(rows, query="LUNG function")) == ["e2"]
    assert ids(ev.filter_evidence(rows, query="three months")) == ["e1"]
    assert ids(ev.filter_evidence(rows, paper="alpha.pdf", cited_only=True)) == ["e1"]
    assert ev.filter_evidence(rows, paper="gamma.pdf") == []


def test_wiki_facts_link_to_the_evidence_that_states_them():
    rows = [r for r in ev.evidence_rows(golden_results()) if r["paper"] == "alpha.pdf"]
    hit = ev.match_evidence("Follow-up limited to three months", rows)
    assert hit and hit["id"] == "e1"
    assert ev.match_evidence("Entirely unrelated statement about genomics", rows) is None
    assert ev.match_evidence("", rows) is None


def test_citation_omits_what_is_unknown():
    assert ev.citation({"page": 4, "section": "Discussion"}) == "p.4 · Discussion"
    assert ev.citation({"page": None, "section": "Results"}) == "Results"
    assert ev.citation({"page": None, "section": None}) == ""


def test_top_gaps_are_ordered_by_rank_and_proposal_skips_rejected():
    r = golden_results()
    r["gaps"] = [dict(r["gaps"][1], rank=2), dict(r["gaps"][0], rank=1)]
    assert [g["rank"] for g in ev.top_gaps(r)] == [1, 2]
    r["proposals"] = [{"title": "bad", "review": {"verdict": "reject"}}, {"title": "good"}]
    assert ev.top_proposal(r)["title"] == "good"
    assert ev.top_proposal({}) is None


def test_warnings_summary_lists_trace_warnings_coverage_and_flags():
    r = golden_results()
    r["gaps"][0]["unsupported_numbers"] = ["45%"]
    r["model_fallbacks"] = [{"stage": "s"}]
    r["run_quality"] = {"quote_rate": 0.5}
    text = " | ".join(ev.warnings_summary(r))
    assert "Stage 2 — LLM Wiki" in text                       # the ⚠️ trace row
    assert "empty wiki page" in text                          # coverage problem
    assert "numbers not found" in text and "fallback model" in text and "50%" in text
    assert ev.warnings_summary({"gaps": [], "papers": [], "pipeline_trace": []}) == []


def test_quality_chips_only_state_measured_values():
    assert ev.quality_chips({"run_quality": {"quote_rate": 0.984, "paper_coverage": None}}) == ["98% of evidence quoted"]
    assert ev.quality_chips({}) == []


# ── screens ─────────────────────────────────────────────────────────────────────────────────
def _texts(at):
    return " ".join(str(getattr(e, "value", "")) for e in (*at.markdown, *at.caption, *at.info, *at.warning,
                                                            *at.success, *at.error))


def _open(app_test, name, results=None):
    seed_run(results or golden_results())
    at = app_test(timeout=90)
    at.session_state["result_tab"] = name
    return at.run()


def test_overview_shows_numbers_top_gaps_proposal_and_warnings(app_test, isolated_env):
    at = app_test_open = _open(app_test, "Overview")
    t = _texts(at)
    assert "Papers Analysed" in t and "Top gaps" in t and "No long-term follow-up" in t
    assert "Leading proposal" in t and "Two-year extension cohort" in t
    assert any("thing(s) to know" in e.label for e in at.expander)


def test_overview_shows_the_coverage_table(app_test, isolated_env):
    at = _open(app_test, "Overview")
    assert any(e.label.startswith("Paper coverage") for e in at.expander)


def test_overview_buttons_jump_to_gaps_and_proposals(app_test, isolated_env):
    at = _open(app_test, "Overview")
    at.button(key="ov_all_gaps").click().run()
    assert at.session_state["result_tab"] == "Gaps"
    at.session_state["result_tab"] = "Overview"
    at.run()
    at.button(key="ov_all_props").click().run()
    assert at.session_state["result_tab"] == "Proposals"


def test_evidence_screen_lists_items_with_quotes_pages_and_citing_gaps(app_test, isolated_env):
    t = _texts(_open(app_test, "Evidence"))
    assert "3 of 3 items" in t
    assert "Follow-up was 3 months." in t and "p.4 · Discussion" in t
    assert "Cited by: #1 No long-term follow-up" in t
    assert "no verified quote" in t


def test_evidence_filters_narrow_the_list(app_test, isolated_env):
    at = _open(app_test, "Evidence")
    at.selectbox(key="ev_paper").select("beta.pdf").run()
    assert "1 of 3 items" in _texts(at)
    at.selectbox(key="ev_paper").select("All papers").run()
    at.checkbox(key="ev_page").check().run()
    assert "2 of 3 items" in _texts(at)
    at.text_input(key="ev_query").set_value("80 patients").run()
    assert "1 of 3 items" in _texts(at) and "A single-centre cohort" in _texts(at)


def test_evidence_screen_says_so_for_a_run_without_evidence(app_test, isolated_env):
    r = golden_results()
    r["evidence_objects"] = {}
    assert "No stored evidence" in _texts(_open(app_test, "Evidence", r))


def test_evidence_text_is_escaped(app_test, isolated_env):
    r = golden_results()
    r["evidence_objects"]["alpha.pdf"][0]["text"] = "p < 0.05 <script>alert(1)</script>"
    t = _texts(_open(app_test, "Evidence", r))
    assert "&lt;script&gt;" in t and "<script>" not in t


def test_wiki_shows_study_type_and_links_facts_to_quotes(app_test, isolated_env):
    r = golden_results()
    r["papers"][0]["wiki"] = {"title": "Alpha trial of drug X",
                              "limitations": ["Follow-up limited to three months"], "contributions": [], "methods": [],
                              "future_work": []}
    at = _open(app_test, "Wiki", r)
    t = _texts(at)
    assert "Study type: rct · 2 evidence item(s)" in t
    assert "p.4 · Discussion · “Follow-up was 3 months.”" in t


def test_only_the_open_section_is_built(app_test, isolated_env):
    """Wiki/Gaps/Graph and the rest cost nothing until opened."""
    seed_run(golden_results())
    at = app_test(timeout=90)
    t = _texts(at)
    assert "Top gaps" in t                                  # Overview is built
    assert "Compiled Wiki Pages" not in t and "Reference Corpus" not in t     # others are not
    assert "Export Results" not in t


def test_overview_renders_a_big_run_quickly(app_test, isolated_env):
    r = golden_results()
    r["evidence_objects"]["alpha.pdf"] = [
        {"evidence_id": f"x{i}", "evidence_type": "Result", "paper_id": "alpha.pdf", "confidence": "high",
         "text": f"finding number {i} " * 5, "provenance": {"page": i % 30 + 1, "section": "Results", "quote": f"quote {i}"}}
        for i in range(2000)]
    seed_run(r)
    start = time.time()
    at = app_test(timeout=90)
    assert not at.exception
    assert time.time() - start < 20


def test_evidence_screen_caps_how_much_it_draws(app_test, isolated_env):
    r = golden_results()
    r["evidence_objects"]["alpha.pdf"] = [
        {"evidence_id": f"x{i}", "evidence_type": "Result", "paper_id": "alpha.pdf", "confidence": "high",
         "text": f"finding {i}", "provenance": {"page": 1, "section": "R", "quote": "q"}} for i in range(500)]
    t = _texts(_open(app_test, "Evidence", r))
    assert "501 of 501 items" in t and "Showing the first 60 of 501" in t


def test_legacy_run_overview_and_evidence_do_not_crash(app_test, isolated_env):
    for name in ("Overview", "Evidence", "Wiki"):
        assert not _open(app_test, name, legacy_results()).exception
