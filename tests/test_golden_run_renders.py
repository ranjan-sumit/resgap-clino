from tests.fixtures.make_golden_run import golden_results, legacy_results, seed_run


def _load(app_test, results, name):
    seed_run(results, name=name)
    return app_test(timeout=90)


def test_golden_run_renders_all_tabs_without_error(app_test, isolated_env):
    at = _load(app_test, golden_results(), "golden")
    assert not at.exception
    assert len(at.tabs) == 8 and "Pipeline Trace" in at.tabs[6].label


def test_legacy_run_renders_without_error(app_test, isolated_env):
    at = _load(app_test, legacy_results(), "legacy")
    assert not at.exception
