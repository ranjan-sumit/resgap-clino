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

from pipeline.literature_scout import scout_gaps
from pipeline.canonical_resolver import filter_and_dedupe_references
from pipeline.corpus_quality import (
    QualityGateBlockedError, compute_corpus_quality, enforce_quality_gate,
    score_paper_completeness,
)
from pipeline.deterministic_gap_patterns import detect_deterministic_gaps
from pipeline.docling_parser import DOCLING_STAGE_VERSION, extract_with_docling
from pipeline.evidence_extractor import extract_evidence_cached
from pipeline.evidence_reader import study_type_of
from pipeline.extraction_reconciler import reconcile_paper
from pipeline.gap_challenger import GAP_CHALLENGER_STAGE_VERSION, run_challenge
from pipeline.gap_agents import find_gaps
from pipeline.gap_detector import GapDetectionError, detect_gaps
from pipeline.graph_builder import build_knowledge_graph
from pipeline.graph_persistence import (
    GRAPH_PERSISTENCE_VERSION, connect_ok as graph_store_connect_ok, save_graph_snapshot,
)
from pipeline.graph_quality import apply_graph_quality_to_gaps, score_graph_quality
from pipeline.graph_structural_gaps import detect_graph_structural_gaps
from pipeline.lineage import record_run_lineage
from pipeline.page_index import build_tree, tree_to_summary
from pipeline.paper_manager import assign_tiers, corpus_stats
from pipeline.agent_config import agent_versions
from pipeline.feedback_context import build_feedback_context, get_feedback_items
from pipeline.run_quality import compute_run_quality
from pipeline.variance import calibration_report, compare_with_previous, self_preference_note
from pipeline.pdf_parser import check_pdf_readable, parse_pdf
from pipeline.proposal_generator import generate_proposals, review_proposals
from pipeline.reference_extractor import (
    REFERENCE_STAGE_VERSION, extract_and_enrich_references, summarise_reference_corpus,
)
from pipeline.relevance_ranking import EMBEDDING_MODEL, RERANK_MODEL
from pipeline.wiki_compiler import build_wiki
from utils.database import DEFAULT_PROJECT_ID, record_artifact, record_run_manifest, save_run
from utils import project_store


# The rule-based pattern library (TRIPOD/PROBAST-style items: external validation,
# calibration, fairness...) only makes sense for studies that build or test a model on patients.
_RULE_CHECK_STUDY_TYPES = ("ml_prediction_model", "clinical_trial", "observational_clinical")
# arXiv covers computing, physics and maths; for biomedical corpora it only adds noise and delay.
_ARXIV_STUDY_TYPES = ("ml_prediction_model", "computational_simulation")


def _dedupe_supplementary(gaps: list, max_items: int = 10) -> list:
    """Drop near-identical titles (graph templates like 'Unexplored concept: X' repeat) and cap the list."""
    import difflib
    kept = []
    for g in gaps:
        title = str(g.get("title", "")).lower()
        if any(difflib.SequenceMatcher(None, title, str(k.get("title", "")).lower()).ratio() > 0.85 for k in kept):
            continue
        kept.append(g)
        if len(kept) >= max_items:
            break
    return kept


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
    nvidia_api_key: str = ""              # relevance reranking in the Gap Challenger
    models: dict | None = None            # ModelConfig.to_dict(): which model did which job
    project_id: str | None = None         # None = the default project
    domain_config: dict | None = None
    git_commit: str | None = None
    token_cap: int | None = None          # stop the run when its estimated token use passes this
    min_gaps_per_paper: int = 0           # 0 = off; else promote gaps so every paper supports at least this many


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


def _model_bundle(options: "RunOptions") -> str:
    """One string naming every model a run used (the old single "provider:model"
    when no per-role assignment was given)."""
    models = options.models
    if not models:
        return f"{options.provider_key}:{options.model}"
    roles = models.get("roles") or {}
    parts = [f"{r}={roles[r]['provider']}:{roles[r]['model']}" for r in ("extraction", "wiki", "analysis") if r in roles]
    fb = models.get("fallback")
    if fb:
        parts.append(f"fallback={fb['provider']}:{fb['model']}")
    return "; ".join(parts)


def _noop(*_args, **_kwargs) -> None:
    return None


