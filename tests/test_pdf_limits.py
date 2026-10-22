import os
import tempfile
import time
from unittest.mock import patch

import fitz
import pytest

from pipeline import pdf_limits, run_pipeline as rp
from pipeline.pdf_parser import check_pdf_readable
from tests.fakes import FakeClient
from tests.test_unreadable_pdfs import _options, _text_pdf


def _write(data: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as t:
        t.write(data)
    return t.name


def _blank_pdf(pages: int) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def test_a_2000_page_pdf_is_refused_quickly_and_before_any_page_is_read():
    path = _write(_blank_pdf(2000))
    try:
        t0 = time.time()
        reason = check_pdf_readable(path)
        assert time.time() - t0 < 2
    finally:
        os.unlink(path)
    assert reason.startswith("too long") and "2,000 pages" in reason


def test_a_normal_paper_is_still_readable():
    path = _write(_text_pdf())
    try:
        assert check_pdf_readable(path) is None
    finally:
        os.unlink(path)


def test_an_oversized_file_is_refused_before_it_is_opened(monkeypatch):
    monkeypatch.setenv("RESGAP_MAX_PDF_MB", "0.00005")
    path = _write(_text_pdf())
    try:
        with patch("pipeline.pdf_parser.fitz.open", side_effect=AssertionError("must not open")):
            assert check_pdf_readable(path).startswith("too large")
    finally:
        os.unlink(path)


def test_limits_can_be_changed_by_environment_and_bad_values_fall_back(monkeypatch):
    monkeypatch.setenv("RESGAP_MAX_PDF_PAGES", "5")
    assert pdf_limits.max_pdf_pages() == 5 and pdf_limits.page_problem(6) and not pdf_limits.page_problem(5)
    monkeypatch.setenv("RESGAP_MAX_PDF_PAGES", "banana")
    assert pdf_limits.max_pdf_pages() == 300
    monkeypatch.setenv("RESGAP_MAX_PDF_MB", "-3")
    assert pdf_limits.max_pdf_bytes() == 50 * 1024 * 1024


def test_a_slow_parse_is_cut_off_in_the_background_thread():
    t0 = time.time()
    with pytest.raises(pdf_limits.ParseTimeout):
        pdf_limits.run_limited(time.sleep, 30, timeout=0.3, isolate=False)
    assert time.time() - t0 < 5


def test_a_fast_parse_returns_its_value_and_errors_pass_through():
    assert pdf_limits.run_limited(len, "abc", timeout=5, isolate=False) == 3
    with pytest.raises(ValueError):
        pdf_limits.run_limited(int, "x", timeout=5, isolate=False)


def test_a_separate_process_is_killed_on_timeout_and_returns_values_otherwise():
    t0 = time.time()
    with pytest.raises(pdf_limits.ParseTimeout):
        pdf_limits.run_limited(time.sleep, 60, timeout=3, isolate=True)
    assert time.time() - t0 < 30
    assert pdf_limits.run_limited(len, "abcd", timeout=60, isolate=True) == 4


def test_a_paper_that_times_out_is_skipped_like_an_unreadable_one(isolated_env):
    warnings, seen = [], {}
    real = rp.parse_pdf

    def slow_for_b(path, filename, **kw):
        if filename == "b.pdf":
            time.sleep(5)
        return real(path, filename, **kw)

    def stop(papers_, trees, client, domain_config=None):
        seen["names"] = [p["filename"] for p in papers_]
        raise RuntimeError("stop here")

    papers = [("a.pdf", _text_pdf("a")), ("b.pdf", _text_pdf("b")), ("c.pdf", _text_pdf("c"))]
    with patch.dict(os.environ, {"RESGAP_PARSE_TIMEOUT_S": "1"}), \
         patch("pipeline.run_pipeline.parse_pdf", slow_for_b), \
         patch("pipeline.run_pipeline.build_wiki", side_effect=stop):
        with pytest.raises(RuntimeError, match="stop here"):
            rp.run_full_pipeline(papers, {}, FakeClient(), _options(), warn=warnings.append)
    assert seen["names"] == ["a.pdf", "c.pdf"]
    assert any("b.pdf" in w and "longer than" in w for w in warnings)


def test_both_upload_places_apply_the_size_limit():
    from pathlib import Path
    app_src = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
    assert app_src.count("_within_size_limit(") >= 3           # the definition and the two upload places
    assert "up to 200 MB" not in app_src
