"""Verify the B19 fix against the exact real data that exposed the bug:
re-run detect_gaps against the saved Phase 0 wiki/graph/context using the
NEW retry/raise logic, and confirm generate_proposals never calls the LLM
when handed an empty gap list. Read-only verification, no engine changes."""
from __future__ import annotations
import json, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))


def _load_dotenv(path: Path) -> None:
    import os
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() and k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip()


_load_dotenv(REPO_ROOT / ".env")
import os
from utils.azure_client import AzureOpenAIClient
from pipeline.gap_detector import detect_gaps, GapDetectionError
from pipeline.proposal_generator import generate_proposals

data = json.loads((Path(__file__).parent / "phase0-report-v1.json").read_text(encoding="utf-8"))
wiki, graph, context = data["wiki"], data["graph"], data["context"]

client = AzureOpenAIClient(api_key=os.environ["NVIDIA_API_KEY"].strip())

print("Calling detect_gaps() with the B19 fix against the real Phase 0 wiki/graph...")
try:
    gaps = detect_gaps(wiki, graph, context, client)
    print(f"RESULT: {len(gaps)} gaps returned (retry logic gave the LLM a fair chance to produce a real result)")
    for g in gaps:
        print(" -", (g.get("title") or "").encode("ascii", "replace").decode("ascii"))
except GapDetectionError as e:
    print(f"RESULT: GapDetectionError raised as designed -- both attempts failed to parse: {e}")
    print(f"raw_response_preview (first 300 chars): {e.raw_response_preview[:300]!r}")
    gaps = None

print("\nVerifying generate_proposals([], ...) never calls the LLM...")
from unittest.mock import MagicMock
mock_client = MagicMock()
proposals = generate_proposals([], wiki, context, mock_client)
assert proposals == [], f"expected [], got {proposals}"
assert not mock_client.chat_json.called, "generate_proposals called the LLM with an empty gaps list -- B19 fix not working"
print("CONFIRMED: generate_proposals([], ...) returns [] and never calls the LLM.")
