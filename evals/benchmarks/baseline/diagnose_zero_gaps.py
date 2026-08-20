"""Phase 0 diagnostic: reproduce detect_gaps() against the saved Story 0.1.1
wiki/graph and print the RAW LLM response before JSON parsing, to determine
whether the 0-gaps result is a genuine "no gaps found" or a silent parse
failure. Read-only diagnostic -- does not modify pipeline/gap_detector.py.
"""
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
from utils.azure_client import AzureOpenAIClient, unwrap
from domain_config import get_domain_config
from pipeline.gap_detector import (
    GAP_DETECTION_PROMPT, inject_domain_into_gap_prompt,
)

data = json.loads((Path(__file__).parent / "phase0-report-v1.json").read_text(encoding="utf-8"))
wiki, graph, context = data["wiki"], data["graph"], data["context"]
domain_cfg = get_domain_config(context["domain"])

pages = wiki.get("pages", [])
communities = graph.get("communities", [])
orphans = graph.get("orphan_concepts", [])
bridges = graph.get("missing_bridges", [])
cross_links = wiki.get("cross_links", {})

wiki_summary = [{
    "title": p.get("title", p.get("source_file", "Unknown")),
    "contributions": p.get("contributions", []),
    "methods": p.get("methods", []),
    "limitations": p.get("limitations", []),
    "future_work": p.get("future_work", []),
    "evaluated_on": p.get("evaluated_on", []),
    "comparison_gap": p.get("comparison_gap", ""),
} for p in pages]

community_summary = [{"theme": c.get("theme", ""), "summary": c.get("summary", ""),
                       "gap_signal": c.get("gap_signal", "")} for c in communities]
orphan_signals = [o.get("signal", "") for o in orphans[:10]]
bridge_signals = [b.get("description", "") for b in bridges[:10]]
conflicts = cross_links.get("conflicts", [])
complementary = cross_links.get("complementary_pairs", [])

prompt_system = inject_domain_into_gap_prompt(
    GAP_DETECTION_PROMPT.format(
        domain=context.get("domain", "General AI/ML"),
        interest=context.get("interest", "General research"),
        gap_type=context.get("gap_type", "Any"),
        n_papers=len(pages),
    ),
    domain_cfg or {}
)
user_prompt = f"""WIKI PAGES (per-paper compiled knowledge):
{json.dumps(wiki_summary, indent=2)}

KNOWLEDGE GRAPH COMMUNITIES:
{json.dumps(community_summary, indent=2)}

ORPHAN CONCEPTS (mentioned but not built upon):
{json.dumps(orphan_signals, indent=2)}

MISSING BRIDGES (limitations that could be solved cross-paper):
{json.dumps(bridge_signals, indent=2)}

COMPLEMENTARY PAPER PAIRS:
{json.dumps(complementary, indent=2)}

CONFLICTS BETWEEN PAPERS:
{json.dumps(conflicts, indent=2)}

Based on all this, identify 4-7 specific, evidence-grounded research gaps.
Prioritize gaps aligned with the researcher's domain: {context.get('domain', 'General AI/ML')}"""

client = AzureOpenAIClient(api_key=os.environ["NVIDIA_API_KEY"].strip())
raw = unwrap(client.chat_json(prompt_system, user_prompt, max_tokens=4000))

out_path = Path(__file__).parent / "diagnostic-raw-gap-response.txt"
out_path.write_text(raw, encoding="utf-8")
print(f"raw response length: {len(raw)} chars")
print(f"saved -> {out_path}")
print("---first 500 chars---")
print(raw[:500])
print("---last 500 chars---")
print(raw[-500:])

try:
    parsed = json.loads(raw)
    print(f"\njson.loads SUCCEEDED: type={type(parsed).__name__}, len={len(parsed) if isinstance(parsed, list) else 'n/a'}")
except json.JSONDecodeError as e:
    print(f"\njson.loads FAILED: {e}")
    import re
    m = re.search(r'\[.*\]', raw, re.DOTALL)
    print(f"regex fallback match found: {bool(m)}")
    if m:
        try:
            parsed2 = json.loads(m.group())
            print(f"regex fallback json.loads SUCCEEDED: len={len(parsed2)}")
        except Exception as e2:
            print(f"regex fallback json.loads ALSO FAILED: {e2}")
