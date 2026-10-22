import json
from unittest.mock import patch

import pytest

from pipeline import run_pipeline as rp
from tests.fakes import FakeClient
from tests.test_unreadable_pdfs import _text_pdf
from utils import database as db
from utils import project_store
from utils.azure_client import ErrorInfo, Failure, Success
from utils.call_log import CallLog
from utils.model_router import ModelRouter

KEY = "AIzaSyDUMMYDUMMYDUMMYDUMMYDUMMY12345"


def test_records_success_and_failure_with_hash_not_prompt():
    log = CallLog()
    log.record(stage="s", provider="p", model="m", method="chat", system="SECRET SYSTEM", user="u",
               started=0, ok=True, response_chars=5)
    log.record(stage="s", provider="p", model="m", method="chat", system="a", user="b", started=0,
               ok=False, error_kind="rate_limit", error_detail="429")
    text = log.to_jsonl()
    assert "SECRET SYSTEM" not in text and log.summary()["failed"] == 1
    assert all("prompt_sha256" in json.loads(line) for line in text.splitlines())


def test_keys_are_redacted_by_value_and_by_shape():
    log = CallLog(secrets=["my-custom-secret-value"])
    log.record(stage="s", provider="p", model="m", method="chat", system="", user="", started=0, ok=False,
               error_kind="api_error", error_detail=f"bad key my-custom-secret-value and {KEY} and nvapi-abcdefghijkl")
    out = log.to_jsonl()
    assert "my-custom-secret-value" not in out and KEY not in out and "nvapi-abcdefghijkl" not in out
    assert "[redacted]" in out


def test_log_is_capped():
    log = CallLog(max_records=3)
    for _ in range(10):
        log.record(stage="", provider="p", model="m", method="chat", system="", user="", started=0, ok=True)
    assert len(log.records) == 3 and "not logged" in log.to_jsonl()


def test_prompts_kept_only_when_enabled_and_still_redacted():
    log = CallLog(keep_prompts=True)
    log.record(stage="", provider="p", model="m", method="chat", system="sys", user=f"key {KEY}", started=0, ok=True)
    rec = json.loads(log.to_jsonl().splitlines()[0])
    assert rec["system"] == "sys" and KEY not in rec["user"]


def test_router_logs_failed_and_successful_calls():
    from utils.model_settings import recommend
    config = recommend({"gemini"})
    fake = FakeClient(["!rate_limit", "ok"])
    router = ModelRouter(config, {"gemini": KEY}, factory=lambda s, k, m: fake)
    router.call_log = CallLog(secrets=[KEY])
    router.set_stage("Stage 2 — LLM Wiki")
    router.chat("sys", "user")
    recs = router.call_log.records
    assert recs and recs[0]["ok"] is False and recs[0]["error_kind"] == "rate_limit"
    assert all(r["stage"] == "Stage 2 — LLM Wiki" for r in recs)


def _opts():
    return rp.RunOptions(provider_key="x", model="m")


def test_failed_run_still_writes_the_call_log(isolated_env):
    from utils.model_settings import recommend
    fake = FakeClient(["!api_error"] * 5)
    router = ModelRouter(recommend({"gemini"}), {"gemini": KEY}, factory=lambda s, k, m: fake)

    def boom(papers, trees, client, domain_config=None):
        client.set_stage("Stage 2 — LLM Wiki")
        client.chat("s", "u")
        raise RuntimeError("stage 2 died")

    with patch("pipeline.run_pipeline.build_wiki", side_effect=boom):
        with pytest.raises(RuntimeError):
            rp.run_full_pipeline([("a.pdf", _text_pdf("a")), ("b.pdf", _text_pdf("b"))], {}, router, _opts())
    folder = project_store.project_dir(db.DEFAULT_PROJECT_ID) / "runs" / "_failed"
    logs = list(folder.glob("*-llm_calls.jsonl"))
    assert logs and "api_error" in logs[0].read_text(encoding="utf-8")
    assert "stage 2 died" in next(folder.glob("*-error.txt")).read_text(encoding="utf-8")
    assert KEY not in logs[0].read_text(encoding="utf-8")


def test_write_run_artifacts_stores_the_log_and_manifest_errors(isolated_env):
    rid = db.save_run("t", {"context": {}, "gaps": [], "proposals": [], "papers": []})
    project_store.write_run_artifacts(
        db.DEFAULT_PROJECT_ID, rid, {"context": {}}, {}, make_reports=False,
        manifest={"llm_call_errors": [{"error_kind": "timeout"}]},
        call_log_jsonl='{"ok": false}\n')
    base = project_store.project_dir(db.DEFAULT_PROJECT_ID) / "runs" / rid
    assert (base / "llm_calls.jsonl").read_text() == '{"ok": false}\n'
    assert json.loads((base / "manifest.json").read_text())["llm_call_errors"][0]["error_kind"] == "timeout"
