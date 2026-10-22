import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline import agent_config
from pipeline import run_pipeline as rp
from pipeline.run_quality import compute_run_quality
from tests.fakes import FakeClient
from tests.fixtures.make_golden_run import golden_results
from tests.test_unreadable_pdfs import _text_pdf
from utils import cost_guard as cg
from utils.model_router import ModelRouter
from utils.model_settings import recommend

ROOT = Path(__file__).resolve().parent.parent


# ── estimate and cost ───────────────────────────────────────────────────────
def test_estimate_scales_with_paper_text_and_options():
    small = cg.estimate_run([40_000, 40_000])
    big = cg.estimate_run([200_000, 200_000])
    assert big["tokens"] > 3 * small["tokens"] and small["low"] < small["tokens"] < small["high"]
    assert cg.estimate_run([40_000], extract_refs=True)["tokens"] > cg.estimate_run([40_000])["tokens"]


def test_estimate_matches_the_calibration_run_within_its_range():
    # 3 papers of ~55,000 characters used about 170,000 recorded tokens in the real run
    est = cg.estimate_run([55_000] * 3)
    assert est["low"] <= 170_000 <= est["high"]


def test_cost_is_none_without_a_price_and_computed_with_one():
    assert cg.estimate_cost(1_000_000, "gemini", "m", prices={}) is None
    assert cg.estimate_cost(1_000_000, "gemini", "m", prices={"gemini/m": (1.0, 5.0)}) == pytest.approx(2.0)


def test_describe_estimate_warns_when_the_range_exceeds_the_cap():
    est = {"tokens": 500_000, "low": 350_000, "high": 850_000}
    assert "exceeds your cap" in cg.describe_estimate(est, 600_000)
    assert "exceeds" not in cg.describe_estimate(est, 2_000_000)
    assert "no price set" in cg.describe_estimate(est, 2_000_000, None)


# ── the cap ─────────────────────────────────────────────────────────────────
def test_budget_warns_once_near_the_cap_then_refuses():
    warnings = []
    b = cg.TokenBudget(1000, on_warn=warnings.append)
    b.add(700); b.check()
    assert warnings == []
    b.add(150); b.add(10)
    assert len(warnings) == 1 and "1,000" in warnings[0]
    b.add(200)
    with pytest.raises(cg.BudgetExceededError):
        b.check()


def test_no_cap_means_no_limit():
    b = cg.TokenBudget(None)
    b.add(10**9)
    b.check()


def _router(fake):
    return ModelRouter(recommend({"gemini"}), {"gemini": "k" * 12}, factory=lambda s, k, m: fake)


def test_router_counts_tokens_and_refuses_calls_over_the_cap():
    fake = FakeClient(default="x" * 4000)                        # ~1000 reply tokens each
    router = _router(fake)
    router.budget = cg.TokenBudget(1500)
    router.set_stage("Stage 2 — LLM Wiki")
    router.chat("s", "u")
    router.chat("s", "u")
    assert router.budget.used >= 1500
    calls_before = len(fake.calls)
    with pytest.raises(cg.BudgetExceededError):
        router.chat("s", "u")
    assert len(fake.calls) == calls_before                        # no further spend


def test_a_run_over_its_cap_stops_cleanly_with_a_message(isolated_env):
    fake = FakeClient(default="x" * 40_000)
    router = _router(fake)

    def wiki(papers, trees, client, domain_config=None):
        client.set_stage("Stage 2 — LLM Wiki")
        client.chat("s", "u")                                    # ~10,000 tokens: over the 5,000 cap
        return {"pages": [], "cross_links": {}, "index": {}, "warnings": []}

    with patch("pipeline.run_pipeline.build_wiki", side_effect=wiki):
        with pytest.raises(cg.BudgetExceededError) as e:
            rp.run_full_pipeline([("a.pdf", _text_pdf("a")), ("b.pdf", _text_pdf("b"))], {}, router,
                                 rp.RunOptions(provider_key="x", model="m", token_cap=5000))
    assert "token cap" in str(e.value) and "5,000" in str(e.value)


def test_budget_error_is_reported_without_a_traceback_in_background_jobs(isolated_env):
    import time
    from types import SimpleNamespace
    from utils import run_jobs

    def runner(**kw):
        raise cg.BudgetExceededError(2_100_000, 2_000_000)

    job_id = run_jobs.start_job(papers=[], context={}, client=None,
                                options=SimpleNamespace(project_id="default"), runner=runner)
    end = time.time() + 5
    while time.time() < end and run_jobs.get_job(job_id)["status"] != "failed":
        time.sleep(0.05)
    job = run_jobs.get_job(job_id)
    assert job["status"] == "failed" and "token cap" in job["error"] and "Traceback" not in job["error"]


