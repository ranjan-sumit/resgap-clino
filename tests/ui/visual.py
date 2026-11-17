"""Screenshot baselines for the key screens (UI-14).

A baseline is the picture a person approved. A test takes the same screenshot and compares it; if more than a small share of
pixels changed, it fails and saves what it saw next to the baseline so a person can decide: fix the UI, or approve the new
look by regenerating (UPDATE_BASELINES=1) and reviewing the picture in the diff.

Baselines are per platform (fonts render differently on Windows, macOS and Linux), so each platform keeps its own folder and
a platform with no baseline yet skips instead of failing.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageChops

HERE = Path(__file__).parent
PLATFORM = sys.platform                                   # "win32", "linux", "darwin"
BASELINES = HERE / "_baselines" / PLATFORM
ARTIFACTS = HERE / "_artifacts"
UPDATE = os.environ.get("UPDATE_BASELINES") == "1"

PER_PIXEL = 40            # a pixel counts as changed when any colour differs by more than this (of 255)
MAX_CHANGED = 0.005       # and a picture passes while at most this share of its pixels changed

# What changes between runs and is not part of the design: dates, run ids and the run picker's label. They are hidden (not removed)
# so the layout around them is still checked.
FREEZE_CSS = """
*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }
.proj-meta, .run-bar .rb-meta, [data-testid="stSidebar"] [data-baseweb="select"] { visibility: hidden !important; }
"""

VIEWPORTS = {"desktop": (1440, 800), "tablet": (1024, 768), "phone": (390, 844)}


def changed_share(actual: Image.Image, baseline: Image.Image, per_pixel: int = PER_PIXEL) -> float:
    """Share of pixels that differ by more than `per_pixel` (1.0 when the sizes differ)."""
    if actual.size != baseline.size:
        return 1.0
    diff = ImageChops.difference(actual.convert("RGB"), baseline.convert("RGB")).convert("L")
    mask = diff.point(lambda p: 255 if p > per_pixel else 0)
    return mask.histogram()[255] / float(diff.size[0] * diff.size[1])


def compare(actual_path: Path, baseline_path: Path, max_changed: float = MAX_CHANGED) -> tuple[bool, float]:
    share = changed_share(Image.open(actual_path), Image.open(baseline_path))
    return share <= max_changed, share


def save_side_by_side(actual_path: Path, baseline_path: Path, out: Path) -> None:
    """baseline | actual | changed pixels, for a person to look at."""
    a, b = Image.open(actual_path).convert("RGB"), Image.open(baseline_path).convert("RGB")
    w, h = max(a.width, b.width), max(a.height, b.height)
    sheet = Image.new("RGB", (w * 3 + 20, h), (255, 255, 255))
    sheet.paste(b, (0, 0))
    sheet.paste(a, (w + 10, 0))
    if a.size == b.size:
        diff = ImageChops.difference(a, b).convert("L").point(lambda p: 255 if p > PER_PIXEL else 0)
        sheet.paste(diff.convert("RGB"), (w * 2 + 20, 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
