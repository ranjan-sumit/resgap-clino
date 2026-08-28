"""
Headless pipeline orchestration (Clinova Phase 5, Epic 5.6).

This is the Stage 1-6 run that used to live inline inside `app.py`'s
"Run Analysis" button handler, lifted out verbatim so it can be driven by
anything -- Streamlit, the FastAPI app, a test, a script -- instead of only
by a Streamlit rerun.

Design notes:

* **Zero Streamlit imports.** Progress, per-stage trace rows, and non-fatal
  warnings are delivered through injected callbacks (`progress`, `trace`,
  `warn`), all defaulting to no-ops. `app.py` passes its existing `upd()` /
  `_add_trace()` / `st.warning` straight in, so its behaviour is unchanged.
* **Papers arrive as (filename, pdf_bytes).** Streamlit's `UploadedFile` and
  an HTTP multipart upload both reduce to that, so neither caller leaks its
  own upload type into the pipeline.
* **Behaviour is deliberately identical to the original block**, including
  its several "one paper failing must not kill the run" try/excepts and the
  B23 gate-blocked path that still saves everything already fetched. This
  module is an extraction, not a rewrite -- any behaviour change here would
  silently change what Streamlit does too.
"""
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from pipeline.academic_search import validate_gaps
from pipeline.canonical_resolver import filter_and_dedupe_references
from pipeline.corpus_quality import (
    QualityGateBlockedError, compute_corpus_quality, enforce_quality_gate,
    score_paper_completeness,
)
from pipeline.deterministic_gap_patterns import detect_deterministic_gaps
from pipeline.docling_parser import DOCLING_STAGE_VERSION, extract_with_docling
from pipeline.evidence_extractor import extract_evidence_cached
from pipeline.extraction_reconciler import reconcile_paper
from pipeline.gap_challenger import GAP_CHALLENGER_STAGE_VERSION, run_challenge
from pipeline.gap_detector import detect_gaps
from pipeline.graph_builder import build_knowledge_graph
from pipeline.graph_persistence import (
    GRAPH_PERSISTENCE_VERSION, connect_ok as arcadedb_connect_ok, save_graph_snapshot,
)
from pipeline.graph_quality import apply_graph_quality_to_gaps, score_graph_quality
from pipeline.graph_structural_gaps import detect_graph_structural_gaps
from pipeline.lineage import record_run_lineage
from pipeline.page_index import build_tree, tree_to_summary
from pipeline.paper_manager import assign_tiers, corpus_stats
from pipeline.pdf_parser import parse_pdf
from pipeline.proposal_generator import generate_proposals
from pipeline.reference_extractor import (
    REFERENCE_STAGE_VERSION, extract_and_enrich_references, summarise_reference_corpus,
)
from pipeline.relevance_ranking import EMBEDDING_MODEL, RERANK_MODEL
from pipeline.wiki_compiler import build_wiki
from utils.database import record_artifact, record_run_manifest, save_run


class PipelineInputError(ValueError):
    """A caller-supplied input is unusable (too few papers, etc). Distinct
    from a mid-run failure so callers can report it as a validation problem
    rather than a crash."""


@dataclass
class RunOptions:
    """Every sidebar toggle the original inline block read from module
    scope, made explicit so a non-Streamlit caller can set them."""
    provider_key: str
    model: str
    use_vision: bool = False
    extract_refs: bool = False
    ref_limit: int | None = None          # None == "All"
    enable_quality_engine: bool = False
    override_quality_gate: bool = False
    enable_gap_challenger: bool = False
    enable_graph_persistence: bool = False
    ss_api_key: str = ""
    domain_config: dict | None = None
    git_commit: str | None = None


@dataclass
class RunOutcome:
    results: dict
    run_id: str
    name: str
    gate_blocked: bool = False
    gate_block_reasons: list[str] = field(default_factory=list)
    n_papers: int = 0
    n_refs: int = 0
    n_evidence: int = 0
    n_gaps: int = 0
    n_proposals: int = 0
    duration_seconds: float = 0.0


def _noop(*_args, **_kwargs) -> None:
    return None


MIN_PAPERS = 2
MAX_PAPERS = 5


