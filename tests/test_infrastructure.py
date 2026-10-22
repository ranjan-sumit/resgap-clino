import pytest

import utils.database as db
from tests.fakes import FakeClient
from tests.fixtures.make_golden_run import golden_results, legacy_results, seed_run
from utils.azure_client import Failure, Success


def test_golden_fixture_has_three_papers_and_current_keys():
    r = golden_results()
    assert len(r["papers"]) == 3
    assert {"paper_profiles", "pipeline_trace", "supplementary_gaps"} <= set(r)


def test_legacy_fixture_lacks_new_keys():
    r = legacy_results()
    assert not {"paper_profiles", "pipeline_trace", "supplementary_gaps"} & set(r)
    assert r["gaps"]


def test_seeding_round_trips_and_isolated_env_is_separate(isolated_env):
    rid = seed_run()
    row = db.get_run_row(rid)
    assert row and row["name"] == "Golden run"
    assert str(isolated_env) in db._db_path()


def test_seeding_twice_gives_distinct_runs(isolated_env):
    assert seed_run() != seed_run()
    assert len(db.list_runs()) == 2


def test_legacy_run_seeds_without_error(isolated_env):
    assert db.get_run_row(seed_run(legacy_results(), name="legacy"))


def test_fake_client_scripts_success_failure_and_default():
    c = FakeClient(["hello", {"a": 1}, "!rate_limit"], default="done")
    assert c.chat("s", "u") == Success("hello")
    assert c.chat_json("s", "u") == Success('{"a": 1}')
    bad = c.chat("s", "u")
    assert isinstance(bad, Failure) and bad.error.kind == "rate_limit"
    assert c.chat("s", "u") == Success("done")
    assert len(c.calls) == 4


def test_fake_client_can_raise_and_records_stage():
    c = FakeClient([RuntimeError("boom")])
    c.set_stage("evidence")
    with pytest.raises(RuntimeError):
        c.chat("s", "u")
    assert c.calls[0]["stage"] == "evidence"


@pytest.mark.real
def test_real_marker_is_excluded_by_default():
    pytest.fail("tests marked 'real' must never run by default")


@pytest.mark.e2e
def test_e2e_marker_is_excluded_by_default():
    pytest.fail("tests marked 'e2e' must never run by default")
