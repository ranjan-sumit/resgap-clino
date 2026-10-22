"""Safety limits for uploaded PDFs: file size, page count and parse time.

A huge or malformed PDF must be refused quickly with a plain reason, never allowed to hang a run or use up the
server's memory. Limits can be changed with environment variables (RESGAP_MAX_PDF_MB, RESGAP_MAX_PDF_PAGES,
RESGAP_PARSE_TIMEOUT_S). Setting RESGAP_ISOLATE_PARSER=1 parses each paper in a separate process that is killed on
timeout, so a runaway parser cannot take the app with it.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import threading


def _env_number(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, ""))
        return value if value > 0 else default
    except ValueError:
        return default


def max_pdf_bytes() -> int:
    return int(_env_number("RESGAP_MAX_PDF_MB", 50) * 1024 * 1024)


def max_pdf_pages() -> int:
    return int(_env_number("RESGAP_MAX_PDF_PAGES", 300))


def parse_timeout_s() -> float:
    return _env_number("RESGAP_PARSE_TIMEOUT_S", 240)


class ParseTimeout(Exception):
    """Raised when a paper takes longer than the parse limit."""


def size_problem(n_bytes: int) -> str | None:
    """The reason a file of this size is refused, or None. Cheap: runs before the file is opened."""
    if n_bytes > max_pdf_bytes():
        return f"too large ({n_bytes / 1024 / 1024:.0f} MB; the limit is {max_pdf_bytes() // 1024 // 1024} MB)"
    return None


def page_problem(n_pages: int) -> str | None:
    if n_pages > max_pdf_pages():
        return f"too long ({n_pages:,} pages; the limit is {max_pdf_pages():,})"
    return None


def _worker(queue, fn, args, kwargs):
    try:
        queue.put(("ok", fn(*args, **kwargs)))
    except BaseException as e:                                   # report anything, the parent decides
        queue.put(("error", f"{type(e).__name__}: {e}"))


def _in_process(fn, args, kwargs, timeout):
    box: dict = {}

    def run():
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as e:                               # re-raised in the caller below
            box["error"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise ParseTimeout(f"took longer than {timeout:.0f} s")  # the thread is abandoned, not killed
    if "error" in box:
        raise box["error"]
    return box["value"]


def _in_subprocess(fn, args, kwargs, timeout):
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    proc = ctx.Process(target=_worker, args=(queue, fn, args, kwargs), daemon=True)
    proc.start()
    try:
        kind, value = queue.get(timeout=timeout)
    except Exception:
        proc.kill()
        proc.join(5)
        raise ParseTimeout(f"took longer than {timeout:.0f} s") from None
    proc.join(5)
    if kind == "error":
        raise RuntimeError(value)
    return value


def run_limited(fn, *args, timeout: float | None = None, isolate: bool | None = None, **kwargs):
    """Run fn(*args, **kwargs) under the parse time limit. With isolation (a separate process) the work is
    killed on timeout; without it the work is abandoned in a background thread. Only picklable arguments can go
    to a separate process, so callers with a model client pass isolate=False."""
    timeout = parse_timeout_s() if timeout is None else timeout
    if isolate is None:
        isolate = os.getenv("RESGAP_ISOLATE_PARSER", "") == "1"
    return (_in_subprocess if isolate else _in_process)(fn, args, kwargs, timeout)