def redo_proposal_step(results: dict, context: dict, client, domain_config: dict | None = None) -> list:
    """Stage 6 (draft + review) alone, on a finished run's gaps. For a run whose proposal
    step failed: fills them in without repeating the whole analysis."""
    client.set_stage("Stage 6 — Proposals")
    gaps = results.get("gaps", [])
    proposals = generate_proposals(gaps, results.get("wiki", {}), context, client, domain_config=domain_config)
    if proposals:
        reviewed, _diag = review_proposals(proposals, gaps, client, domain_config=domain_config)
        proposals = reviewed or proposals
    return proposals


MIN_PAPERS = 2
MAX_PAPERS = 5


def prepare_papers(papers: list[tuple[str, bytes]]) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Makes the paper set explicit: identical files collapse to one, papers
    beyond MAX_PAPERS are named in a notice instead of vanishing, and two
    different papers sharing a filename get distinct names (the filename is the
    key for evidence and profiles downstream). Returns (papers, notices)."""
    import hashlib
    notices: list[str] = []
    seen: dict[str, str] = {}
    unique: list[tuple[str, bytes]] = []
    for filename, content in papers:
        sha = hashlib.sha256(content).hexdigest()
        if sha in seen:
            notices.append(f"'{filename}' is identical to '{seen[sha]}' and was analysed once.")
            continue
        seen[sha] = filename
        unique.append((filename, content))

    if len(unique) > MAX_PAPERS:
        dropped = [f for f, _ in unique[MAX_PAPERS:]]
        notices.append(f"Only the first {MAX_PAPERS} papers are analysed. Not analysed: "
                       + ", ".join(f"'{f}'" for f in dropped) + ".")
        unique = unique[:MAX_PAPERS]

    names = [f for f, _ in unique]
    result = []
    for filename, content in unique:
        if names.count(filename) > 1:
            stem, dot, ext = filename.rpartition(".")
            tag = hashlib.sha256(content).hexdigest()[:6]
            new = f"{stem or filename} [{tag}]{dot}{ext}" if dot else f"{filename} [{tag}]"
            notices.append(f"Two different papers were both named '{filename}'; "
                           f"this one is shown as '{new}'.")
            filename = new
        result.append((filename, content))
    return result, notices


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

    Every model call and every warning is recorded for the run (llm_calls.jsonl
    and the manifest). If the run dies midway, the call log is still written
    to the project's runs/_failed/ folder before the error propagates.
    """
    from utils.call_log import CallLog
    from utils.azure_client import AzureOpenAIClient
    from utils.model_router import ModelRouter
    secrets: list = []
    if isinstance(client, ModelRouter):
        secrets = list(client.keys.values())
    elif isinstance(client, AzureOpenAIClient):
        secrets = [client.api_key]
    call_log = CallLog(secrets=secrets)
    if isinstance(client, ModelRouter):
        client.call_log = call_log
    audit = {"call_log": call_log, "warnings": [], "budget": None}

    def _warn(msg: str) -> None:
        stage = client.current_stage if isinstance(client, ModelRouter) else None
        audit["warnings"].append({"stage": stage, "message": call_log.redact(msg)})
        warn(msg)

    from utils.cost_guard import TokenBudget
    budget = TokenBudget(options.token_cap, on_warn=_warn)
    audit["budget"] = budget
    if isinstance(client, ModelRouter):
        client.budget = budget

    def _progress(msg: str, pct: int) -> None:
        budget.check()                  # between stages: a passed cap stops the run here, cleanly
        progress(msg, pct)

    try:
        return _run_full_pipeline(papers, context, client, options, name, progress=_progress,
                                  trace=trace, warn=_warn, token_meter=token_meter, _audit=audit)
    except BaseException as e:
        _dump_failed_run_log(options, call_log, e)
        raise


def _repeatability_vs_previous(results: dict, project_id: str, look_back: int = 8) -> dict | None:
    """Overlap of this run's gaps with the most recent earlier run in the project on the same papers
    (None when there is none). Best effort: a failure here never touches the run."""
    try:
        from utils.database import list_runs, load_run
        for row in list_runs(limit=look_back, project_id=project_id):
            previous = load_run(row["id"], sections=False).get("results") or {}
            found = compare_with_previous(results, previous, row["id"])
            if found is not None:
                found["matches"] = found["matches"][:10]
                return found
    except Exception:
        return None
    return None


