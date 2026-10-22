import ast
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.fixtures.make_golden_run import golden_results, seed_run
from ui import components as comp
from ui import messages as msg

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "app.py").read_text(encoding="utf-8")


# ── friendly hints ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,fragment", [
    ("Request timed out after 300 s", "took too long"),
    ("Error code: 429 - quota exceeded", "rate limit or quota"),
    ("RESOURCE_EXHAUSTED", "rate limit or quota"),
    ("401 Unauthorized: invalid API key", "did not accept the API key"),
    ("Connection error: name or service not known", "could not be reached"),
    ("JSONDecodeError: Expecting value", "could not be read"),
    ("sqlite3.OperationalError: database is locked", "database was busy"),
    ("[Errno 2] No such file or directory", "file could not be accessed"),
    ("model gpt-x does not exist", "not available for your key"),
])
def test_recognised_causes_get_a_plain_next_step(text, fragment):
    assert fragment in msg.hint_for(text)


def test_unrecognised_text_gets_no_invented_hint():
    assert msg.hint_for("something odd happened") == "" and msg.hint_for("") == ""


def test_a_warning_sign_is_not_doubled_up():
    assert msg.clean("⚠️ Careful") == "Careful" and msg.clean("❌  Failed") == "Failed" and msg.clean("plain") == "plain"


class _Spy:
    def __init__(self):
        self.calls = []

    def error(self, text): self.calls.append(("error", text))
    def warning(self, text): self.calls.append(("warning", text))
    def info(self, text): self.calls.append(("info", text))
    def expander(self, label):
        self.calls.append(("expander", label))
        import contextlib
        return contextlib.nullcontext()
    def code(self, text, language=None): self.calls.append(("code", text))


def _spied(fn, *a, **k):
    spy = _Spy()
    with patch.object(msg, "st", spy):
        fn(*a, **k)
    return spy.calls


def test_an_exception_becomes_a_sentence_plus_a_next_step_with_the_raw_text_behind_details():
    calls = _spied(msg.show_error, "The report could not be generated", exc=TimeoutError("request timed out"))
    assert calls[0] == ("error", "The report could not be generated. The model took too long to answer. Try again; "
                                 "if it keeps happening, choose a faster model in Settings → Models.")
    assert ("expander", "Technical details") in calls and ("code", "TimeoutError: request timed out") in calls


def test_a_plain_message_has_no_details_expander_and_an_explicit_hint_wins():
    calls = _spied(msg.show_error, "Choose at least 2 papers.")
    assert calls == [("error", "Choose at least 2 papers.")]
    calls = _spied(msg.show_error, "Could not save", hint="Free some disk space.", exc=OSError("disk full"))
    assert calls[0] == ("error", "Could not save. Free some disk space.")


def test_traceback_text_can_be_passed_as_the_details():
    calls = _spied(msg.show_error, "The analysis hit an error", exc=ValueError("x"), details="Traceback ...")
    assert ("code", "Traceback ...") in calls and ("code", "ValueError: x") not in calls


def test_warnings_and_info_are_cleaned_and_native():
    assert _spied(msg.show_warning, "⚠️ Heads up") == [("warning", "Heads up")]
    assert _spied(msg.show_info, "FYI") == [("info", "FYI")]


# ── every alert in the app goes through the shared functions ───────────────────────────────────
def test_the_app_has_no_direct_alert_calls_left():
    assert not re.findall(r"\bst\.(error|warning|info)\(", APP)
    assert APP.count("show_error(") >= 18 and APP.count("show_warning(") >= 15


def test_exception_messages_never_paste_the_raw_exception_into_the_sentence():
    bad = re.findall(r'show_error\(f"[^"]*\{e\}', APP)
    assert bad == []


# ── microcopy lint: no internal jargon in what the reader sees ─────────────────────────────────
_BANNED = [
    (r"\bLLM\b", "say 'the model'"), (r"\bdeterministic\b", "say 'simpler' or 'rule-based'"),
    (r"\btier ?[123]\b", "tiers are internal"), (r"pip install", "do not tell users to install packages"),
    (r"\bstage \d", "stage numbers are internal"), (r"\bgate\b", "say 'quality check'"),
    (r"traceback", "keep tracebacks behind Technical details"), (r"\bNone\b", "no raw None"),
    (r"\bTODO\b", "unfinished text"),
]


def _message_strings() -> list[str]:
    out = []
    for node in ast.walk(ast.parse(APP)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("show_error", "show_warning", "show_info"):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    out.append(sub.value)
    return out


def test_user_facing_messages_use_plain_words():
    offenders = [(why, s[:80]) for s in _message_strings() for pattern, why in _BANNED if re.search(pattern, s, re.I)]
    assert offenders == [], offenders


def test_the_microcopy_lint_actually_finds_what_it_looks_for():
    assert [w for p, w in _BANNED if re.search(p, "LLM stage 3 tier 2 gate None", re.I)]


def test_messages_are_sentences():
    msgs = [s.strip() for s in _message_strings() if len(s.strip()) > 25]
    assert msgs and all(not s.startswith(("⚠", "❌")) for s in msgs)


# ── the screens still show their alerts ─────────────────────────────────────────────────────
def test_alerts_still_reach_the_page_as_native_alert_elements(app_test, isolated_env):
    at = app_test(timeout=90)
    at.button(key="new_project_btn").click().run()
    at.button(key="np_create").click().run()                                  # no name: an error
    assert any("needs a name" in e.value for e in at.error)


def test_shared_state_components_are_used_by_the_run_progress_card():
    assert 'loading_state(f"Analysis running: {msg}")' in APP
    assert "collapse_sidebar_on_phones()" in APP


# ── the sidebar script ──────────────────────────────────────────────────────────────────────
def test_the_sidebar_script_only_acts_on_narrow_screens_and_targets_the_collapse_button():
    script = comp.sidebar_collapse_script()
    assert script.startswith("<script>") and script.endswith("</script>")
    assert "p.innerWidth <= 768" in script and 'stSidebarCollapseButton' in script and "b.click()" in script
    assert "innerWidth <= 600" in comp.sidebar_collapse_script(600)
    assert "<script" not in comp.sidebar_collapse_script().replace("<script>", "", 1).replace("</script>", "")  # one tag only


def test_choosing_a_page_hands_the_script_to_a_zero_height_frame_exactly_once(app_test, isolated_env):
    seen = []
    import streamlit.components.v1 as components
    real = components.html

    def spy(html, *a, **k):
        seen.append((html, k.get("height")))
        return real(html, *a, **k)

    with patch.object(components, "html", spy):
        at = app_test(timeout=90)
        at.button(key="settings_btn").click().run()
        assert [h for h, _ in seen if "stSidebarCollapseButton" in h] and all(ht == 0 for h, ht in seen if "stSidebarCollapseButton" in h)
        n = len([1 for h, _ in seen if "stSidebarCollapseButton" in h])
        at.run()                                                              # a plain rerun: no new request
        assert len([1 for h, _ in seen if "stSidebarCollapseButton" in h]) == n


def test_loading_a_run_from_the_picker_also_closes_the_sidebar_on_phones(app_test, isolated_env):
    seed_run(golden_results(), name="First")
    seed_run(golden_results(), name="Second")
    seen = []
    import streamlit.components.v1 as components
    real = components.html
    with patch.object(components, "html", lambda h, *a, **k: (seen.append(h), real(h, *a, **k))[1]):
        at = app_test(timeout=90)
        picker = next(s for s in at.sidebar.selectbox if s.label == "Run")
        picker.select(next(o for o in picker.options if "First" in o)).run()
    assert any("stSidebarCollapseButton" in h for h in seen)
