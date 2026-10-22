import pytest

import utils.database as db
from tests.test_unreadable_pdfs import _text_pdf
from utils import project_store

PID = db.DEFAULT_PROJECT_ID


def _store(isolated_env, n=3):
    papers = [(f"p{i}.pdf", _text_pdf(f"paper {i}")) for i in range(n)]
    return papers, project_store.save_papers(PID, papers)


def test_list_papers_returns_stored_files_with_sizes(isolated_env):
    papers, ids = _store(isolated_env)
    listed = project_store.list_papers(PID)
    assert [p["id"] for p in listed] == ids
    assert [p["filename"] for p in listed] == ["p0.pdf", "p1.pdf", "p2.pdf"]
    assert all(p["kb"] >= 1 for p in listed)


def test_list_papers_skips_files_deleted_from_disk(isolated_env):
    _, ids = _store(isolated_env)
    first = project_store.list_papers(PID)[0]
    (project_store.project_dir(PID) / first["rel_path"]).unlink()
    assert [p["id"] for p in project_store.list_papers(PID)] == ids[1:]


def test_read_papers_returns_the_original_bytes_in_the_order_asked(isolated_env):
    papers, ids = _store(isolated_env)
    got = project_store.read_papers(PID, [ids[2], ids[0]])
    assert got == [papers[2], papers[0]]


def test_read_papers_rejects_an_id_from_another_project(isolated_env):
    _, ids = _store(isolated_env)
    other = project_store.create_project("Other")["id"]
    with pytest.raises(ValueError):
        project_store.read_papers(other, [ids[0]])


def test_combine_counts_the_same_file_once():
    a, b = ("a.pdf", b"AAA"), ("b.pdf", b"BBB")
    out, notes = project_store.combine_papers([("again.pdf", b"AAA")], [a, b])
    assert [n for n, _ in out] == ["a.pdf", "b.pdf"]
    assert any("again.pdf" in n and "a.pdf" in n for n in notes)


def test_combine_caps_at_five_and_names_the_rest():
    stored = [(f"s{i}.pdf", bytes([i])) for i in range(4)]
    up = [(f"u{i}.pdf", bytes([10 + i])) for i in range(3)]
    out, notes = project_store.combine_papers(up, stored)
    assert len(out) == 5 and any("u2.pdf" in n for n in notes)


def _run_button(at):
    return next(b for b in at.button if b.label == "Run analysis")


def test_run_button_follows_the_number_of_ticked_papers(app_test, isolated_env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 30)
    _, ids = _store(isolated_env)
    at = app_test(timeout=90)
    boxes = [c for c in at.checkbox if c.label.startswith("p")]
    assert len(boxes) == 3 and _run_button(at).disabled
    boxes[0].check().run()
    at2 = at
    assert _run_button(at2).disabled                      # one paper is not enough
    [c for c in at2.checkbox if c.label.startswith("p1")][0].check().run()
    assert not _run_button(at2).disabled


def test_clicking_run_sends_the_stored_papers_to_the_pipeline(app_test, isolated_env, monkeypatch):
    from pipeline import run_pipeline as rp
    monkeypatch.setenv("GEMINI_API_KEY", "k" * 30)
    papers, _ = _store(isolated_env)
    seen = {}

    def fake_run(papers, **kw):
        seen["papers"] = papers
        raise rp.PipelineInputError("stop here")
    monkeypatch.setattr(rp, "run_full_pipeline", fake_run)

    at = app_test(timeout=90)
    for c in at.checkbox:
        if c.label.startswith(("p0", "p2")):
            c.check()
    at.run()
    _run_button(at).click().run()
    assert seen["papers"] == [papers[0], papers[2]]


def test_no_checklist_when_the_project_has_no_papers(app_test, isolated_env):
    at = app_test(timeout=90)
    assert not [c for c in at.checkbox if "KB" in c.label]
