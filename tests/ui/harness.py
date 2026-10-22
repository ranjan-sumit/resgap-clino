"""Playwright harness: start the app on a throwaway DB, screenshot at 3 viewports."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = Path(__file__).resolve().parent / "_artifacts"
VIEWPORTS = {"desktop": (1440, 800), "laptop": (1024, 768), "phone": (390, 844)}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def running_app(data_dir: Path):
    port = _free_port()
    env = {**os.environ, "RESGAP_DB_PATH": str(data_dir / "ui.db"),
           "RESGAP_PROJECTS_DIR": str(data_dir / "projects")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
         "--server.port", str(port), "--server.headless", "true",
         "--browser.gatherUsageStats", "false"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(url + "/_stcore/health", timeout=1)
                break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError("app did not start")
        yield url
    finally:
        proc.terminate()


def screenshot_all(url: str, name: str) -> list[Path]:
    from playwright.sync_api import sync_playwright
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for label, (w, h) in VIEWPORTS.items():
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto(url)
            page.wait_for_selector("[data-testid='stSidebar'], [data-testid='stMain'] h1, [data-testid='stMain'] h2", timeout=45000)
            page.wait_for_timeout(3000)
            path = ARTIFACTS / f"{name}-{label}.png"
            page.screenshot(path=str(path), full_page=True)
            out.append(path)
            page.close()
        browser.close()
    return out

