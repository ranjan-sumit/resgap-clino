import pytest

from tests.fixtures.make_golden_run import golden_results, legacy_results, seed_run

SECTIONS = ["Overview", "Evidence", "Wiki", "References", "Graph", "Gaps", "Proposals", "Lab", "Trace", "Export"]


def _load(app_test, results, name):
    seed_run(results, name=name)
    return app_test(timeout=90)


def test_golden_run_opens_on_the_overview(app_test, isolated_env):
    at = _load(app_test, golden_results(), "golden")
    assert not at.exception
    assert at.session_state["result_tab"] == "Overview"
    assert not at.tabs                                   # sections are a selector now, not st.tabs


@pytest.mark.parametrize("results_fn", [golden_results, legacy_results])
@pytest.mark.parametrize("section", SECTIONS)
def test_every_section_renders_for_golden_and_legacy_runs(app_test, isolated_env, results_fn, section):
    at = _load(app_test, results_fn(), "run")
    at.session_state["result_tab"] = section
    at.run()
    assert not at.exception, [e.value for e in at.exception]