# ── quality metrics ─────────────────────────────────────────────────────────
def _with_evidence(quoted, unquoted):
    r = golden_results()
    ev = [{"provenance": {"quote": "q"}}] * quoted + [{"provenance": {}}] * unquoted
    r["evidence_objects"] = {"alpha.pdf": ev, "beta.pdf": [], "gamma.pdf": []}
    return r


def test_quote_rate_is_the_share_of_evidence_with_a_quote():
    assert compute_run_quality(_with_evidence(9, 1))["quote_rate"] == 0.9
    assert compute_run_quality(_with_evidence(0, 0))["quote_rate"] is None       # nothing to measure


def test_unsupported_number_and_duplicate_rates():
    r = golden_results()
    r["gaps"] = [{"title": "No long term follow up in trials", "unsupported_numbers": ["45%"]},
                 {"title": "No long-term follow-up in trials"},
                 {"title": "Single centre data only"}]
    r["proposals"] = []
    q = compute_run_quality(r)
    assert q["unsupported_number_rate"] == round(1 / 3, 3)
    assert q["duplicate_gap_rate"] == round(1 / 3, 3)


def test_paper_coverage_counts_papers_with_status_ok():
    q = compute_run_quality(golden_results(), duration_seconds=12.5, call_summary={"calls": 7, "failed": 1},
                            tokens_estimated=999)
    assert q["paper_coverage"] == 0.0                      # the synthetic papers have empty wiki pages
    assert (q["llm_calls"], q["llm_calls_failed"], q["duration_seconds"], q["tokens_estimated"]) == (7, 1, 12.5, 999)


# ── agent versions ──────────────────────────────────────────────────────────
def test_every_agent_is_listed_with_a_version_and_hash():
    versions = agent_config.agent_versions()
    roles = {cfg.role for cfg in agent_config.all_agent_configs().values()}
    assert set(versions) == roles and {"Evidence Reader", "Gap Finder", "Methodology Critic",
                                       "Proposal Reviewer"} <= roles
    assert all(v["prompt_version"] and len(v["config_hash"]) == 10 for v in versions.values())


def test_changing_a_limit_changes_the_config_hash():
    from dataclasses import replace
    before = agent_config.agent_versions()["Gap Finder"]["config_hash"]
    cfg = agent_config.GAP_FINDER
    with patch.dict(agent_config.__dict__, {"GAP_FINDER": replace(cfg, max_tokens=cfg.max_tokens + 1)}):
        assert agent_config.agent_versions()["Gap Finder"]["config_hash"] != before
    assert agent_config.agent_versions()["Gap Finder"]["config_hash"] == before


def test_agents_carry_no_stale_model_label():
    assert not any(hasattr(cfg, "model") for cfg in agent_config.all_agent_configs().values())


# ── golden eval ─────────────────────────────────────────────────────────────
def _run_eval(tmp_path, results):
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"results": results}))
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "golden_eval.py"), "--file", str(f)],
                          capture_output=True, text=True)


def test_golden_eval_passes_on_good_quality_and_fails_when_the_quote_rate_drops(tmp_path):
    good = {"run_quality": {"quote_rate": 0.98, "paper_coverage": 1.0, "unsupported_number_rate": 0.0,
                            "duplicate_gap_rate": 0.0}}
    ok = _run_eval(tmp_path, good)
    assert ok.returncode == 0 and "PASS" in ok.stdout, ok.stdout + ok.stderr
    bad = {"run_quality": {**good["run_quality"], "quote_rate": 0.4}}
    res = _run_eval(tmp_path, bad)
    assert res.returncode == 1 and "quote_rate" in res.stdout


def test_golden_eval_reports_but_does_not_fail_an_unmeasurable_metric(tmp_path):
    res = _run_eval(tmp_path, {"run_quality": {"quote_rate": None, "paper_coverage": 1.0}})
    assert res.returncode == 0


def test_golden_eval_recomputes_quality_for_runs_saved_without_it(tmp_path):
    r = _with_evidence(0, 10)                      # ten pieces of evidence, none quoted
    res = _run_eval(tmp_path, r)
    assert res.returncode == 1 and "quote_rate = 0.0" in res.stdout
