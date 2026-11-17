"""UI-05: wording rules applied at display time."""
from ui.copy import plain_stage, status_mark, status_word, strip_emoji


def test_strip_emoji_removes_pictographs_and_keeps_text_marks():
    assert strip_emoji("\U0001F4CA Mean (3 total)") == "Mean (3 total)"
    assert strip_emoji("⚠️ 4 thing(s) to know") == "4 thing(s) to know"               # a pictograph plus its variation selector
    assert strip_emoji("Limitations ⚠️") == "Limitations"
    assert strip_emoji("✓ Processed → next · done ★ starred") == "✓ Processed → next · done ★ starred"
    assert strip_emoji("\U0001F3E5\U0001F52C  two   emoji") == "two emoji"
    assert strip_emoji(None) == "" and strip_emoji("plain") == "plain"


def test_status_marks_replace_the_stored_emoji_statuses():
    assert [status_mark(s) for s in ("✅", "⚠️", "⚠", "❌", "", None)] == ["✓", "!", "!", "✗", "✓", "✓"]
    assert status_word("✓") == "OK" and status_word("!") == "Warning" and status_word("✗") == "Failed"
    assert status_mark("✅ ") == "✓"                                                    # stray space


def test_plain_stage_drops_emoji_and_long_dashes_but_not_the_name():
    assert plain_stage("Stage 2 — LLM Wiki") == "Stage 2 - LLM Wiki"
    assert plain_stage("✅ Stage 1 — PDF Parse") == "Stage 1 - PDF Parse"
    assert plain_stage("Parsed re3_varsha.pdf") == "Parsed re3_varsha.pdf"
    assert "—" not in plain_stage("a—b")
