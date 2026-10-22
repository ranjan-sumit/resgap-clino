"""Guards against two editing accidents that already happened once:
text re-encoded through the wrong code page (mojibake such as 'âœ…'), and a UTF-8 BOM."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_MOJIBAKE = re.compile("[âÃÂ][\u0080-ÿŒœŠšŸŽžƒˆ˜"
                       "–—‘’‚“”„†‡•…‰‹"
                       "›€™]")


def _tracked_py():
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True).stdout
    return [ROOT / p for p in out.split() if not p.startswith("_archive/") and (ROOT / p).exists()]


def test_no_mojibake_in_python_sources():
    bad = [p.name for p in _tracked_py() if p.name != "test_source_hygiene.py"
           and _MOJIBAKE.search(p.read_text(encoding="utf-8", errors="replace"))]
    assert bad == []


def test_no_byte_order_mark_in_python_sources():
    bad = [p.name for p in _tracked_py() if p.read_bytes()[:3] == b"\xef\xbb\xbf"]
    assert bad == []
