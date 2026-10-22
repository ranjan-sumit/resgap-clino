import pytest

from pipeline import run_pipeline as rp
from pipeline import wiki_compiler as wc
from tests.fakes import FakeClient
from utils.azure_client import LLMCallError, ErrorInfo


def _pdf(tag: str) -> bytes:
    return f"%PDF-fake-{tag}".encode()


def test_six_uploads_name_the_dropped_paper():
    papers = [(f"p{i}.pdf", _pdf(i)) for i in range(6)]
    kept, notices = rp.prepare_papers(papers)
    assert [f for f, _ in kept] == [f"p{i}.pdf" for i in range(5)]
    assert any("p5.pdf" in n and "Not analysed" in n for n in notices)


def test_five_uploads_give_no_notice():
    kept, notices = rp.prepare_papers([(f"p{i}.pdf", _pdf(i)) for i in range(5)])
    assert len(kept) == 5 and notices == []


def test_same_pdf_twice_is_analysed_once():
    kept, notices = rp.prepare_papers([("a.pdf", _pdf("x")), ("copy.pdf", _pdf("x")), ("b.pdf", _pdf("y"))])
    assert [f for f, _ in kept] == ["a.pdf", "b.pdf"]
    assert any("copy.pdf" in n and "a.pdf" in n for n in notices)


def test_duplicates_are_removed_before_the_limit_is_applied():
    papers = [("a.pdf", _pdf("x")), ("a2.pdf", _pdf("x"))] + [(f"p{i}.pdf", _pdf(i)) for i in range(4)]
    kept, notices = rp.prepare_papers(papers)
    assert len(kept) == 5 and not any("Not analysed" in n for n in notices)


def test_two_different_papers_with_one_filename_keep_separate_names():
    kept, notices = rp.prepare_papers([("paper.pdf", _pdf("a")), ("paper.pdf", _pdf("b"))])
    names = [f for f, _ in kept]
    assert len(set(names)) == 2 and all(n.endswith(".pdf") for n in names)
    assert len(notices) == 2


def test_pipeline_rejects_when_dedupe_leaves_one_paper():
    with pytest.raises(rp.PipelineInputError):
        rp.run_full_pipeline([("a.pdf", _pdf("x")), ("b.pdf", _pdf("x"))], {}, FakeClient(),
                             rp.RunOptions(provider_key="x", model="m"))


def test_cross_link_failure_does_not_crash_the_wiki(monkeypatch):
    monkeypatch.setattr(wc, "compile_wiki_page",
                        lambda paper, tree, client, domain_config=None: {"title": paper["t"], "key_concepts": ["c"]})

    def boom(pages, client):
        raise LLMCallError(ErrorInfo(kind="rate_limit", detail="429"))
    monkeypatch.setattr(wc, "compile_cross_links", boom)

    wiki = wc.build_wiki([{"t": "A"}, {"t": "B"}], [{}, {}], FakeClient())
    assert len(wiki["pages"]) == 2
    assert wiki["cross_links"] == {}
    assert len(wiki["warnings"]) == 1 and "skipped" in wiki["warnings"][0]


def test_successful_cross_links_have_no_warnings(monkeypatch):
    monkeypatch.setattr(wc, "compile_wiki_page",
                        lambda paper, tree, client, domain_config=None: {"title": paper["t"]})
    monkeypatch.setattr(wc, "compile_cross_links", lambda pages, client: {"shared_concepts": []})
    assert wc.build_wiki([{"t": "A"}], [{}], FakeClient())["warnings"] == []

