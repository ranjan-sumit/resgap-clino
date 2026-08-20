"""
Phase 0, Story 0.1.1 — generate a real baseline report from the existing
(pre-Clinova) pipeline against a small real corpus.

This is a measurement harness, not an engine change: it calls the existing
pipeline/*.py stages in exactly the order app.py's run button does (see
app.py's "Main Pipeline" section) and saves the result immutably. It does
not modify any pipeline/utils module.

Usage:
    python evals/benchmarks/baseline/generate_baseline_report.py \
        --papers-dir path/to/sample_papers \
        --domain "Healthcare AI" \
        --interest "diagnostic imaging fairness" \
        --out-name phase0-report-v1

Reads NVIDIA_API_KEY (required) and SEMANTIC_SCHOLAR_API_KEY (optional) from
a local .env file (see .env.example) or from the environment directly.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

OUT_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader — avoids adding python-dotenv as a new dependency
    for a single-use script (see 04-ai-research-architecture.md §2's
    dependency-discipline convention, applied here to tooling too)."""
    import os

    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--papers-dir", required=True, type=Path,
                         help="Directory of sample PDF papers (>=2 required, matching app.py's own minimum)")
    parser.add_argument("--domain", default="Healthcare AI")
    parser.add_argument("--interest", default="General research")
    parser.add_argument("--gap-type", default="Any")
    parser.add_argument("--out-name", default="phase0-report-v1")
    parser.add_argument("--extract-refs", action="store_true", default=True)
    parser.add_argument("--no-extract-refs", dest="extract_refs", action="store_false")
    args = parser.parse_args()

    _load_dotenv(REPO_ROOT / ".env")

    import os
    api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
    ss_api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    if not api_key:
        print("ERROR: NVIDIA_API_KEY not set. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 1

    pdf_paths = sorted(args.papers_dir.glob("*.pdf"))
    if len(pdf_paths) < 2:
        print(f"ERROR: found {len(pdf_paths)} PDFs in {args.papers_dir}; need at least 2 "
              f"(app.py itself refuses to run below this).", file=sys.stderr)
        return 1

    from utils.azure_client import AzureOpenAIClient
    from utils.export import to_enterprise_html_report
    from pipeline.pdf_parser import parse_pdf
    from pipeline.page_index import build_tree, tree_to_summary
    from pipeline.wiki_compiler import build_wiki
    from pipeline.graph_builder import build_knowledge_graph
    from pipeline.gap_detector import detect_gaps
    from pipeline.academic_search import validate_gaps
    from pipeline.proposal_generator import generate_proposals
    from pipeline.reference_extractor import extract_and_enrich_references, summarise_reference_corpus
    from pipeline.paper_manager import assign_tiers, corpus_stats
    from domain_config import get_domain_config

    client = AzureOpenAIClient(api_key=api_key)
    domain_cfg = get_domain_config(args.domain)
    context = {"domain": args.domain, "interest": args.interest, "gap_type": args.gap_type}

    t0 = time.time()
    print(f"[1/6] Parsing {len(pdf_paths)} PDFs + building PageIndex trees...")
    all_papers, all_trees = [], []
    for pdf_path in pdf_paths:
        paper = parse_pdf(str(pdf_path), pdf_path.name, client=None, use_vision=False)
        paper["tier"] = 1
        all_papers.append(paper)
        all_trees.append(build_tree(paper))
    print(f"      {sum(p.get('char_count', 0) for p in all_papers):,} chars extracted")

    ref_papers, ref_diagnostics = [], {}
    if args.extract_refs:
        print("[1B/6] Extracting & enriching references...")

        def _progress(_current, _total, msg):
            print(f"      {msg}")

        ref_papers, ref_diagnostics = extract_and_enrich_references(
            all_papers, client, progress_callback=_progress, return_diagnostics=True,
        )
        ref_summary = summarise_reference_corpus(ref_papers)
        print(f"      {ref_summary['total']} refs from {ref_diagnostics.get('raw_entries', 0)} raw entries: "
              f"{ref_summary['tier2_abstract']} with abstract, {ref_summary['tier3_title']} title-only")
    else:
        ref_summary = summarise_reference_corpus(ref_papers)

    print("[2/6] Compiling LLM wiki pages...")
    wiki = build_wiki(all_papers, all_trees, client, domain_config=domain_cfg)
    print(f"      {len(wiki.get('pages', []))} pages")

    print("[3/6] Building knowledge graph...")
    graph = build_knowledge_graph(wiki, client, domain_config=domain_cfg)
    print(f"      {graph['stats']['entity_count']} entities, {graph['stats']['relationship_count']} relationships, "
          f"fallback_used={graph.get('diagnostics', {}).get('fallback_used')}")

    print("[4/6] Detecting research gaps...")
    gaps = detect_gaps(wiki, graph, context, client, domain_config=domain_cfg)

    print("[5/6] Validating gaps (Semantic Scholar + arXiv)...")
    validated_gaps = validate_gaps(gaps, client, domain_config=domain_cfg, ss_api_key=ss_api_key)
    open_count = sum(1 for g in validated_gaps if g.get("validation_status") == "open")
    print(f"      {len(validated_gaps)} gaps: {open_count} open")

    print("[6/6] Generating proposals...")
    proposals = generate_proposals(validated_gaps, wiki, context, client, domain_config=domain_cfg)
    print(f"      {len(proposals)} proposals")

    corpus = assign_tiers(all_papers, ref_papers)
    results = {
        "papers": [
            {"filename": p["filename"], "wiki": w, "char_count": p.get("char_count", 0),
             "sections": p.get("sections", {}), "tables": p.get("tables", []),
             "tree_summary": tree_to_summary(t, max_chars=2000), "tier": 1}
            for p, w, t in zip(all_papers, wiki["pages"], all_trees)
        ],
        "wiki": wiki, "graph": graph,
        "gaps": validated_gaps, "proposals": proposals,
        "communities": graph.get("communities", []),
        "context": context,
        "corpus_stats": corpus_stats(corpus),
        "ref_summary": ref_summary,
        "ref_papers": ref_papers,
        "ref_diagnostics": ref_diagnostics,
        "corpus": corpus,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "duration_seconds": round(time.time() - t0, 1),
        "pipeline_note": "Pre-Clinova baseline (Phase 0) -- existing ResGap pipeline, unmodified.",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / f"{args.out_name}.json"
    json_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved structured results -> {json_path}")

    try:
        html = to_enterprise_html_report(results, context, narrative=None)
        html_path = OUT_DIR / f"{args.out_name}.html"
        html_path.write_text(html, encoding="utf-8")
        print(f"Saved HTML report        -> {html_path}")
    except Exception:
        print("WARNING: HTML report generation failed (non-fatal, JSON results are still valid):",
              file=sys.stderr)
        traceback.print_exc()

    print(f"\nDone in {results['duration_seconds']}s.")
    print("Next: manually review the JSON/HTML for Problems A-F evidence per "
          "09-epics-and-stories.md Story 0.1.3.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