def _dump_failed_run_log(options, call_log, exc) -> None:
    """Best effort: a crash must not lose the record of what was called."""
    try:
        if not call_log.records:
            return
        folder = project_store.project_dir(options.project_id or DEFAULT_PROJECT_ID) / "runs" / "_failed"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (folder / f"{stamp}-llm_calls.jsonl").write_text(call_log.to_jsonl(), encoding="utf-8")
        (folder / f"{stamp}-error.txt").write_text(
            call_log.redact(f"{type(exc).__name__}: {exc}"), encoding="utf-8")
    except Exception:
        pass


def _run_full_pipeline(
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
    _audit: dict,
) -> RunOutcome:
    if len(papers) < MIN_PAPERS:
        raise PipelineInputError(
            f"Upload at least {MIN_PAPERS} papers (got {len(papers)}) -- gap detection "
            "compares papers against each other, so a single paper has nothing to compare to."
        )
    papers, _paper_notices = prepare_papers(papers)
    for _n in _paper_notices:
        warn(_n)
    if len(papers) < MIN_PAPERS:
        raise PipelineInputError(
            f"Only {len(papers)} distinct paper after removing duplicates; upload at least "
            f"{MIN_PAPERS} different papers.")
    project_id = options.project_id or DEFAULT_PROJECT_ID

    # Keep the uploaded papers in the project folder before anything else runs,
    # so they survive even if a later stage fails. A failure here must never
    # stop the analysis itself.
    paper_file_ids: list[int] = []
    try:
        paper_file_ids = project_store.save_papers(project_id, papers)
    except Exception as e:
        warn(f"Papers were not saved to the project folder (analysis continues): {e}")

    domain_cfg = options.domain_config
    run_start = time.time()
    name = (name or "").strip() or f"{context.get('domain', 'Run')[:20]} — {datetime.now().strftime('%H:%M')}"

    # The pipeline owns its own trace rows rather than relying on the
    # caller's callback to retain them: results["pipeline_trace"] is what
    # Run Detail's Stages tab reads, so a caller that passes no `trace`
    # callback (the API, a test) must still produce a run with a real
    # stage timeline. The callback is additionally invoked for live display.
    trace_rows: list[dict] = []

    _last_trace_at = [run_start]

    def _trace(stage: str, inputs: str, outputs: str, status: str = "✅") -> None:
        now = time.time()
        trace_rows.append({"stage": stage, "inputs": inputs, "outputs": outputs, "status": status,
                           "duration_s": round(now - _last_trace_at[0], 1)})   # time since the previous row
        _last_trace_at[0] = now
        trace(stage, inputs, outputs)

    all_papers, all_trees = [], []

    # ── Stage 1+2: Parse + PageIndex ──────────────────────────────────────
    progress("Stage 1 — Parsing PDFs & building PageIndex trees…", 5)
    # When the Corpus Quality Engine is enabled, Stage 2B needs each paper's
    # original PDF file (Docling operates on the file, not extracted text) --
    # keep the temp files alive until then instead of deleting here.
    paper_tmp_paths = []
    unreadable: list[tuple[str, str]] = []
    readable_papers: list[tuple[str, bytes]] = []
    try:
        for filename, content in papers:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            keep = False
            try:
                problem = check_pdf_readable(tmp_path)
                if problem:
                    unreadable.append((filename, problem))
                    warn(f"'{filename}' was skipped: {problem}.")
                    continue
                if options.use_vision:
                    client.set_stage("Stage 1 — Figure analysis")
                paper = parse_pdf(tmp_path, filename,
                                  client=client if options.use_vision else None,
                                  use_vision=options.use_vision,
                                  on_progress=lambda msg, _f=filename: progress(
                                      f"Stage 1 — Analysing figures in {_f} ({msg})…", 8))
                paper["tier"] = 1
                all_papers.append(paper)
                all_trees.append(build_tree(paper))
                readable_papers.append((filename, content))
                if options.enable_quality_engine:
                    paper_tmp_paths.append(tmp_path)
                    keep = True
            finally:
                if not keep:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
    except BaseException:
        for _p in paper_tmp_paths:       # a crash must not leave uploaded papers in the temp folder
            try:
                os.unlink(_p)
            except OSError:
                pass
        raise

    for _fn, _why in unreadable:
        _trace(f"  Skipped {_fn}", "PDF check", _why, "❌")
    if len(readable_papers) < MIN_PAPERS:
        for _p in paper_tmp_paths:
            try:
                os.unlink(_p)
            except OSError:
                pass
        raise PipelineInputError(
            f"Only {len(readable_papers)} of {len(papers)} papers could be read. "
            + " ".join(f"{fn}: {why}." for fn, why in unreadable))
    papers = readable_papers      # later stages index papers[i] alongside all_papers[i]

    _trace("Stage 1 — PDF Parse",
          f"{len(papers)} PDFs",
          f"{sum(p.get('char_count', 0) for p in all_papers):,} chars extracted")
    for p in all_papers:
        secs = [k for k, v in p.get("sections", {}).items() if k != "_header" and str(v).strip()]
        figs = p.get("figures") or []
        bad = sum(1 for f in figs if str(f.get("description", "")).startswith("["))
        fig_note = f", figures: {len(figs) - bad}/{len(figs)} analysed" if figs else ""
        _trace(f"  Parsed {p.get('filename', '?')}",
               f"{p.get('char_count', 0):,} chars",
               f"{len(secs)} sections, {len(p.get('tables', []))} tables{fig_note}",
               "✅" if len(secs) >= 2 and not bad else "⚠️")
    progress("Stage 1 complete", 12)

    # ── Stage 1B/1C: References ───────────────────────────────────────────
    ref_papers: list = []
    ref_diagnostics: dict = {}
    ref_resolution_diagnostics = None
    if options.extract_refs:
        progress("Stage 1B — Extracting & enriching references (50+ paper corpus)…", 14)
        client.set_stage("Stage 1B — Reference Extraction")

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
    for _w in wiki.get("warnings", []):
        _trace("  Wiki cross-links", "all pages", _w, "⚠️")
        warn(_w)
    for pg in wiki.get("pages", []):
        if not (pg.get("key_findings") or pg.get("contributions") or pg.get("methods")):
            _trace(f"  Wiki page for {pg.get('source_file', '?')}", "paper text",
                   "empty — the model returned no findings, contributions or methods", "⚠️")
    progress("Wiki complete", 34)

    # ── Stage 2B: Corpus Quality Engine (opt-in) ──────────────────────────
    corpus_quality_metrics = None
    # Per-paper field-level completeness. Kept at function scope (not inside
    # the Quality Engine branch) so it can be persisted below: app.py only
    # ever held these as a local and threw them away after aggregating, which
    # is why no screen could show WHICH field was missing from WHICH paper --
    # only the corpus-wide average. Stays None, never [], when the Quality
    # Engine was off, so "not measured" and "measured, all empty" remain
    # distinguishable downstream.
    paper_quality_scores: list[dict] | None = None
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
            progress(f"Stage 2B — Cross-checking paper {i+1}/{len(all_papers)} with the structural parser…", 35)
            wiki_page = wiki_pages[i] if i < len(wiki_pages) else {}
            docling_result = None
            try:
                docling_result = extract_with_docling(tmp_path, paper.get("filename", papers[i][0]))
                reconciled = reconcile_paper(paper, docling_result, paper.get("filename", ""))
            except Exception:
                # A second-parser failure degrades this paper's score rather than
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
        # Attach the filename each score belongs to. score_paper_completeness()
        # returns fields/counts but no identity, and the list's order is the
        # only thing tying a score to its paper -- an ordering dependency that
        # would not survive being stored and re-read.
        paper_quality_scores = [
            {**score, "filename": paper.get("filename", papers[i][0])}
            for i, (score, paper) in enumerate(zip(paper_scores, all_papers))
        ]
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
    client.set_stage("Stage 2C — Evidence Extraction")
    evidence_objects: dict = {}
    paper_profiles: dict = {}
    total_evidence = 0

    def _read_one(i_paper):
        i, paper = i_paper
        wiki_page = wiki_pages[i] if i < len(wiki_pages) else {}
        docling_result = docling_results[i] if i < len(docling_results) else None
        if not docling_result and paper.get("text_segments"):
            # The page-tagged text from Stage 1 is what the Evidence Reader reads and
            # what gives every quote a real page and section.
            docling_result = {"text_segments": paper["text_segments"]}
        filename = paper.get("filename", f"paper_{i+1}")
        try:
            evidence_dicts, diag, _ = extract_evidence_cached(
                filename, wiki_page, docling_result, client=client, use_llm=True,
            )
        except Exception:
            # Evidence extraction is additive, not load-bearing.
            evidence_dicts, diag = [], {}
        return filename, evidence_dicts, diag

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, min(len(all_papers), 4))) as pool:
        reads = list(pool.map(_read_one, enumerate(all_papers)))
    for filename, evidence_dicts, diag in reads:
        evidence_objects[filename] = evidence_dicts
        total_evidence += len(evidence_dicts)
        reader = (diag or {}).get("reader") or {}
        paper_profiles[filename] = {"study_type": study_type_of(evidence_dicts),
                                    "quoted_items": sum(1 for e in evidence_dicts if (e.get("provenance") or {}).get("quote"))}
        if reader and not reader.get("usable"):
            _trace(f"  Evidence for {filename}", "paper text",
                   f"reader could not run ({reader.get('error')}); used the wiki summary instead", "⚠️")

    n_quoted = sum(p["quoted_items"] for p in paper_profiles.values())
    _trace("Stage 2C — Evidence Extraction",
          f"{len(all_papers)} papers",
          f"{total_evidence} evidence objects, {n_quoted} with a verified quote and page "
          f"(study types: " + ", ".join(f"{p['study_type'] or '?'}" for p in paper_profiles.values()) + ")")

    # ── Stages 3-6 (skipped entirely on a FAIL gate) ──────────────────────
    if not gate_blocked:
        progress("Stage 3 — Building knowledge graph (LazyGraphRAG)…", 36)
        client.set_stage("Stage 3 — Knowledge Graph")
        graph = build_knowledge_graph(wiki, client, domain_config=domain_cfg,
                                      evidence_objects=evidence_objects)
        graph_quality = score_graph_quality(graph, wiki)
        _gd = graph.get("diagnostics", {})
        _trace("Stage 3 — Knowledge Graph",
              "Quoted evidence" if _gd.get("grounded") else "Wiki pages + cross-links",
              f"{graph['stats']['entity_count']} entities, "
              f"{graph['stats']['relationship_count']} relationships "
              f"— {graph_quality['build_status']} (quality={graph_quality['quality_score']})"
              + (f"; every relationship cites its quote; orphans {_gd.get('orphans_remaining', 0)} "
                 f"({_gd.get('orphan_share', 0):.0%}) after linking" if _gd.get("grounded") else
                 (f"; evidence-based graph not used: {_gd['grounded_failure']}" if _gd.get("grounded_failure") else "")))
        progress("Graph complete", 48)

        progress("Stage 4 — Finding research gaps (finder agents + critic)…", 50)
        client.set_stage("Stage 4 — Gap Detection")
        gap_detection_error = None
        # What this project's user said about earlier gaps steers the critic, the ranking and the reviewer.
        try:
            _fb_items = get_feedback_items(project_id, "all", max_items=30)
            _fb_text = build_feedback_context(project_id, "agent")
        except Exception as e:                      # feedback is a bonus: never stop a run for it
            _fb_items, _fb_text = [], ""
            warn(f"Earlier feedback could not be read ({e}).")
        agent_out = find_gaps(wiki, graph, context, client, evidence_objects, paper_profiles,
                              feedback_items=_fb_items, feedback_text=_fb_text,
                              min_gaps_per_paper=options.min_gaps_per_paper)
        gaps = agent_out["gaps"]
        rejected_gaps = agent_out["rejected"]
        agent_diag = agent_out["diagnostics"]
        _trace("Stage 4 — Gap agents",
               f"{len(evidence_objects)} papers' quoted evidence, 3 finder lenses",
               f"{agent_diag.get('candidates', 0)} grounded candidates -> {len(agent_out['gaps'])} kept by the critic, "
               f"{len(rejected_gaps)} merged/dropped"
               + (f"; critic: {agent_diag['critic_error']}" if agent_diag.get("critic_error") else ""),
               "⚠️" if agent_diag.get("critic_error") else "✅")
        if _fb_items:
            _adj = agent_diag.get("feedback_adjusted", [])
            _trace("  Feedback applied", f"{len(_fb_items)} earlier rating(s) in this project",
                   f"{sum(1 for a in _adj if a['change'] < 0)} gap(s) ranked lower, "
                   f"{sum(1 for a in _adj if a['change'] > 0)} higher; ratings also sent to the critic and reviewer")
        for _t in agent_diag.get("papers_without_gaps", []):
            warn(f"No gap rests on “{_t}”. The final list is built from the other papers.")
            _trace("  Paper coverage", "gap support per paper", f"“{_t}” supports no gap", "⚠️")
        for _pr in agent_diag.get("promoted_for_coverage", []):
            _trace("  Paper coverage", f"minimum {options.min_gaps_per_paper} gap(s) per paper",
                   f"promoted “{_pr['title'][:60]}” so {_pr['paper']} is represented")
        for fd in agent_diag.get("finders", []):
            if fd.get("error"):
                _trace(f"  Gap finder: {fd['lens']}" + (f" ({fd['paper']})" if fd.get("paper") else ""),
                       "evidence brief", fd["error"], "⚠️")
        if not gaps:
            # Agents produced nothing usable (all calls failed or nothing grounded): fall back to
            # the single-call detector so a run is not left without gaps by one bad round of calls.
            client.set_stage("Stage 4 — Gap Detection")
            try:
                gaps = detect_gaps(wiki, graph, context, client, domain_config=domain_cfg,
                                   evidence_objects=evidence_objects)
                gap_detection_error = "gap agents returned nothing; used the single-call detector"
            except GapDetectionError as e:
                gap_detection_error = str(e)
                warn(f"Gap detection failed ({e}).")
                gaps = []
        # Supplementary candidates, kept OUT of the main gap list: rule-based checks only for
        # papers whose study type they fit (a review or a lab study has no calibration curve),
        # and graph-structure hints, de-duplicated. They are shown separately and are not
        # validated or turned into proposals.
        applicable = {pid: ev for pid, ev in evidence_objects.items()
                      if (paper_profiles.get(pid) or {}).get("study_type") in _RULE_CHECK_STUDY_TYPES}
        det_gaps = detect_deterministic_gaps(applicable, context.get("domain", "")) if applicable else []
        graph_gaps = detect_graph_structural_gaps(graph)
        supplementary_gaps = _dedupe_supplementary(det_gaps + graph_gaps)
        for g in supplementary_gaps:
            g["supplementary"] = True
        if not gaps:
            # Last resort: neither the agents nor the single-call detector produced a gap, so
            # promote the rule-based and graph-structure leads (ungated) rather than end the run
            # with nothing. They are marked as degraded so nobody mistakes them for findings.
            lead_gaps = _dedupe_supplementary(
                detect_deterministic_gaps(evidence_objects, context.get("domain", "")) + graph_gaps)
            for g in lead_gaps:
                g["degraded_source"] = True
            gaps, supplementary_gaps = lead_gaps, []
            warn("No gaps came from the model-based detectors; showing rule-based and graph-structure leads instead.")
        if gap_detection_error:
            _trace("Stage 4 — Gap Detection (fallback)", "gap agents", gap_detection_error, status="⚠️")
        # FR-7: a DEGRADED/FALLBACK graph downgrades confidence for gaps
        # whose entire evidentiary basis is that graph.
        gaps = apply_graph_quality_to_gaps(gaps, graph_quality)

        progress("Stage 5 — Checking gaps against the literature (Semantic Scholar + Europe PMC)…", 58)
        client.set_stage("Stage 5 — Gap Validation")
        _study_types = {(p or {}).get("study_type") for p in paper_profiles.values()}
        scout_out = scout_gaps(
            gaps, client, domain_config=domain_cfg,
            ss_api_key=(options.ss_api_key or "").strip(),
            use_arxiv=bool(_study_types & set(_ARXIV_STUDY_TYPES)),
            progress_callback=lambda done, total: progress(
                f"Stage 5 — Checking gaps against the literature: {done + 1} of {total}…",
                58 + int(8 * done / max(total, 1))))
        validated_gaps = scout_out["gaps"]
        scout_diag = scout_out["diagnostics"]
        _by_status = {}
        for g in validated_gaps:
            _by_status[g.get("validation_status")] = _by_status.get(g.get("validation_status"), 0) + 1
        _trace("Stage 5 — Literature check",
               f"{len(validated_gaps)} gaps, queries written by a planner agent",
               ", ".join(f"{n} {s}" for s, n in sorted(_by_status.items(), key=lambda kv: str(kv[0])))
               + (f"; {scout_diag['cache_hits']} from cache" if scout_diag.get("cache_hits") else "")
               + (f"; WARNING: {scout_diag['unverified']} could not be checked (search unavailable)"
                  if scout_diag.get("unverified") else "")
               + (f"; {scout_diag['planner_error']}" if scout_diag.get("planner_error") else ""),
               "⚠️" if scout_diag.get("unverified") or scout_diag.get("planner_error") else "✅")
        _trace("Stage 4-5 — Gaps",
              "Top-ranked agent gaps"
              + (f" (+{len(supplementary_gaps)} supplementary, not validated)" if supplementary_gaps else ""),
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
                        nvidia_api_key=(options.nvidia_api_key or "").strip(),
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
        _had_actionable = any(g.get("validation_status") in ("open", "partial", "unverified") for g in validated_gaps)
        if proposals:
            _trace("Stage 6 — Proposals", f"{len(validated_gaps)} gaps", f"{len(proposals)} drafted")
            progress("Stage 6b — Reviewing proposals…", 72)
            drafted = len(proposals)
            reviewed, review_diag = review_proposals(proposals, validated_gaps, client, domain_config=domain_cfg,
                                                   feedback_text=_fb_text)
            if reviewed:
                proposals = reviewed
            else:
                review_diag["error"] = (review_diag.get("error") or "") + " every proposal was rejected: kept the originals"
            _trace("Stage 6b — Proposal Review", f"{drafted} drafted proposals",
                   f"{len(proposals)} kept: {review_diag['accepted']} accepted, {review_diag['revised']} revised, "
                   f"{len(review_diag['rejected'])} rejected"
                   + (f" ({'; '.join(r['title'] + ': ' + r['reason'] for r in review_diag['rejected'][:3])})"
                      if review_diag["rejected"] else "")
                   + (f"; {review_diag['error']}" if review_diag.get("error") else ""),
                   "⚠️" if review_diag.get("error") else "✅")
        elif not _had_actionable:
            _trace("Stage 6 — Proposals", f"{len(validated_gaps)} gaps", "0 proposals (no open or partial gaps)")
        else:
            _trace("Stage 6 — Proposals", f"{len(validated_gaps)} gaps",
                   "0 proposals even though open gaps exist: the model's reply could not be read. "
                   "Run again, or pick a different Analysis model.", "⚠️")
        progress("Proposals complete", 75)
    else:
        progress("Quality gate FAILED — skipping gap analysis, saving fetched data…", 68)
        graph = {"stats": {"entity_count": 0, "relationship_count": 0}, "communities": []}
        graph_quality = None
        validated_gaps = []
        supplementary_gaps, rejected_gaps, agent_diag = [], [], {}
        proposals = []
        _trace("Stage 3-6 — Skipped (quality gate FAIL)",
              f"{len(all_papers)} papers, {len(ref_papers)} refs",
              "; ".join(gate_block_reasons) or "corpus below quality threshold")
        progress("Saving fetched data", 75)

    corpus = assign_tiers(all_papers, ref_papers)

    # build_wiki() contract: one page per parsed paper. zip() would silently
    # truncate results["papers"] if that invariant ever broke -- say so
    # loudly instead of dropping papers from a saved run.
    if len(wiki["pages"]) != len(all_papers):
        raise RuntimeError(
            f"Wiki page count ({len(wiki['pages'])}) does not match parsed paper count "
            f"({len(all_papers)}) -- refusing to silently drop papers from the run's results."
        )

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
        "supplementary_gaps": supplementary_gaps,
        "rejected_gaps": rejected_gaps,
        "gap_agent_diagnostics": agent_diag,
        "communities": graph.get("communities", []),
        "context": context,
        "corpus_stats": corpus_stats(corpus),
        "ref_summary": summarise_reference_corpus(ref_papers),
        "ref_papers": ref_papers,
        "ref_diagnostics": ref_diagnostics,
        "ref_resolution_diagnostics": ref_resolution_diagnostics,
        "corpus_quality_metrics": corpus_quality_metrics,
        "paper_quality_scores": paper_quality_scores,
        "evidence_objects": evidence_objects,
        "paper_profiles": paper_profiles,
        "corpus": corpus,
        "pipeline_trace": trace_rows,
        "models": options.models,
        # Calls where the chosen model failed and the fallback answered (empty
        # when the client is a plain single-model one).
        "model_fallbacks": list(getattr(client, "fallback_events", []) or []),
        "gate_blocked": gate_blocked,
        "gate_block_reasons": gate_block_reasons,
        "agent_versions": agent_versions(),
    }
    # Are the judges discriminating, is the same model marking its own work, and does this run agree
    # with an earlier run on the same papers? (pipeline/variance.py)
    if not gate_blocked:
        results["calibration"] = calibration_report(validated_gaps, proposals)
        for _w in results["calibration"]["warnings"]:
            _trace("  Judge calibration", "critic and reviewer scores", _w, "⚠️")
            warn(_w)
        _self_note = self_preference_note(client.config) if hasattr(client, "config") else None
        if _self_note:
            _trace("  Judge independence", "critic and reviewer model", _self_note, "⚠️")
        results["repeatability"] = _repeatability_vs_previous(results, project_id)
        if results["repeatability"]:
            _rp = results["repeatability"]
            _trace("  Repeatability", f"vs the previous run on these papers ({_rp['n_previous']} gaps)",
                   f"{_rp['overlap']:.0%} of distinct gaps found by both runs ({_rp['matched']} matched)")
    results["run_quality"] = compute_run_quality(
        results, duration_seconds=round(time.time() - run_start, 1),
        call_summary=_audit["call_log"].summary(), tokens_estimated=_audit["budget"].used)

    # Auto-save regardless of gate_blocked, so a FAIL-gated run's fetched
    # data is never lost (B23).
    if results["model_fallbacks"]:
        n_fb = len(results["model_fallbacks"])
        warn(f"{n_fb} call(s) used the fallback model because the chosen model failed "
             f"(first: {results['model_fallbacks'][0]['from']} -> {results['model_fallbacks'][0]['to']}).")

    saved_id = save_run(name, results, project_id=project_id)

    # Opt-in graph persistence. Skipped (not attempted) when gate_blocked --
    # that path's graph is an empty placeholder. A failure degrades to a
    # warning; it must never look like the run itself failed.
    if options.enable_graph_persistence and not gate_blocked:
        ok, msg = graph_store_connect_ok()
        if ok:
            try:
                gsummary = save_graph_snapshot(saved_id, name, graph, quality=graph_quality)
                _trace("Graph Persistence (SQLite)",
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
            project_id=project_id,
            content_hash=saved_id, run_id=saved_id,
        )
        lineage = record_run_lineage(
            run_id=saved_id,
            project_id=project_id,
            papers=all_papers, wiki=wiki, ref_papers=ref_papers,
            evidence_objects=evidence_objects,
            graph=None if gate_blocked else graph,
            gaps=None if gate_blocked else validated_gaps,
            proposals=None if gate_blocked else proposals,
            tooling={
                "graph_builder": str(GRAPH_PERSISTENCE_VERSION) if options.enable_graph_persistence else None,
                "embedding_model": EMBEDDING_MODEL if options.enable_gap_challenger else None,
                "model_bundle": _model_bundle(options),
            },
            gate_blocked=gate_blocked,
        )
        record_run_manifest(
            run_id=saved_id,
            project_id=project_id,
            git_commit=options.git_commit,
            parser_versions={
                "pymupdf": None,  # no formal version constant exists for this stage yet
                "docling": DOCLING_STAGE_VERSION if options.enable_quality_engine else None,
            },
            reference_resolver_version=str(REFERENCE_STAGE_VERSION),
            model_bundle_version=_model_bundle(options),
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

    # Write the run's artifacts (results, report, manifest) into the project
    # folder. Best-effort for the same reason as above: the run is already saved.
    try:
        project_store.write_run_artifacts(
            project_id, saved_id, results, context, paper_file_ids=paper_file_ids,
            manifest={
                "run_name": name,
                "model": _model_bundle(options),
                "models": options.models,
                "model_fallbacks": results["model_fallbacks"],
                "options": {
                    "use_vision": options.use_vision, "extract_refs": options.extract_refs,
                    "ref_limit": options.ref_limit,
                    "quality_check": options.enable_quality_engine,
                    "deep_gap_validation": options.enable_gap_challenger,
                },
                "gate_blocked": gate_blocked,
                "duration_seconds": round(time.time() - run_start, 1),
                "run_quality": results["run_quality"],
                "agent_versions": results["agent_versions"],
                "token_cap": options.token_cap,
                "llm_call_summary": _audit["call_log"].summary(),
                "llm_call_errors": _audit["call_log"].failures()[:100],
                "warnings": _audit["warnings"],
            },
            call_log_jsonl=_audit["call_log"].to_jsonl(),
        )
    except Exception as e:
        warn(f"Run artifacts were not written to the project folder (run itself completed normally): {e}")

    progress("Done", 80)

    return RunOutcome(
        results=results, run_id=saved_id, name=name,
        gate_blocked=gate_blocked, gate_block_reasons=gate_block_reasons,
        n_papers=len(all_papers), n_refs=len(ref_papers), n_evidence=total_evidence,
        n_gaps=len(validated_gaps), n_proposals=len(proposals),
        duration_seconds=round(time.time() - run_start, 1),
    )

