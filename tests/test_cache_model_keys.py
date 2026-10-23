"""PR-02a: a cached result belongs to the model that produced it."""
import json

from pipeline.evidence_extractor import EVIDENCE_STAGE_VERSION
from pipeline.literature_scout import SCOUT_STAGE_VERSION
from pipeline.page_index import build_tree
from pipeline.param_extractor import PARAM_STAGE_VERSION
from pipeline.wiki_compiler import WIKI_STAGE_VERSION, compile_wiki_page
from tests.fakes import FakeClient
from utils import cache_tag
from utils.call_log import CallLog
from utils.database import compute_cache_key
from utils.model_router import ModelRouter

KEY = "AIzaSyDUMMYDUMMYDUMMYDUMMYDUMMY12345"
WIKI = {"title": "A paper", "contributions": ["x"], "year": "2024", "key_concepts": ["y"]}


class TaggedClient(FakeClient):
    def __init__(self, tag, **kw):
        super().__init__(**kw)
        self._tag = tag

    def cache_tag(self):
        return self._tag


def _paper():
    text = "Some paper full text about a novel method. " * 5
    return {"filename": "p.pdf", "full_text": text, "char_count": len(text), "sections": {}}


def test_the_same_input_under_two_models_gives_two_different_keys():
    a = compute_cache_key("text", None, [], 1, model_tag="gemini:flash")
    b = compute_cache_key("text", None, [], 1, model_tag="nvidia:gpt-oss")
    again = compute_cache_key("text", None, [], 1, model_tag="gemini:flash")
    assert a[0] != b[0] and a[0] == again[0] and a[1] == b[1]          # same content hash, different entries


def test_without_a_tag_the_key_keeps_its_old_shape():
    key = compute_cache_key("text", None, [], 3)[0]
    assert key.count(":") == 2 and key.endswith(":3")


def test_clients_that_cannot_name_a_model_give_an_empty_tag():
    from unittest.mock import MagicMock
    assert cache_tag.model_tag(FakeClient()) == ""
    assert cache_tag.model_tag(MagicMock()) == ""                       # a mock's reply is not a stable string
    assert cache_tag.suffix("") == ""


def test_a_wiki_page_is_recomputed_when_the_model_changes_and_reused_when_it_does_not(isolated_env):
    paper, tree = _paper(), build_tree(_paper())
    one = TaggedClient("gemini:flash", default=json.dumps(WIKI))
    two = TaggedClient("nvidia:gpt-oss", default=json.dumps(WIKI))
    compile_wiki_page(paper, tree, one)
    compile_wiki_page(paper, tree, one)
    assert len(one.calls) == 1                                          # same model: served from saved results
    compile_wiki_page(paper, tree, two)
    assert len(two.calls) == 1                                          # another model: computed afresh


def test_the_router_names_the_model_for_the_current_stage_and_follows_a_change():
    from utils.model_settings import recommend
    config = recommend({"gemini"})
    router = ModelRouter(config, {"gemini": KEY}, factory=lambda s, k, m: FakeClient())
    router.set_stage("Stage 2 — LLM Wiki")
    tag = router.cache_tag()
    assert tag.startswith("gemini:") and tag == cache_tag.model_tag(router)
    other = ModelRouter(recommend({"gemini"}), {"gemini": KEY}, factory=lambda s, k, m: FakeClient())
    other.config.roles["wiki"] = type(config.roles["wiki"])("gemini", "some-other-model")
    other.set_stage("Stage 2 — LLM Wiki")
    assert other.cache_tag() != tag


def test_stage_versions_were_bumped_so_old_untagged_entries_are_not_served():
    assert WIKI_STAGE_VERSION >= 4 and EVIDENCE_STAGE_VERSION >= 6
    assert PARAM_STAGE_VERSION >= 4 and SCOUT_STAGE_VERSION >= 6


def test_the_call_log_names_the_models_that_really_answered_including_a_fallback():
    log = CallLog()
    log.record(stage="s", provider="nvidia", model="gpt-oss", method="chat", system="", user="", started=0, ok=False,
               error_kind="timeout")
    log.record(stage="s", provider="gemini", model="flash", method="chat", system="", user="", started=0, ok=True)
    log.record(stage="s", provider="gemini", model="flash", method="chat", system="", user="", started=0, ok=True)
    assert log.models_used() == {"nvidia:gpt-oss": {"calls": 1, "ok": 0}, "gemini:flash": {"calls": 2, "ok": 2}}


def test_the_manifest_records_the_models_that_answered():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "pipeline" / "run_pipeline.py").read_text(encoding="utf-8")
    assert '"models_that_answered": _audit["call_log"].models_used()' in src
