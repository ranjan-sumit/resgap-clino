import re
from pathlib import Path

from tests.fixtures.make_golden_run import golden_results, legacy_results, seed_run
from ui import viewmodels as vm

ROOT = Path(__file__).resolve().parent.parent
_LEGACY_ARG = "use_container" + "_width"


# ── view-models ────────────────────────────────────────────────────────────────
def test_run_header_chips_for_golden_run():
    h = vm.run_header({"name": "g", "created_at": "2026-10-22T10:00:00", "n_papers": 3, "n_gaps": 2}, "",
                      golden_results(), {"run_duration_seconds": 372})
    assert "Completed with warnings" in h["chips"] and "gemini-3.5-flash-lite" in h["chips"]
    assert "6 min 12 s" in h["chips"]


def test_run_header_chips_for_legacy_run_omit_missing_fields():
    h = vm.run_header({"name": "l", "created_at": "", "n_papers": 3, "n_gaps": 2}, "", legacy_results(), None)
    assert h["chips"] == ["No stage trace"]


def test_keys_line_reports_both_states():
    assert "Semantic Scholar: key set" in vm.keys_line(["Google Gemini"], True)
    assert "no key" in vm.keys_line(["Google Gemini"], False)
    assert "No API keys found" in vm.keys_line([], False)


def test_off_note_only_when_references_did_not_run():
    assert vm.off_note({}) is not None
    assert vm.off_note({"ref_diagnostics": {"raw_entries": 3}}) is None


def test_saved_trace_prefers_the_live_session_trace():
    saved = {"pipeline_trace": [{"stage": "a"}]}
    assert vm.saved_trace(saved, [{"stage": "live"}]) == [{"stage": "live"}]
    assert vm.saved_trace(saved, []) == [{"stage": "a"}]
    assert vm.saved_trace({}, None) == []


def test_trace_summary_reads_models_fallbacks_and_tokens():
    res = golden_results()
    res["model_fallbacks"] = [{"stage": "s", "from": "a", "to": "b"}]
    s = vm.trace_summary(res, {"token_usage": {"total": 1200, "by_stage": {"Stage 2": 1200}}})
    assert s["models"] == {"extraction": "gemini-3.5-flash-lite"}
    assert s["fallback_count"] == 1 and s["tokens_total"] == 1200
    assert vm.trace_summary(legacy_results()) == {}


# ── screens ──────────────────────────────────────────────────────────────────
def _texts(at):
    return " ".join(str(getattr(e, "value", "")) for e in (*at.markdown, *at.caption, *at.info, *at.warning))


def test_trace_tab_shows_the_stored_trace_for_a_saved_run(app_test, isolated_env):
    seed_run(golden_results())
    at = app_test(timeout=90)
    text = _texts(at)
    assert "STAGE 1" in text and "PDF Parse" in text
    assert "Run the main analysis to see the pipeline trace" not in text


def test_trace_tab_says_so_for_a_legacy_run(app_test, isolated_env):
    seed_run(legacy_results())
    text = _texts(app_test(timeout=90))
    assert "no stage trace stored" in text and "Run the main analysis" not in text


def test_hero_is_shown_only_for_an_empty_project(app_test, isolated_env):
    assert 'class="hero-h1"' in _texts(app_test(timeout=90))
    seed_run(golden_results())
    assert 'class="hero-h1"' not in _texts(app_test(timeout=90))


def test_hero_copy_names_the_real_sources(app_test, isolated_env):
    assert "Europe PMC" in _texts(app_test(timeout=90))


def test_no_off_cards_when_references_were_not_fetched(app_test, isolated_env):
    seed_run(golden_results() | {"corpus_stats": {"tier1": 3}})
    text = _texts(app_test(timeout=90))
    assert ">Off<" not in text and "were not fetched for this run" in text


def test_the_form_is_not_on_the_results_page_any_more(app_test, isolated_env):
    seed_run(golden_results())
    at = app_test(timeout=90)
    assert not [e for e in at.expander if e.label == "New analysis"]
    assert not at.file_uploader                        # uploading happens in the New analysis form


# ── deprecation ────────────────────────────────────────────────────────────────
def test_no_deprecated_container_width_argument_is_left():
    offenders = []
    for path in list(ROOT.glob("*.py")) + list((ROOT / "ui").glob("*.py")) + list((ROOT / "pipeline").glob("*.py")) \
            + list((ROOT / "utils").glob("*.py")):
        if re.search(_LEGACY_ARG, path.read_text(encoding="utf-8")) and path.name != "compat.py":
            offenders.append(path.name)
    assert offenders == []
