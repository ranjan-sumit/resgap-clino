from tests.fixtures.make_golden_run import golden_comp, golden_results, seed_run
from ui import lab_view as lv


def test_verdict_for_a_skipped_simulation_names_the_reason_and_the_set_aside_parameters():
    v = lv.lab_verdict(golden_comp())
    assert v["state"] == "skipped" and "not contain enough usable numbers" in v["headline"]
    assert any("only 1 usable numeric" in r for r in v["reasons"])
    assert any("1 parameter(s) are opinions" in r for r in v["reasons"])
    assert any("1 parameter(s) have impossible values" in r for r in v["reasons"])
    assert (v["measured"], v["opinion"], v["flagged"], v["coverage"]) == (1, 1, 1, 3)


def test_verdict_for_a_simulation_lists_what_ran_and_what_was_refused():
    v = lv.lab_verdict(golden_comp(simulated=True))
    assert v["state"] == "simulated" and "1 algorithm(s)" in v["headline"]
    assert [a for a in v["algorithms"] if a["state"] == "ran"][0]["name"] == "Tornado sensitivity"
    refused = [a for a in v["algorithms"] if a["state"] == "refused"][0]
    assert refused["name"] == "Markov chain" and "transition probabilities" in refused["reason"]


def test_verdict_when_every_algorithm_is_refused():
    cr = golden_comp(simulated=True)
    cr["sim_results"]["models_run"] = []
    assert "nothing was simulated" in lv.lab_verdict(cr)["headline"]


def test_parameters_per_paper_split_measured_opinion_and_impossible():
    rows = {r["paper"]: r for r in lv.parameters_by_paper(golden_comp(), golden_results()["papers"])}
    assert rows["alpha.pdf"] == {"paper": "alpha.pdf", "total": 1, "measured": 1, "opinion": 0, "flagged": 0}
    assert rows["beta.pdf"]["flagged"] == 1 and rows["gamma.pdf"]["opinion"] == 1


def test_a_paper_without_parameters_shows_zero():
    cr = golden_comp()
    cr["params"] = [p for p in cr["params"] if p["source_file"] != "alpha.pdf"]
    assert {r["paper"]: r["total"] for r in lv.parameters_by_paper(cr, golden_results()["papers"])}["alpha.pdf"] == 0


def test_kind_badges():
    assert lv.kind_badge({"evidence_kind": "opinion"}) == "opinion"
    assert lv.kind_badge({"sanity_issues": ["x"]}) == "impossible value"
    assert lv.kind_badge({}) == ""


def _texts(at):
    return " ".join(str(getattr(e, "value", "")) for e in (*at.markdown, *at.caption, *at.info, *at.warning, *at.success))


def _open(app_test, comp):
    seed_run(golden_results(), comp_results=comp)
    at = app_test(timeout=90)
    at.session_state["result_tab"] = "Lab"
    return at.run()


def test_lab_screen_leads_with_the_verdict_then_the_per_paper_table(app_test, isolated_env):
    at = _open(app_test, golden_comp())
    assert not at.exception, [e.value for e in at.exception]
    t = _texts(at)
    assert t.index("Not simulated") < t.index("Data Availability")
    assert "1 parameter(s) are opinions" in t
    df = at.dataframe[0].value
    assert list(df["Paper"]) == ["alpha.pdf", "beta.pdf", "gamma.pdf"] and list(df["Opinions"]) == [0, 0, 1]


def test_lab_screen_shows_refused_algorithms_with_their_reason(app_test, isolated_env):
    at = _open(app_test, golden_comp(simulated=True))
    assert not at.exception
    t = _texts(at)
    assert "Simulated" in t and "Simulation run with 1 algorithm(s)" in t
    assert any(e.label == "Algorithms: what ran and what was refused" for e in at.expander)
    assert "Markov chain** refused" in t and "transition probabilities" in t


def test_lab_screen_without_lab_results_still_renders(app_test, isolated_env):
    assert not _open(app_test, None).exception
