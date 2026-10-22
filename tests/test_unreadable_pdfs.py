import glob
import os
import tempfile
from unittest.mock import patch

import fitz
import pytest

from pipeline import run_pipeline as rp
from pipeline.pdf_parser import check_pdf_readable
from tests.fakes import FakeClient

_TEXT = "Cystic fibrosis outcomes were measured over twelve months in this cohort. " * 8


def _text_pdf(tag="a") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(40, 40, 550, 800), f"{tag}. {_TEXT}")
    data = doc.tobytes()
    doc.close()
    return data


def _scanned_pdf() -> bytes:
    """Image-only page: no text layer."""
    doc = fitz.open()
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 50), False)
    pix.clear_with(200)
    page.insert_image(fitz.Rect(50, 50, 300, 300), pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


def _encrypted_pdf() -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), _TEXT[:100])
    data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    doc.close()
    return data


def _check(data: bytes):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as t:
        t.write(data)
    try:
        return check_pdf_readable(t.name)
    finally:
        os.unlink(t.name)


def test_text_pdf_is_readable():
    assert _check(_text_pdf()) is None


def test_scanned_pdf_is_reported_as_no_text_layer():
    assert "no text layer" in _check(_scanned_pdf())


def test_encrypted_pdf_is_reported():
    assert "password" in _check(_encrypted_pdf())


def test_corrupt_file_is_reported():
    assert "corrupt" in _check(b"this is not a pdf at all")


def _options():
    return rp.RunOptions(provider_key="x", model="m")


def test_all_papers_bad_stops_with_a_clear_message_and_never_calls_the_model(isolated_env):
    client = FakeClient()
    with pytest.raises(rp.PipelineInputError) as e:
        rp.run_full_pipeline([("scan.pdf", _scanned_pdf()), ("bad.pdf", b"junk")], {}, client, _options())
    assert "scan.pdf" in str(e.value) and "bad.pdf" in str(e.value)
    assert client.calls == []


def test_one_bad_paper_among_two_good_is_skipped_with_a_trace_row_and_warning(isolated_env):
    warnings, traces = [], []
    papers = [("a.pdf", _text_pdf("a")), ("scan.pdf", _scanned_pdf()), ("b.pdf", _text_pdf("b"))]
    seen = {}

    def stop_after_stage1(papers_, trees, client, domain_config=None):
        seen["names"] = [p["filename"] for p in papers_]
        raise RuntimeError("stop here")

    with patch("pipeline.run_pipeline.build_wiki", side_effect=stop_after_stage1):
        with pytest.raises(RuntimeError, match="stop here"):
            rp.run_full_pipeline(papers, {}, FakeClient(), _options(),
                                 warn=warnings.append, trace=lambda s, i, o: traces.append((s, o)))
    assert seen["names"] == ["a.pdf", "b.pdf"]
    assert any("scan.pdf" in w for w in warnings)
    assert any("Skipped scan.pdf" in s for s, _ in traces)


def test_no_temp_pdfs_are_left_behind_after_a_crash(isolated_env):
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "*.pdf")))
    with patch("pipeline.run_pipeline.build_wiki", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            rp.run_full_pipeline([("a.pdf", _text_pdf("a")), ("b.pdf", _text_pdf("b"))], {},
                                 FakeClient(), _options())
    assert set(glob.glob(os.path.join(tempfile.gettempdir(), "*.pdf"))) == before