def run_full_pipeline(
    papers: list[tuple[str, bytes]],
    context: dict,
    client,
    options: RunOptions,
    name: str = "",
    *,
    progress: Callable[[str, int], None] = _noop,
    trace: Callable[[str, str, str], None] = _noop,
    warn: Callable[[str], None] = _noop,
    token_meter=None,
) -> RunOutcome:
    """Runs Stages 1-6 and persists the run. Returns a RunOutcome.

    `papers` is a list of (filename, pdf_bytes). `progress(msg, pct)`,
    `trace(stage, inputs, outputs)` and `warn(msg)` are optional callbacks.
    """
    if len(papers) < MIN_PAPERS:
        raise PipelineInputError(
            f"Upload at least {MIN_PAPERS} papers (got {len(papers)}) -- gap detection "
            "compares papers against each other, so a single paper has nothing to compare to."
        )
    papers = papers[:MAX_PAPERS]

    domain_cfg = options.domain_config
    run_start = time.time()
    name = (name or "").strip() or f"{context.get('domain', 'Run')[:20]} — {datetime.now().strftime('%H:%M')}"

    # The pipeline owns its own trace rows rather than relying on the
    # caller's callback to retain them: results["pipeline_trace"] is what
    # Run Detail's Stages tab reads, so a caller that passes no `trace`
    # callback (the API, a test) must still produce a run with a real
    # stage timeline. The callback is additionally invoked for live display.
    trace_rows: list[dict] = []

    def _trace(stage: str, inputs: str, outputs: str, status: str = "✅") -> None:
        trace_rows.append({"stage": stage, "inputs": inputs, "outputs": outputs, "status": status})
        trace(stage, inputs, outputs)

    all_papers, all_trees = [], []

    # ── Stage 1+2: Parse + PageIndex ──────────────────────────────────────
    progress("Stage 1 — Parsing PDFs & building PageIndex trees…", 5)
    # When the Corpus Quality Engine is enabled, Stage 2B needs each paper's
    # original PDF file (Docling operates on the file, not extracted text) --
    # keep the temp files alive until then instead of deleting here.
    paper_tmp_paths = []
    for filename, content in papers:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        paper = parse_pdf(tmp_path, filename,
                          client=client if options.use_vision else None,
                          use_vision=options.use_vision)
        paper["tier"] = 1
        all_papers.append(paper)
        all_trees.append(build_tree(paper))
        if options.enable_quality_engine:
            paper_tmp_paths.append(tmp_path)
        else:
            os.unlink(tmp_path)

    _trace("Stage 1 — PDF Parse",
          f"{len(papers)} PDFs",
          f"{sum(p.get('char_count', 0) for p in all_papers):,} chars extracted")
    progress("Stage 1 complete", 12)

    # ── Stage 1B/1C: References ───────────────────────────────────────────
    ref_papers: list = []
    ref_diagnostics: dict = {}
    ref_resolution_diagnostics = None
    if options.extract_refs:
        progress("Stage 1B — Extracting & enriching references (50+ paper corpus)…", 14)

        def ref_upd(_current, _total, msg):
            progress(f"Stage 1B — {msg}", 14)

        ref_papers, ref_diagnostics = extract_and_enrich_references(
            all_papers, client,
            max_refs_per_paper=options.ref_limit,
            progress_callback=ref_upd,
            return_diagnostics=True,
        )
        summary = summarise_reference_corpus(ref_papers)
        _trace("Stage 1B — Reference Extraction",
              f"{len(papers)} PDFs scanned",
              f"{summary['total']} refs from {ref_diagnostics.get('raw_entries', 0)} raw entries: "
              f"{summary['tier2_abstract']} with abstract, {summary['tier3_title']} title-only")

        # Only VERIFIED/ACCEPTED references feed the rest of the pipeline;
        # QUARANTINED/UNRESOLVED are dropped from what downstream stages see
        # but counted in diagnostics -- never silently discarded.
        if options.enable_quality_engine and ref_papers:
            progress("Stage 1C — Canonical reference resolution…", 21)
            ref_papers, ref_resolution_diagnostics = filter_and_dedupe_references(ref_papers)
            sc = ref_resolution_diagnostics["status_counts"]
            _trace("Stage 1C — Reference Resolution",
                  f"{ref_resolution_diagnostics['input_count']} enriched refs",
                  f"{ref_resolution_diagnostics['trusted_count']} trusted "
                  f"(VERIFIED {sc['VERIFIED']}, ACCEPTED {sc['ACCEPTED']}), "
                  f"{sc['QUARANTINED']} quarantined, {sc['UNRESOLVED']} unresolved, "
                  f"{ref_resolution_diagnostics['duplicates_removed']} duplicates merged")
    progress("References complete", 20)

    # ── Stage 2: Wiki ─────────────────────────────────────────────────────
    progress("Stage 2 — Compiling LLM Wiki pages…", 22)
    client.set_stage("Stage 2 — LLM Wiki")
    wiki = build_wiki(all_papers, all_trees, client, domain_config=domain_cfg)
    _trace("Stage 2 — LLM Wiki",
          f"{len(all_papers)} papers",
          f"{len(wiki.get('pages', []))} pages, "
          f"{len(wiki.get('cross_links', {}).get('shared_concepts', []))} links")
    progress("Wiki complete", 34)

    # ── Stage 2B: Corpus Quality Engine (opt-in) ──────────────────────────
    corpus_quality_metrics = None
    gate_blocked = False
    gate_block_reasons: list[str] = []
    wiki_pages = wiki.get("pages", [])
    # Honest default: no real page provenance available when the Quality
    # Engine is off. Stage 2C runs regardless and degrades gracefully.
    docling_results = [None] * len(all_papers)

    if options.enable_quality_engine:
        progress("Stage 2B — Corpus Quality Engine (multi-parser cross-check)…", 35)
        paper_scores = []
        docling_results = []
        for i, (paper, tmp_path) in enumerate(zip(all_papers, paper_tmp_paths)):
            progress(f"Stage 2B — Cross-checking paper {i+1}/{len(all_papers)} with Docling…", 35)
            wiki_page = wiki_pages[i] if i < len(wiki_pages) else {}
            docling_result = None
            try:
                docling_result = extract_with_docling(tmp_path, paper.get("filename", papers[i][0]))
                reconciled = reconcile_paper(paper, docling_result, paper.get("filename", ""))
            except Exception:
                # A Docling failure degrades this paper's score rather than
                # aborting the run -- its doi/tables fields score as
                # not-extracted, correctly lowering completeness instead of
                # pretending nothing was lost.
                reconciled = {"fields": {}}
            docling_results.append(docling_result)
            paper_scores.append(score_paper_completeness(
                reconciled, wiki_page,
                ref_count=len(ref_papers), has_figures=bool(paper.get("figures")),
            ))

        corpus_quality_metrics = compute_corpus_quality(
            paper_scores, ref_diagnostics, ref_papers=ref_papers,
        )
        try:
            corpus_quality_metrics = enforce_quality_gate(
                corpus_quality_metrics,
                override=options.override_quality_gate,
                override_reason="caller override" if options.override_quality_gate else "",
                override_by="pipeline_caller",
            )
        except QualityGateBlockedError as e:
            # B23: caught locally so already-fetched data is still saved.
            # Stages 3-6 are skipped (PRD FR-3 forbids analyzing a FAIL-gated
            # corpus); only that output is empty, not the whole run.
            gate_blocked = True
            gate_block_reasons = e.reasons

        _trace("Stage 2B — Corpus Quality Engine",
              f"{len(all_papers)} papers, {len(ref_papers)} refs",
              f"{corpus_quality_metrics['extraction_completeness']:.0%} extraction completeness, "
              f"{corpus_quality_metrics['doi_resolution_rate']:.0%} DOI resolution, "
              f"gate={corpus_quality_metrics['quality_gate']}")

    for p in paper_tmp_paths:
        try:
            os.unlink(p)
        except OSError:
            pass

    # ── Stage 2C: Evidence Extraction (always runs) ───────────────────────
    progress("Stage 2C — Extracting evidence objects…", 35)
    evidence_objects: dict = {}
    total_evidence = 0
    for i, paper in enumerate(all_papers):
        wiki_page = wiki_pages[i] if i < len(wiki_pages) else {}
        docling_result = docling_results[i] if i < len(docling_results) else None
        filename = paper.get("filename", f"paper_{i+1}")
        try:
            evidence_dicts, _, _ = extract_evidence_cached(
                filename, wiki_page, docling_result, client=client, use_llm=True,
            )
        except Exception:
            # Evidence extraction is additive, not load-bearing.
            evidence_dicts = []
        evidence_objects[filename] = evidence_dicts
        total_evidence += len(evidence_dicts)

    _trace("Stage 2C — Evidence Extraction",
          f"{len(all_papers)} papers",
          f"{total_evidence} evidence objects extracted "
          f"({'with' if options.enable_quality_engine else 'without'} Docling page provenance)")

    # ── Stages 3-6 (skipped entirely on a FAIL gate) ──────────────────────
    if not gate_blocked:
        progress("Stage 3 — Building knowledge graph (LazyGraphRAG)…", 36)
        client.set_stage("Stage 3 — Knowledge Graph")
        graph = build_knowledge_graph(wiki, client, domain_config=domain_cfg,
                                      evidence_objects=evidence_objects)
        graph_quality = score_graph_quality(graph, wiki)
        _trace("Stage 3 — Knowledge Graph",
              "Wiki pages + cross-links",
              f"{graph['stats']['entity_count']} entities, "
              f"{graph['stats']['relationship_count']} relationships "
              f"— {graph_quality['build_status']} (quality={graph_quality['quality_score']})")
        progress("Graph complete", 48)

        progress("Stage 4 — Detecting research gaps…", 50)
        client.set_stage("Stage 4 — Gap Detection")
        gaps = detect_gaps(wiki, graph, context, client, domain_config=domain_cfg,
                           evidence_objects=evidence_objects)
        # Two additional, independent candidate-gap sources (no LLM call):
        # the deterministic pattern library and graph-structural signals.
        det_gaps = detect_deterministic_gaps(evidence_objects, context.get("domain", ""))
        graph_gaps = detect_graph_structural_gaps(graph)
        gaps = gaps + det_gaps + graph_gaps
        # FR-7: a DEGRADED/FALLBACK graph downgrades confidence for gaps
        # whose entire evidentiary basis is that graph.
        gaps = apply_graph_quality_to_gaps(gaps, graph_quality)

        progress("Stage 5 — Validating gaps (Semantic Scholar + arXiv)…", 58)
        client.set_stage("Stage 5 — Gap Validation")
        validated_gaps = validate_gaps(gaps, client, domain_config=domain_cfg,
                                       ss_api_key=(options.ss_api_key or "").strip())
        _trace("Stage 4-5 — Gaps",
              "Wiki + graph + domain context"
              + (f" + {len(det_gaps)} deterministic-pattern candidates" if det_gaps else "")
              + (f" + {len(graph_gaps)} graph-structural candidates" if graph_gaps else ""),
              f"{len(validated_gaps)} gaps: "
              f"{sum(1 for g in validated_gaps if g.get('validation_status') == 'open')} open")
        progress("Gaps complete", 66)

        if options.enable_gap_challenger:
            progress("Stage 5b — Gap Challenger (search coverage + terminal status)…", 62)
            client.set_stage("Stage 5b — Gap Challenger")
            for i, gap in enumerate(validated_gaps):
                progress(f"Stage 5b — Challenging gap {i+1}/{len(validated_gaps)}…", 62)
                try:
                    gap.update(run_challenge(
                        gap, client, ss_api_key=(options.ss_api_key or "").strip(),
                        domain_config=domain_cfg,
                    ))
                except Exception as e:
                    # Per-gap failure degrades that gap only.
                    gap["challenger_state"] = None
                    gap["challenger_status"] = None
                    gap["challenger_error"] = str(e)
            statuses = [g.get("challenger_status") for g in validated_gaps if g.get("challenger_status")]
            status_counts = {s: statuses.count(s) for s in sorted(set(statuses))}
            _trace("Stage 5b — Gap Challenger",
                  f"{len(validated_gaps)} gaps",
                  ", ".join(f"{v} {k}" for k, v in status_counts.items())
                  or "no gaps reached a terminal status")

        progress("Stage 6 — Generating proposals…", 68)
        client.set_stage("Stage 6 — Proposals")
        proposals = generate_proposals(validated_gaps, wiki, context, client,
                                       domain_config=domain_cfg)
        _trace("Stage 6 — Proposals", f"{len(validated_gaps)} gaps", f"{len(proposals)} proposals")
        progress("Proposals complete", 75)
    else:
        progress("Quality gate FAILED — skipping gap analysis, saving fetched data…", 68)
        graph = {"stats": {"entity_count": 0, "relationship_count": 0}, "communities": []}
        graph_quality = None
        validated_gaps = []
        proposals = []
        _trace("Stage 3-6 — Skipped (quality gate FAIL)",
              f"{len(all_papers)} papers, {len(ref_papers)} refs",
              "; ".join(gate_block_reasons) or "corpus below quality threshold")
        progress("Saving fetched data", 75)

    corpus = assign_tiers(all_papers, ref_papers)

    results = {
        "papers": [
            {"filename": p["filename"], "wiki": w,
             "char_count": p.get("char_count", 0),
             "sections": p.get("sections", {}),
             "tables": p.get("tables", []),
             "tree_summary": tree_to_summary(t, max_chars=2000),
             "tier": 1}
            for p, w, t in zip(all_papers, wiki["pages"], all_trees)
        ],
        "wiki": wiki, "graph": graph, "graph_quality": graph_quality,
        "gaps": validated_gaps, "proposals": proposals,
        "communities": graph.get("communities", []),
        "context": context,
        "corpus_stats": corpus_stats(corpus),
        "ref_summary": summarise_reference_corpus(ref_papers),
        "ref_papers": ref_papers,
        "ref_diagnostics": ref_diagnostics,
        "ref_resolution_diagnostics": ref_resolution_diagnostics,
        "corpus_quality_metrics": corpus_quality_metrics,
        "evidence_objects": evidence_objects,
        "corpus": corpus,
        "pipeline_trace": trace_rows,
        "gate_blocked": gate_blocked,
        "gate_block_reasons": gate_block_reasons,
    }

    # Auto-save regardless of gate_blocked, so a FAIL-gated run's fetched
    # data is never lost (B23).
    saved_id = save_run(name, results)

    # Opt-in graph persistence. Skipped (not attempted) when gate_blocked --
    # that path's graph is an empty placeholder. A failure degrades to a
    # warning; it must never look like the run itself failed.
    if options.enable_graph_persistence and not gate_blocked:
        ok, msg = arcadedb_connect_ok()
        if ok:
            try:
                gsummary = save_graph_snapshot(saved_id, name, graph, quality=graph_quality)
                _trace("Graph Persistence (ArcadeDB)",
                      f"{gsummary['entity_count']} entities, {gsummary['relationship_count']} relationships",
                      f"Saved under run_id={saved_id[:8]}…")
            except Exception as e:
                warn(f"Graph persistence failed (run itself completed normally): {e}")
        else:
            warn(f"Graph not persisted -- {msg}")

    # Artifact + lineage + manifest. Always attempted, gate-blocked runs
    # included -- a FAIL-gated run is itself a real research event. Failure
    # degrades to a warning for the same reason as above.
    lineage = {"artifact_ids": []}
    try:
        record_artifact(
            artifact_id=f"pipeline:{saved_id}", artifact_type="pipeline",
            artifact_version=f"pipeline:{saved_id}",
            project_id=context.get("domain") or "default",
            content_hash=saved_id, run_id=saved_id,
        )
        lineage = record_run_lineage(
            run_id=saved_id,
            project_id=context.get("domain") or "default",
            papers=all_papers, wiki=wiki, ref_papers=ref_papers,
            evidence_objects=evidence_objects,
            graph=None if gate_blocked else graph,
            gaps=None if gate_blocked else validated_gaps,
            proposals=None if gate_blocked else proposals,
            tooling={
                "graph_builder": str(GRAPH_PERSISTENCE_VERSION) if options.enable_graph_persistence else None,
                "embedding_model": EMBEDDING_MODEL if options.enable_gap_challenger else None,
                "model_bundle": f"{options.provider_key}:{options.model}",
            },
            gate_blocked=gate_blocked,
        )
        record_run_manifest(
            run_id=saved_id,
            project_id=context.get("domain") or "default",
            git_commit=options.git_commit,
            parser_versions={
                "pymupdf": None,  # no formal version constant exists for this stage yet
                "docling": DOCLING_STAGE_VERSION if options.enable_quality_engine else None,
            },
            reference_resolver_version=str(REFERENCE_STAGE_VERSION),
            model_bundle_version=f"{options.provider_key}:{options.model}",
            embedding_model_version=EMBEDDING_MODEL if options.enable_gap_challenger else None,
            reranker_version=RERANK_MODEL if options.enable_gap_challenger else None,
            graph_version=str(GRAPH_PERSISTENCE_VERSION) if options.enable_graph_persistence else None,
            search_strategy_version=str(GAP_CHALLENGER_STAGE_VERSION) if options.enable_gap_challenger else None,
            academic_search_date=datetime.now().date().isoformat(),
            search_providers=["semantic_scholar", "arxiv"],
            output_artifacts=lineage["artifact_ids"],
            warnings=gate_block_reasons if gate_blocked else [],
            quality_gate_results={
                "corpus": corpus_quality_metrics.get("quality_gate") if corpus_quality_metrics else None,
                "graph": graph_quality.get("build_status") if graph_quality else None,
            },
            run_duration_seconds=round(time.time() - run_start, 1),
            token_usage=token_meter.to_manifest_dict() if token_meter else None,
        )
    except Exception as e:
        warn(f"Run Manifest not recorded (run itself completed normally): {e}")

    progress("Done", 80)

    return RunOutcome(
        results=results, run_id=saved_id, name=name,
        gate_blocked=gate_blocked, gate_block_reasons=gate_block_reasons,
        n_papers=len(all_papers), n_refs=len(ref_papers), n_evidence=total_evidence,
        n_gaps=len(validated_gaps), n_proposals=len(proposals),
        duration_seconds=round(time.time() - run_start, 1),
    )
