"""
Research Gap Analyzer (Clinova Research Intelligence Platform)
An AI-powered tool for identifying research gaps across academic papers.
Architecture: LLM Wiki + PageIndex + LazyGraphRAG + Academic Validation
"""
import streamlit as st
import tempfile
import os
import json
import time
import html
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader -- avoids adding python-dotenv as a new dependency.
    Existing real environment variables always win (matches the same helper
    already used across evals/benchmarks/baseline/*.py)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() and k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip()


_load_dotenv(Path(__file__).parent / ".env")


# Clinova Phase 4, Epic 4.2 (Run Manifest, FR-23's `git_commit` field).
# Computed once per process, not per run -- the commit doesn't change
# mid-session. Honest None (not a fake value) if git isn't on PATH or this
# isn't a git checkout, rather than a placeholder that looks like a hash.
def _git_commit() -> str | None:
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


_GIT_COMMIT = _git_commit()

# Clinova Phase 1, Story 1.4.2: product name/tagline live in the branding
# config layer (03-system-architecture.md AD-3), not hardcoded here -- the
# product identity can change without touching this file. Falls back to the
# pre-Clinova name if the config is ever missing (defensive, not expected).
def _load_branding() -> dict:
    try:
        theme_path = Path(__file__).parent / "packages" / "branding" / "theme.json"
        theme = json.loads(theme_path.read_text(encoding="utf-8"))
        return {"product_name": theme.get("product_name", "Research Gap Analyzer"),
                "tagline": theme.get("tagline", "")}
    except Exception:
        return {"product_name": "Research Gap Analyzer", "tagline": ""}

_BRANDING = _load_branding()

# ── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title=(f'{_BRANDING["product_name"]} — {_BRANDING["tagline"]}'
                if _BRANDING["tagline"] else _BRANDING["product_name"]),
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="auto",        # open on wide screens, collapsed on phones (an open sidebar covers the page)
)

# ── Theme (stylesheet lives in ui/theme.py) ─────────────────────────────────
from ui.theme import apply_theme
apply_theme()

# ── Imports ───────────────────────────────────────────────────────────────────
import streamlit as st
import tempfile, os, json, traceback
from datetime import datetime

from utils.azure_client import AzureOpenAIClient, MASTER_MODEL, FALLBACK_MODEL
from utils.model_providers import PROVIDER_REGISTRY
from utils.model_router import (
    ModelRouter, ModelSpec, ModelConfig, ALL_ROLES, MAIN_ROLES, COUNCIL_ROLES, ROLE_LABELS, ROLE_HELP,
    ROLE_EXTRACTION, ROLE_ANALYSIS, CUSTOM_PROVIDER, run_model_tests, fetch_models, can_read_images,
)
from utils.model_settings import load_config, save_config, recommend, explain, BENCHMARK
from utils.export import (
    to_json, to_markdown_report, to_pdf_report,
    generate_report_narrative, to_enterprise_html_report,
    to_enterprise_pdf_report,
)
from utils.database import (
    init_db, save_run, list_runs, load_run, delete_run, get_run_row,
    record_artifact, record_run_manifest, get_run_manifest,
    DEFAULT_PROJECT_ID, list_projects, get_project, list_feedback, upsert_feedback,
    list_project_files, attach_comp_results, update_run_proposals,
)
from utils import project_store, run_jobs
from utils.run_jobs import start_job
from pipeline.feedback_context import POSITIVE_REASONS, NEGATIVE_REASONS
from pipeline import pdf_limits
from pipeline.pdf_parser import parse_pdf
from utils.backup import backup_bytes
from pipeline.page_index import build_tree, tree_to_summary
from pipeline.wiki_compiler import build_wiki
from pipeline.graph_builder import build_knowledge_graph
from pipeline.deterministic_gap_patterns import detect_deterministic_gaps
from pipeline.graph_structural_gaps import detect_graph_structural_gaps
from pipeline.graph_quality import score_graph_quality, apply_graph_quality_to_gaps
from pipeline.gap_challenger import run_challenge, GAP_CHALLENGER_STAGE_VERSION
from pipeline.repeatability_score import compute_repeatability_score
from pipeline.run_compare import compare_runs
from pipeline.lineage import record_run_lineage, get_technical_lineage, get_scientific_lineage
from utils.token_meter import TokenMeter
from pipeline.graph_persistence import (
    connect_ok as graph_store_connect_ok, save_graph_snapshot, load_graph_snapshot,
    list_graph_snapshots, diff_graph_snapshots, GRAPH_PERSISTENCE_VERSION,
)
from pipeline.coverage import paper_coverage
from pipeline.run_lab import run_computational_lab
from pipeline.param_extractor import (
    extract_parameters, derive_cross_paper_parameters,
    check_sufficiency, params_to_csv, group_params_by_category,
)
from pipeline.reference_extractor import (
    extract_and_enrich_references, summarise_reference_corpus, REFERENCE_STAGE_VERSION,
)
from pipeline.paper_manager import (
    assign_tiers, corpus_stats, compile_tier2_batch,
    extract_tier2_parameters, TIER_LABELS,
)
from pipeline.discovery_engine import run_discovery_engine
from pipeline.llm_council import council_select_model, council_synthesise_insights
from pipeline.simulation_engine import run_simulation, filter_confident_params, resolve_models_to_run
from pipeline.multi_run import run_multi_council
# Clinova Phase 5, Epic 5.6 -- the Stage 1-6 orchestration formerly inline
# in this file. Extracted so the FastAPI app can run the identical
# pipeline; this file injects its Streamlit progress/trace/warning
# callbacks into it, so behaviour here is unchanged.
from pipeline.run_pipeline import PipelineInputError, RunOptions, redo_proposal_step, run_full_pipeline
from pipeline.doc_generator import build_zip
from domain_config import get_ui_domain_choices, get_domain_config
# Clinova Phase 1 (Epics 1.2-1.3) -- opt-in Corpus Quality Engine + canonical
# reference resolution. Not imported into the always-on Stage 1-6 flow
# above: the second parser (docling_parser.py, now PyMuPDF-based -- Docling
# was removed for its ~5.8GB torch/CUDA footprint) stays behind the
# "enable_quality_engine" sidebar toggle so the extra pass and quality gate
# are not silently added to every run.
from pipeline.docling_parser import extract_with_docling, DOCLING_STAGE_VERSION
from pipeline.extraction_reconciler import reconcile_paper
from pipeline.corpus_quality import (
    score_paper_completeness, compute_corpus_quality, enforce_quality_gate,
    QualityGateBlockedError,
)
from pipeline.canonical_resolver import filter_and_dedupe_references
from pipeline.evidence_extractor import extract_evidence_cached

# Initialise DB on startup
init_db()

# ── Session state ─────────────────────────────────────────────────────────────
_DEFAULTS = {
    "results":        None,
    "running":        False,
    "comp_results":   None,
    "pipeline_trace": [],
    "ref_papers":     [],    # enriched reference paper list
    "ref_diagnostics": {},
    "corpus":         [],    # full corpus (Tier 1 + Tier 2 + Tier 3)
    "loaded_run_id":  None,  # which saved run is currently displayed
    "report_bundle":  None,
    "current_run_name": "",
    "current_run_id": None,
    "current_project_id": DEFAULT_PROJECT_ID,   # the project new runs are saved to
    "project_select": DEFAULT_PROJECT_ID,       # the sidebar picker's widget state
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Helpers ───────────────────────────────────────────────────────────────────
from ui.viewmodels import (keys_line, off_note, overview, run_header, saved_trace, trace_summary,
                           trace_rows, stage_status)
from ui.compat import plotly_full_width, table_full_width
from ui.run_board import board_rows
from utils.export import ALL_SECTION_IDS, REPORT_SECTIONS
from ui.lab_view import kind_badge, lab_verdict, parameters_by_paper
from ui.graph_view import filter_relations, grounding_summary, orphan_explanation, relation_rows
from ui.gaps_view import (SORTS as GAP_SORTS, compare_proposals, filter_gaps, gap_rows, proposal_rows,
                          sort_gaps)
from ui.evidence_view import (citation, evidence_rows, filter_evidence, match_evidence, paper_titles,
                              quality_chips, study_type_label, top_gaps, top_proposal, warnings_summary)
import hashlib
from utils.run_storage import to_local_display
from utils.database import with_sections, cache_stats as db_cache_stats, clear_cache as db_clear_cache, _db_path as db_path_for_display
from utils.database import get_run_manifests_bulk, load_run_gate_fields_bulk, set_run_archived
from utils.run_management import (best_to_keep, delete_project as delete_project_everywhere, deleted_folder_footprint,
                                  empty_deleted_folder, erase_on_delete,
                                  delete_run as delete_run_everywhere, find_duplicate_groups, merge_runs,
                                  project_footprint, rename_run, run_footprint,
                                  update_project as update_project_settings)
from utils.cost_guard import DEFAULT_CAP_TOKENS, describe_estimate, estimate_cost, estimate_run


@st.cache_data(show_spinner=False, max_entries=64, ttl=3600)     # capped: one small number per file, but never unbounded
def _pdf_text_chars(_sha: str, data: bytes) -> int:
    """Characters of text in a PDF (cached per file), for the pre-run estimate."""
    try:
        import fitz
        with fitz.open(stream=data, filetype="pdf") as doc:
            return sum(len(page.get_text()) for page in doc)
    except Exception:
        return len(data) // 10


def _local_time(ts: str) -> str:
    """A stored UTC timestamp in the viewer's own time zone (the browser's, when Streamlit knows it)."""
    return to_local_display(ts, getattr(st.context, "timezone", None))

from ui.glossary import lookup as glossary_lookup
from utils.provider_policy import provider_allowed
from ui.messages import show_error, show_info, show_warning
from ui.components import (esc, collapse_sidebar_on_phones, empty_state, error_state, loading_state, badge as _badge, tier_badge as _tier_badge, card as _card,
                           section_label as _section_label, item as _item, skeleton as _skeleton)


def _free_report_bytes(keep_run_id: str | None = None) -> None:
    """Drop a generated report (HTML and PDF bytes, often megabytes) unless it belongs to the run now on screen."""
    bundle = st.session_state.get("report_bundle")
    if bundle and bundle.get("run_id") != keep_run_id:
        st.session_state.report_bundle = None


def _load_run_into_session(run_id: str, run_name: str) -> bool:
    """Make a saved run the one on screen. Returns False if it has no results
    (nothing is changed in that case)."""
    loaded = load_run(run_id, sections=False)      # section text is only needed by the Lab; added then
    if not loaded.get("results"):
        return False
    _free_report_bytes(keep_run_id=run_id)
    st.session_state.results      = loaded["results"]
    st.session_state.comp_results = loaded.get("comp_results")
    st.session_state.ref_papers   = loaded["results"].get("ref_papers", [])
    st.session_state.ref_diagnostics = loaded["results"].get("ref_diagnostics", {})
    st.session_state.corpus       = loaded["results"].get("corpus", loaded["results"].get("papers", []))
    st.session_state.loaded_run_id = run_id
    st.session_state.current_run_id = run_id
    st.session_state.current_run_name = run_name
    return True


def _clear_results() -> None:
    """Nothing on screen (e.g. after switching to a project with no runs)."""
    _free_report_bytes()
    st.session_state.results = None
    st.session_state.comp_results = None
    st.session_state.ref_papers = []
    st.session_state.ref_diagnostics = {}
    st.session_state.corpus = []
    st.session_state.loaded_run_id = None
    st.session_state.current_run_id = None
    st.session_state.current_run_name = ""


def _switch_project(project_id: str) -> None:
    """Make `project_id` current and show its most recent run (or nothing)."""
    st.session_state.current_project_id = project_id
    latest = list_runs(limit=1, project_id=project_id)
    if not (latest and _load_run_into_session(latest[0]["id"], latest[0]["name"])):
        _clear_results()


def _on_project_change() -> None:
    _switch_project(st.session_state["project_select"])


# Open every new session on the most recent saved run -- and the project that
# run belongs to -- so its results are already on screen. Session state is per
# browser tab and is empty after a refresh, but the run itself is persisted.
# Done once per session: after that, whatever the user loads or runs stays in
# control.
if not st.session_state.get("_latest_run_checked"):
    st.session_state["_latest_run_checked"] = True
    if st.session_state.results is None and not st.session_state.running:
        _latest = list_runs(limit=1)
        if _latest:
            _load_run_into_session(_latest[0]["id"], _latest[0]["name"])
            st.session_state.current_project_id = _latest[0].get("project_id") or DEFAULT_PROJECT_ID
            st.session_state["project_select"] = st.session_state.current_project_id


@st.dialog("New project")
def _new_project_dialog() -> None:
    name = st.text_input("Project name", placeholder="e.g., Cystic fibrosis review")
    description = st.text_area("Description (optional)", height=80,
                               placeholder="What this project is about")
    st.caption("A folder is created for the project. The papers you upload, each run's results and "
               "reports, and your feedback are saved there and in the database.")
    if st.button("Create project", type="primary"):
        try:
            project = project_store.create_project(name, description)
        except ValueError as e:
            show_error(str(e))
            return
        _clear_results()                          # a new project starts empty
        st.session_state.current_project_id = project["id"]
        st.session_state["_pending_project"] = project["id"]   # applied to the picker on the next run
        st.rerun()


def _add_trace(stage, inp, out, status="✅"):
    st.session_state.pipeline_trace.append(
        {"stage": stage, "inputs": inp, "outputs": out, "status": status}
    )

# ── Models: which provider and model does which job ───────────────────────────
# The assignment lives in st.session_state["model_config"] (a ModelConfig, saved
# to data/model_settings.json -- never any keys). The widgets mirror it under the
# keys mp_<role> (provider), mm_<role> (model) and mc_<role> (typed custom id);
# every change goes through _on_model_change, which rebuilds and saves the config.

_NO_FALLBACK = "(none)"
_CUSTOM_MODEL = "Custom…"
_MODEL_ROWS = list(ALL_ROLES) + ["fallback"]


def _provider_name(pk: str) -> str:
    return "Custom endpoint" if pk == CUSTOM_PROVIDER else PROVIDER_REGISTRY[pk].label.split(" (")[0]


def _provider_options(role: str) -> list:
    options = [pk for pk in (*PROVIDER_REGISTRY, CUSTOM_PROVIDER) if provider_allowed(pk)]
    return [_NO_FALLBACK] + options if role == "fallback" else options


def _provider_label(pk: str) -> str:
    if pk == _NO_FALLBACK:
        return "No fallback"
    return _provider_name(pk) + ("" if pk in st.session_state.get("_available_providers", set()) else " (no key)")


def _model_choices(pk: str) -> list:
    if pk == _NO_FALLBACK:
        return []
    known = [] if pk == CUSTOM_PROVIDER else list(PROVIDER_REGISTRY[pk].known_models)
    live = st.session_state.get("_fetched_models", {}).get(pk, [])
    return known + [m for m in live if m not in known]


def _default_model(pk: str) -> str:
    return "" if pk == CUSTOM_PROVIDER else PROVIDER_REGISTRY[pk].default_model


def _set_widget_state(cfg: ModelConfig) -> None:
    for role in _MODEL_ROWS:
        spec = cfg.fallback if role == "fallback" else cfg.spec_for(role)
        if spec is None:
            st.session_state[f"mp_{role}"], st.session_state[f"mm_{role}"], st.session_state[f"mc_{role}"] = _NO_FALLBACK, "", ""
            continue
        st.session_state[f"mp_{role}"] = spec.provider
        if spec.model in _model_choices(spec.provider):
            st.session_state[f"mm_{role}"], st.session_state[f"mc_{role}"] = spec.model, ""
        else:
            st.session_state[f"mm_{role}"], st.session_state[f"mc_{role}"] = _CUSTOM_MODEL, spec.model


def _spec_from_widgets(role: str):
    pk = st.session_state.get(f"mp_{role}")
    if pk in (None, _NO_FALLBACK):
        return None
    choice = st.session_state.get(f"mm_{role}", "")
    model = (st.session_state.get(f"mc_{role}", "") if choice == _CUSTOM_MODEL else choice).strip() or _default_model(pk)
    if not model:
        return None
    return ModelSpec(pk, model, st.session_state.get("_custom_base_url", "") if pk == CUSTOM_PROVIDER else "")


def _on_model_change() -> None:
    roles = {role: _spec_from_widgets(role) for role in ALL_ROLES}
    if any(roles[r] is None for r in MAIN_ROLES):
        return                                  # incomplete (e.g. a custom model id still empty): keep the last good config
    cfg = ModelConfig({r: s for r, s in roles.items() if s}, _spec_from_widgets("fallback"))
    st.session_state["model_config"] = cfg
    st.session_state.pop("_model_test", None)   # a test of the old choice says nothing about the new one
    save_config(cfg)


def _on_provider_change(role: str) -> None:
    pk = st.session_state[f"mp_{role}"]
    if pk == _NO_FALLBACK:                       # only the fallback row offers this
        st.session_state[f"mm_{role}"] = ""
    else:
        st.session_state[f"mm_{role}"] = _CUSTOM_MODEL if pk == CUSTOM_PROVIDER else _default_model(pk)
    st.session_state[f"mc_{role}"] = ""
    _on_model_change()


def _apply_preset(preset: str) -> None:
    cfg = recommend(st.session_state.get("_available_providers", set()), preset)
    st.session_state["model_config"] = cfg
    save_config(cfg)
    _set_widget_state(cfg)
    st.session_state.pop("_model_test", None)


def _refresh_model_lists() -> None:
    """Ask each provider that has a key which models it offers."""
    from concurrent.futures import ThreadPoolExecutor
    keys, base = _keys, st.session_state.get("_custom_base_url", "")
    todo = [p for p in st.session_state.get("_available_providers", set())]
    with ThreadPoolExecutor(max_workers=max(1, len(todo))) as pool:
        found = list(pool.map(lambda p: fetch_models(p, keys[p], base if p == CUSTOM_PROVIDER else ""), todo))
    st.session_state["_fetched_models"] = {p: m for p, m in zip(todo, found) if m}
    st.session_state["_models_refreshed"] = {p: len(m) for p, m in zip(todo, found)}
    _set_widget_state(st.session_state["model_config"])   # a model may now be in the list instead of "Custom…"


def _model_row(role: str) -> None:
    label = ROLE_LABELS.get(role, "Fallback")
    tip = ROLE_HELP.get(role, "Used when a role's own model fails. A different provider is best, so one outage "
                              "cannot take out both.")
    c_role, c_prov, c_model = st.columns([1.1, 1.3, 2.2], vertical_alignment="center")
    c_role.markdown(f'<span title="{html.escape(tip)}" style="font-weight:600;font-size:0.9rem;">{esc(label)}</span>',
                    unsafe_allow_html=True)
    # A fixed snapshot of the labels (not a function that reads session state), so
    # they are the same wherever Streamlit evaluates them.
    _labels = {p: _provider_label(p) for p in _provider_options(role)}
    c_prov.selectbox("Provider", list(_labels), key=f"mp_{role}", format_func=_labels.__getitem__,
                     label_visibility="collapsed", on_change=_on_provider_change, args=(role,))
    pk = st.session_state[f"mp_{role}"]
    if pk == _NO_FALLBACK:
        c_model.caption("If a model fails, the call fails.")
        return
    options = _model_choices(pk) + [_CUSTOM_MODEL]
    if st.session_state.get(f"mm_{role}") not in options:
        st.session_state[f"mm_{role}"] = options[0]
    c_model.selectbox("Model", options, key=f"mm_{role}", label_visibility="collapsed", on_change=_on_model_change)
    if st.session_state[f"mm_{role}"] == _CUSTOM_MODEL:
        c_model.text_input("Model id", key=f"mc_{role}", label_visibility="collapsed", on_change=_on_model_change,
                           placeholder="model id, exactly as the provider names it")


def _config_signature(cfg: ModelConfig) -> str:
    return json.dumps(cfg.to_dict(), sort_keys=True)


def _render_model_picker() -> list:
    """The 'Models for this run' panel, shown right above Run analysis. Returns
    the problems that would make the run fail (missing keys) so Run can be held."""
    import pandas as pd_module
    cfg = st.session_state["model_config"]
    if "mp_analysis" not in st.session_state:
        _set_widget_state(cfg)
    available = st.session_state.get("_available_providers", set())

    head, b_test, b_rec, b_fast = st.columns([2.4, 1, 1.3, 1], vertical_alignment="center")
    head.markdown('<div class="section-label" style="margin:0;">Models for this run</div>', unsafe_allow_html=True)
    test_clicked = b_test.button("Test models", key="test_models_btn", help="Sends each selected model a tiny real "
                                 "request (plain, then strict JSON) and shows the time or the exact error.")
    b_rec.button("Use recommended", key="preset_recommended", on_click=_apply_preset, args=("recommended",),
                 help="Fast model for extraction and wiki, a stronger one for analysis, a mixed council, "
                      "and a fallback on another provider, chosen from the keys you have.")
    b_fast.button("Fastest", key="preset_fastest", on_click=_apply_preset, args=("fastest",),
                  help="The fast model for every role.")

    notes = explain(cfg)
    summary = " · ".join(f"{ROLE_LABELS[r]}: {cfg.spec_for(r).model}" for r in MAIN_ROLES)
    summary += f" · Fallback: {cfg.fallback.model}" if cfg.fallback else " · No fallback"
    st.caption(summary)

    if test_clicked:
        with st.spinner("Testing models…"):
            st.session_state["_model_test"] = {"sig": _config_signature(cfg),
                                               "results": run_model_tests(cfg, _keys)}
    test = st.session_state.get("_model_test")
    if test and test["sig"] == _config_signature(cfg):
        for r in test["results"]:
            roles = ", ".join(r["roles"])
            if r["ok"]:
                if r["json_ok"] is None:
                    json_note = f" · JSON check skipped: {html.escape(r['json_note'])}" if r.get("json_note") else ""
                elif r["json_ok"]:
                    json_note = ""
                else:
                    json_note = (" · <b>replies, but not in strict JSON</b>" if not r.get("json_note")
                                 else f" · <b>JSON check failed:</b> {html.escape(r['json_note'])}")
                st.markdown(f'<span style="color:#087f5b;font-weight:700;">✓</span> {html.escape(r["label"])} '
                            f'— {r["latency_s"]} s{json_note} <span style="color:#4a6580;">({html.escape(roles)})</span>',
                            unsafe_allow_html=True)
            else:
                st.markdown(f'<span style="color:#c81e1e;font-weight:700;">✗</span> {html.escape(r["label"])} '
                            f'<span style="color:#4a6580;">({html.escape(roles)})</span><br>'
                            f'<span style="color:#c81e1e;font-size:0.82rem;">{html.escape(r["error"])}</span>',
                            unsafe_allow_html=True)

    with st.expander("Choose models"):
        st.caption("Each job can use a different provider and model. Hover a name to see what it does.")
        for role in MAIN_ROLES:
            _model_row(role)
            if notes.get(role):
                st.caption(f"↳ {notes[role]}")
        _model_row("fallback")
        st.markdown('<div style="margin-top:0.6rem;font-weight:600;font-size:0.9rem;">Council (Computational Lab)</div>',
                    unsafe_allow_html=True)
        for role in COUNCIL_ROLES:
            _model_row(role)
        st.button("Refresh model lists", key="refresh_models_btn", on_click=_refresh_model_lists,
                  help="Asks each provider you have a key for which models it offers right now.")
        refreshed = st.session_state.get("_models_refreshed")
        if refreshed:
            st.caption("Models listed: " + " · ".join(f"{_provider_name(p)} {n}" for p, n in refreshed.items()))
        with st.expander("Why these recommendations?"):
            st.caption("Measured on the same wiki-compile task (one 16-page paper, the app's own prompt):")
            st.table(pd_module.DataFrame(BENCHMARK).rename(columns={
                "model": "Model", "time": "Time per call", "valid_json": "Valid JSON", "quality": "Quality"}))
            st.caption("So: a fast model for the high-volume stages, a stronger one only where reasoning matters, "
                       "council seats from different models (independent views are the point), and a fallback on "
                       "a different provider. Not benchmarked here: OpenAI, Groq, and custom endpoints, so use "
                       "Test models with them.")

    issues = []
    for role in MAIN_ROLES:
        spec = cfg.spec_for(role)
        if spec.provider not in available:
            issues.append(f"{ROLE_LABELS[role]}: add a {_provider_name(spec.provider)} key under API keys & endpoints.")
    if cfg.fallback and cfg.fallback.provider not in available:
        st.caption(f"⚠ The fallback ({cfg.fallback.label}) has no key, so it cannot take over.")
    return issues


# ── Settings state, resolved on every run (the widgets are on the Settings page) ──────────────
from ui.settings_state import (DEFAULT_OPTIONS, hide_paths, model_issues as _model_issues_for,
                               new_settings, resolve_keys, source_label)

if "_settings" not in st.session_state:
    st.session_state["_settings"] = new_settings()
_S = st.session_state["_settings"]
_resolved = resolve_keys(_S, PROVIDER_REGISTRY, CUSTOM_PROVIDER)
_keys = _resolved["keys"]
_available = _resolved["available"]
_custom_base = _resolved["custom_base"]
ss_api_key = _resolved["ss_key"]
api_key = _keys["nvidia"]          # also used for relevance ranking in Deep gap validation
st.session_state["_available_providers"] = _available
st.session_state["_custom_base_url"] = _custom_base
if "model_config" not in st.session_state:
    st.session_state["model_config"] = load_config(_available)
st.session_state.setdefault("view", "main")   # main | new_analysis | settings | new_project


def _go(view: str) -> None:
    st.session_state["view"] = view
    st.session_state["_collapse_sidebar"] = True      # on a phone the open sidebar would cover the page just chosen


def _model_issues() -> list:
    return _model_issues_for(st.session_state["model_config"], _available, MAIN_ROLES, ROLE_LABELS, _provider_name)


# ── Sidebar: where am I, and the four things to do ─────────────────────────────────────────
with st.sidebar:
    st.markdown(f'<div class="sb-brand">{html.escape(_BRANDING["product_name"])}</div>', unsafe_allow_html=True)

    _projects = list_projects()
    _project_ids = [p["id"] for p in _projects]
    _project_by_id = {p["id"]: p for p in _projects}
    if "_pending_project" in st.session_state:   # set by New project; the picker can't be set after it exists
        st.session_state["project_select"] = st.session_state.pop("_pending_project")
    if st.session_state.get("project_select") not in _project_ids:
        st.session_state["project_select"] = DEFAULT_PROJECT_ID
    st.session_state.current_project_id = st.session_state["project_select"]
    st.selectbox(
        "Project", _project_ids, key="project_select", on_change=_on_project_change,
        format_func=lambda pid: f"{_project_by_id[pid]['name']} ({_project_by_id[pid]['run_count']} runs)",
        label_visibility="collapsed")
    st.button("New project", key="new_project_btn", on_click=_go, args=("new_project",))
    st.button("New analysis", key="new_analysis_btn", type="primary", on_click=_go, args=("new_analysis",),
              width="stretch")
    st.button("Settings", key="settings_btn", on_click=_go, args=("settings",))

    st.markdown("---")
    st.markdown("##### Run")
    runs = list_runs(limit=30, project_id=st.session_state.current_project_id)
    _run_by_id = {r["id"]: r for r in runs}

    def _run_label(rid: str) -> str:
        r = _run_by_id[rid]
        return f"{r['name'][:28]} · {_local_time(r['created_at'])} · {r['n_gaps']} gaps" + (" · Lab" if r["has_comp"] else "")

    def _on_run_select() -> None:
        rid = st.session_state.get("run_select")
        if rid in _run_by_id and _load_run_into_session(rid, _run_by_id[rid]["name"]):
            st.session_state["view"] = "main"
            st.session_state["_collapse_sidebar"] = True

    if not runs:
        st.caption("No saved runs in this project yet.")
    else:
        # The picker always shows the run on screen (a run just finished, or loaded elsewhere).
        st.session_state["run_select"] = (st.session_state.current_run_id
                                          if st.session_state.current_run_id in _run_by_id else None)
        st.selectbox("Run", list(_run_by_id), key="run_select", format_func=_run_label,
                     on_change=_on_run_select, index=None, placeholder="Select a run",
                     label_visibility="collapsed")
        st.caption("All runs, comparison, files and feedback: Project view.")

# On narrow screens, close the sidebar once the user has picked something in it (a no-op on wide screens).
if st.session_state.pop("_collapse_sidebar", False):
    collapse_sidebar_on_phones()

# ── Main header (hero) ────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  .hero, .hero * { font-family: Inter, "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif !important; }
  .hero {
    position: relative; overflow: hidden;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.1rem 1.9rem 1.2rem;
    margin: 0 0 1.1rem;
    box-shadow: 0 1px 2px rgba(11, 31, 58, 0.05), 0 6px 20px rgba(0, 76, 147, 0.06);
  }
  .hero::before {
    content: ""; position: absolute; inset: 0 0 auto 0; height: 4px;
    background: linear-gradient(90deg, var(--accent-strong), var(--accent) 55%, #19a7ce);
  }
  .hero-brand {
    display: flex; align-items: center; gap: 0.7rem;
    padding-bottom: 0.85rem; margin-bottom: 1.1rem; border-bottom: 1px solid #e3eefb;
  }
  .hero-mark {
    width: 2.1rem; height: 2.1rem; border-radius: 8px; flex: none;
    display: flex; align-items: center; justify-content: center;
    background: linear-gradient(135deg, var(--accent-strong), var(--accent));
  }
  .hero-mark svg { width: 1.3rem; height: 1.3rem; }
  .hero-name { font-size: 1.05rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--accent-strong); }
  .hero-divider { width: 1px; height: 1.1rem; background: var(--border); }
  .hero-platform { font-size: 0.86rem; font-weight: 500; color: var(--muted); }
  .hero-grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr); gap: 2.2rem; align-items: start; }
  .hero .hero-h1 {
    margin: 0 0 0.55rem !important; font-size: 1.65rem; font-weight: 700;
    line-height: 1.2; letter-spacing: -0.02em; color: var(--text);
  }
  .hero .hero-desc {
    margin: 0 !important; max-width: 36rem; font-size: 0.95rem; line-height: 1.6; color: var(--muted);
  }
  .hero-points { display: flex; flex-direction: column; gap: 0.65rem; padding-left: 1.6rem; border-left: 1px solid #e3eefb; }
  .hero-point { display: flex; gap: 0.7rem; align-items: flex-start; }
  .hero-point svg { flex: none; width: 1.15rem; height: 1.15rem; margin-top: 0.12rem; }
  .hero-point b { display: block; font-size: 0.9rem; font-weight: 600; color: var(--text); }
  .hero-point span { display: block; font-size: 0.82rem; line-height: 1.45; color: var(--muted); }
  .hero-flow { display: flex; }
  .hero-flow-title {
    font-size: 0.68rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase;
    color: var(--muted); margin: 1.1rem 0 0.7rem; padding-top: 0.85rem; border-top: 1px solid #e3eefb;
  }
  .flow-step { flex: 1; position: relative; min-width: 0; }
  .flow-step:not(:last-child)::after {
    content: ""; position: absolute; top: 0.8rem; left: 2.1rem; right: 0.4rem; height: 1px; background: var(--border);
  }
  .flow-dot {
    width: 1.6rem; height: 1.6rem; border-radius: 50%; display: flex; align-items: center; justify-content: center;
    background: var(--accent-soft); border: 1px solid #7ab8f5; color: var(--accent-strong);
    font-size: 0.72rem; font-weight: 600; position: relative; z-index: 1;
  }
  .flow-label { margin-top: 0.45rem; font-size: 0.8rem; font-weight: 500; color: var(--text); }
  @media (max-width: 900px) {
    .hero-grid { grid-template-columns: 1fr; gap: 1.2rem; }
    .hero-points { padding-left: 0; border-left: none; }
    .hero-flow { flex-wrap: wrap; gap: 0.8rem 0; }
    .flow-step { flex: 0 0 33%; }
    .flow-step::after { display: none; }
  }
  .sb-brand {
    font-size: 1.05rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--accent-strong); padding: 0.3rem 0 0.7rem; margin-bottom: 0.4rem;
    border-bottom: 1px solid var(--border);
    font-family: Inter, "Segoe UI", system-ui, sans-serif !important;
  }
  [data-testid="stSidebar"] .stButton > button {
    background: var(--surface) !important; color: var(--accent-strong) !important;
    border: 1px solid var(--border) !important; width: 100%;
    justify-content: flex-start; text-align: left; font-weight: 500 !important;
  }
  [data-testid="stSidebar"] .stButton > button:hover {
    background: var(--accent-soft) !important; border-color: #7ab8f5 !important;
  }
  [data-testid="stSidebar"] .stButton > button:disabled {
    background: #f2f5f8 !important; color: #8aa0b8 !important; border-color: #e3eefb !important;
  }
  .section-label { font-size: 1rem; font-weight: 600; color: var(--text); margin: 0 0 0.15rem; }
  .section-hint { font-size: 0.82rem; color: var(--muted); margin: 0 0 0.6rem; }
  .run-status { font-size: 0.86rem; color: var(--muted); margin: 0 !important; line-height: 1.2; }
  .run-status.ready { color: var(--success); font-weight: 500; }
  [data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--surface) !important;
    border-radius: 12px !important;
    border-color: var(--border) !important;
    box-shadow: 0 1px 2px rgba(11, 31, 58, 0.05), 0 6px 20px rgba(0, 76, 147, 0.06) !important;
  }
  .stButton > button[kind="primary"] { padding: 0.6rem 1.6rem !important; font-weight: 600 !important; }
  .stButton > button:disabled { background: #c9d6e2 !important; border-color: #c9d6e2 !important; color: #ffffff !important; }
</style>
""", unsafe_allow_html=True)

_CHECK = ('<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="9" fill="#e5f2ff" stroke="#7ab8f5"/>'
          '<path d="M6 10.4l2.6 2.6L14 7.6" stroke="#0066cc" stroke-width="1.8" stroke-linecap="round" '
          'stroke-linejoin="round"/></svg>')
_MARK = ('<svg viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="1.7" stroke-linecap="round">'
         '<path d="M6.5 7.5L17 6.5M6.5 7.5L11 17.5M17 6.5L11 17.5"/>'
         '<circle cx="6.5" cy="7.5" r="2.2" fill="#ffffff"/><circle cx="17" cy="6.5" r="2.2" fill="#ffffff"/>'
         '<circle cx="11" cy="17.5" r="2.2" fill="#ffffff"/></svg>')
_hero_points = [
    ("Evidence-linked", "Every gap is traced to evidence in your papers."),
    ("Literature-validated", "Checked against Europe PMC, Semantic Scholar and arXiv."),
    ("Auditable runs", "Model, parser and code versions recorded."),
]
_hero_steps = ["Parse", "Evidence", "Knowledge graph", "Gap detection", "Validation", "Proposals"]
_points_html = "".join(
    f'<div class="hero-point">{_CHECK}<div><b>{esc(t)}</b><span>{esc(d)}</span></div></div>' for t, d in _hero_points)
_flow_html = "".join(
    f'<div class="flow-step"><div class="flow-dot">{i}</div><div class="flow-label">{esc(s)}</div></div>'
    for i, s in enumerate(_hero_steps, 1))
# The hero is for first-time visitors: once the project has a run, results come first.
_show_hero = st.session_state["view"] == "main" and not (st.session_state.results or list_runs(limit=1, project_id=st.session_state.current_project_id))
if _show_hero:
    st.markdown(
        '<div class="hero">'
        '<div class="hero-brand">'
        f'<div class="hero-mark">{_MARK}</div>'
        f'<div class="hero-name">{html.escape(_BRANDING["product_name"])}</div>'
        '<div class="hero-divider"></div>'
        f'<div class="hero-platform">{html.escape(_BRANDING["tagline"])}</div>'
        '</div>'
        '<div class="hero-grid">'
        '<div>'
        '<div class="hero-h1">Identify and validate the research gaps across your literature.</div>'
        '<div class="hero-desc">Upload 2&ndash;5 papers. AI agents read them, map what is already known, '
        'and surface the open questions &mdash; with the evidence behind each one.</div>'
        '</div>'
        f'<div class="hero-points">{_points_html}</div>'
        '</div>'
        '<div class="hero-flow-title">Analysis pipeline</div>'
        f'<div class="hero-flow">{_flow_html}</div>'
        '</div>',
        unsafe_allow_html=True)

# ── Project: tools shared by the Project view ───────────────────────────────
# The run-comparison tools used to live in the sidebar. They are in the Project
# view now, where a project's runs are listed and can be selected together.

def _render_run_comparison(id_a: str, id_b: str, name_a: str = "the older run", name_b: str = "the newer run") -> None:
    """Diffs two saved runs directly, in full: papers, evidence counts, graph
    entities/relationships, gaps (with confidence changes), proposals, and the
    model/pipeline version each run used. Reads only already-saved data
    (pipeline/run_compare.py), no new LLM calls. A is the older run."""
    try:
        cmp = compare_runs(id_a, id_b)
        m = cmp["manifest"]

        def _gate(value) -> str:
            if isinstance(value, dict):
                return " · ".join(f"{k}: {v or 'not run'}" for k, v in value.items()) or "unknown"
            return str(value or "unknown")

        st.markdown(
            f"**Model:** `{m['model_bundle_version_a'] or 'unknown'}` → "
            f"`{m['model_bundle_version_b'] or 'unknown'}`  \n"
            f"**Duration:** {m['run_duration_seconds_a'] or '?'}s → "
            f"{m['run_duration_seconds_b'] or '?'}s  \n"
            f"**Quality gate:** {_gate(m['quality_gate_results_a'])} → "
            f"{_gate(m['quality_gate_results_b'])}"
        )
        st.markdown("")
        p = cmp["papers"]
        e = cmp["evidence"]
        gp0, pr0 = cmp["gaps"], cmp["proposals"]
        _cards = [("Papers in common", p["common_count"]), ("Evidence items", f"{e['count_a']} → {e['count_b']}"),
                  ("Gaps in common", gp0["common_count"]), ("New gaps", len(gp0["added"])),
                  ("Proposals in common", pr0["common_count"])]
        for col, (lbl, val) in zip(st.columns(len(_cards)), _cards):
            with col:
                st.markdown(f'<div class="stat-box"><span class="stat-number" style="font-size:1.4rem;">{esc(val)}</span>'
                            f'<span class="stat-label">{esc(lbl)}</span></div>', unsafe_allow_html=True)
        st.markdown(f"**Papers:** {p['common_count']} common · "
                    f"{len(p['added'])} added · {len(p['removed'])} removed")
        st.markdown(f"**Evidence objects:** {e['count_a']} → {e['count_b']} "
                    f"({'+' if e['delta'] >= 0 else ''}{e['delta']})")
        g = cmp["graph"]
        st.markdown(
            f"**Graph entities:** {g['entities_common_count']} common · "
            f"{len(g['entities_added'])} added · {len(g['entities_removed'])} removed  \n"
            f"**Graph relationships:** {g['relationships_common_count']} common · "
            f"{len(g['relationships_added'])} added · {len(g['relationships_removed'])} removed"
        )
        gp = cmp["gaps"]
        st.markdown(
            f"**Gaps:** {gp['common_count']} common · "
            f"{len(gp['added'])} new · {len(gp['removed'])} no longer generated · "
            f"{len(gp['confidence_changes'])} confidence change(s)"
        )
        pr = cmp["proposals"]
        st.markdown(f"**Proposals:** {pr['common_count']} common · "
                    f"{pr['added_count']} added · {pr['removed_count']} removed")
        if gp["added"]:
            st.markdown("")
            _section_label(f"New gaps in the newer run ({html.escape(name_b)})")
            for t in gp["added"][:15]:
                _item(f"🆕 {esc(t)}")
        if gp["removed"]:
            st.markdown("")
            _section_label(f"Gaps no longer generated (only in the older run, {html.escape(name_a)})")
            for t in gp["removed"][:15]:
                _item(f"➖ {esc(t)}")
        if gp["confidence_changes"]:
            st.markdown("")
            _section_label("Confidence changes")
            for c in gp["confidence_changes"][:15]:
                _item(f"🔀 {esc(c['title'])}: {esc(c['confidence_a'])} → {esc(c['confidence_b'])}")
    except ValueError as e:
        show_error(str(e))


def _render_repeatability(selected_ids: list[str]) -> None:
    """How stable the gap output was across repeated analyses of the same
    corpus/context (pipeline/repeatability_score.py). Unrelated runs just give
    a low, honestly-meaningless score, not an error."""
    gap_sets = [load_run(rid).get("results", {}).get("gaps", []) for rid in selected_ids]
    _names = {r["id"]: r["name"] for r in list_runs(limit=100000, include_archived=True)}
    try:
        report = compute_repeatability_score(gap_sets, run_ids=selected_ids)
        st.markdown(
            f"**Gap overlap:** {report['gap_overlap_mean']} · "
            f"**Claim stability:** {report['claim_stability_mean']} · "
            f"**Ranking correlation:** {report['ranking_correlation_mean']} · "
            f"**Confidence drift:** {report['confidence_drift_mean']}"
        )
        if report.get("duplicate_run_note"):
            show_warning(
                f"{report['n_duplicate_pairs_excluded']} pair(s) excluded from the "
                f"averages above -- {report['duplicate_run_note']}"
            )
        st.caption(report["ranking_proxy_note"])
        st.markdown("")
        _section_label("Per-Pair Detail")
        for p in report["pairs"]:
            dup = " ⚠️ likely duplicate (excluded above)" if p["likely_duplicate_run"] else ""
            st.markdown(
                f"**{html.escape(_names.get(p['run_a'], 'run'))}** vs **{html.escape(_names.get(p['run_b'], 'run'))}**{dup} — "
                f"overlap {p['gap_overlap']}, stability {p['claim_stability']}, "
                f"ranking corr {p['ranking_correlation']}, drift {p['confidence_drift']} "
                f"({p['n_common_gaps']} common gaps)"
            )
    except ValueError as e:
        show_error(str(e))


def _render_lineage(run_id: str) -> None:
    """Technical lineage (the artifact chain) and scientific lineage (each gap
    traced back to the evidence and graph relationships behind it)."""
    try:
        tech = get_technical_lineage(run_id)
        _section_label("Technical lineage (artifact chain)")
        if tech["root"] is None:
            st.caption("No artifact chain recorded for this run.")
        else:
            by_id = {n["artifact_id"]: n for n in tech["nodes"]}
            for e in tech["edges"]:
                child = by_id.get(e["child"], {})
                _item(f"🔗 {esc(e['parent'])} → {esc(e['child'])} ({esc(child.get('artifact_type','?'))})")
            if tech["fan_in_edges"]:
                st.caption(f"{len(tech['fan_in_edges'])} fan-in edge(s) (e.g. N papers → 1 evidence set)")
            if tech["orphans"]:
                show_warning(f"{len(tech['orphans'])} artifact(s) with an unresolved parent.")

        sci = get_scientific_lineage(run_id)
        st.markdown("")
        _section_label("Scientific lineage (per-gap chain)")
        if not sci["gaps"] and not sci["n_gaps_without_identity"]:
            st.caption("No gaps recorded for this run.")
        if sci["n_gaps_without_identity"]:
            st.caption(f"{sci['n_gaps_without_identity']} gap(s) on this run have no gap_id "
                       f"(saved before gap identity existed) and are excluded below.")
        for g in sci["gaps"][:10]:
            c = g["chain"]
            u = g["unresolved"]
            n_unresolved = (len(u["evidence_ids_not_found"]) + len(u["relationship_ids_not_found"])
                            + len(u["entity_ids_not_found"]))
            _item(
                f"🧩 {esc(g['title'])} [{esc(g['source'])}/{esc(g['evidence_basis'])}] — "
                f"{len(c['evidence'])} evidence · {len(c['relationships'])} relationships · "
                f"{len(c['proposals'])} proposal(s)"
                + (f" · ⚠️ {n_unresolved} unresolved id(s)" if n_unresolved else "")
            )
    except ValueError as e:
        show_error(str(e))


def _render_graph_history(project_run_ids: set) -> None:
    """Knowledge graphs saved for this project's runs, and a diff of any two."""
    ok, msg = graph_store_connect_ok()
    if not ok:
        st.caption(f"Not connected -- {msg}")
        return
    try:
        graph_runs = [g for g in list_graph_snapshots() if g["run_id"] in project_run_ids]
    except Exception as e:
        show_error("Could not list saved graphs", exc=e)
        return
    if not graph_runs:
        st.caption("No saved graphs for this project yet. Run an analysis first.")
        return
    graph_options = {
        f"{g['name'][:30]} ({g['entity_count']}e/{g['relationship_count']}r"
        + (f", {g['build_status']} {g['quality_score']:.2f})" if g.get("build_status") else ")"): g["run_id"]
        for g in graph_runs
    }
    labels = st.multiselect("Pick exactly 2 saved graphs to diff", options=list(graph_options.keys()),
                            key="graph_diff_select")
    if st.button("Diff graphs", key="diff_graphs", disabled=len(labels) != 2):
        id_a, id_b = [graph_options[lbl] for lbl in labels]
        try:
            diff = diff_graph_snapshots(id_a, id_b)
            st.markdown(
                f"**Entities:** {len(diff['entities_common'])} common · "
                f"{len(diff['entities_only_in_a'])} only in the first · "
                f"{len(diff['entities_only_in_b'])} only in the second"
            )
            st.markdown(
                f"**Relationships:** {len(diff['relationships_common'])} common · "
                f"{len(diff['relationships_only_in_a'])} only in the first · "
                f"{len(diff['relationships_only_in_b'])} only in the second"
            )
            if diff.get("entities_renamed"):
                a_, b_ = diff["entities_renamed"][0]
                st.caption(f"{len(diff['entities_renamed'])} common entit"
                           f"{'y is' if len(diff['entities_renamed']) == 1 else 'ies are'} worded differently in the two runs "
                           f"(for example “{a_}” and “{b_}”). Different words for the same idea that cannot be matched "
                           "by spelling alone (such as an abbreviation and its long form) still count as different.")
            for key, rid in (("entities_only_in_a", id_a), ("entities_only_in_b", id_b)):
                if diff[key]:
                    st.markdown("")
                    _section_label("Entities only in the " + ("first" if rid == id_a else "second") + " graph")
                    for name_ in diff[key][:15]:
                        _item(f"🔹 {esc(name_)}")
            for key, rid in (("relationships_only_in_a", id_a), ("relationships_only_in_b", id_b)):
                if diff[key]:
                    st.markdown("")
                    _section_label("Relationships only in the " + ("first" if rid == id_a else "second") + " graph")
                    for s_, t_, r_ in diff[key][:10]:
                        _item(f"↔ {esc(s_)} — {esc(r_)} → {esc(t_)}")
        except Exception as e:
            show_error("Diff failed", exc=e)


_FILE_MIME = {"results": "application/json", "manifest": "application/json",
              "report_html": "text/html", "report_pdf": "application/pdf"}
_FILE_LABEL = {"results": "Results (JSON)", "manifest": "Run manifest (JSON)",
               "report_html": "Report (HTML)", "report_pdf": "Report (PDF)"}


def _render_run_files(project_id: str, run: dict) -> None:
    """Download buttons for what one run saved in the project folder."""
    files = [f for f in list_project_files(project_id, run_id=run["id"]) if f["kind"] in _FILE_MIME]
    if not files:
        st.caption("No saved files for this run (it predates projects, or saving failed).")
        return
    cols = st.columns(len(files))
    for col, f in zip(cols, files):
        with col:
            try:
                st.download_button(
                    _FILE_LABEL.get(f["kind"], f["filename"]),
                    data=project_store.read_project_file(project_id, f["rel_path"]),
                    file_name=f"{project_store.safe_filename(run['name'])}_{f['filename']}",
                    mime=_FILE_MIME[f["kind"]], key=f"dl_{run['id']}_{f['kind']}")
            except (OSError, ValueError):
                st.caption(f"{_FILE_LABEL.get(f['kind'], f['filename'])}: no longer on disk")


def _table(df, **kwargs):
    """st.dataframe at full width on any Streamlit version (see ui/compat.py)."""
    return table_full_width(df, **kwargs)


def _render_project_view(project: dict, runs: list[dict]) -> None:
    import pandas as pd
    from collections import Counter
    pid = project["id"]
    st.markdown(f"### {html.escape(project['name'])}")
    if project.get("description"):
        st.caption(project["description"])
    if not hide_paths():                      # a server's folder names mean nothing on a hosted deployment
        st.caption(f"Folder: `{project_store.project_path(pid)}`")

    # ── Runs: the board ──────────────────────────────────────────────────────
    st.markdown("#### Runs")
    show_archived = st.checkbox("Show archived runs", key=f"show_archived_{pid}")
    if show_archived:
        runs = list_runs(limit=100000, project_id=pid, include_archived=True)
    selected: list[dict] = []
    if not runs:
        show_info("No analyses in this project yet. Switch to **Analysis**, add papers and run one. "
                "Run it again with different settings to compare the results here.")
    else:
        fb_rows = list_feedback(project_id=pid)
        fb_by_run = Counter(f["run_id"] for f in fb_rows)
        _ids = [r["id"] for r in runs]
        df = pd.DataFrame(board_rows(
            runs, get_run_manifests_bulk(_ids), fb_by_run,
            {k: v.get("gate_blocked") for k, v in load_run_gate_fields_bulk(_ids).items()},
            getattr(st.context, "timezone", None)))
        st.caption("Select one run to open, rename, archive or download it; two to compare them; "
                   "two or more to check how repeatable the results are.")
        event = _table(df, hide_index=True, on_select="rerun",
                       selection_mode="multi-row", key=f"project_runs_{pid}")
        selected = [runs[i] for i in event.selection.rows if i < len(runs)]

        _dups = find_duplicate_groups(pid)
        if _dups:
            with st.expander(f"{len(_dups)} set(s) of duplicate runs"):
                st.caption("Runs with the same papers and the same gaps. Merging keeps one (the one with Lab results, "
                           "else the newest), moves the others' feedback and Lab results to it, and archives the "
                           "rest. Nothing is deleted.")
                for _gi, _grp in enumerate(_dups):
                    _keep = best_to_keep(_grp)
                    st.markdown(f"- Keep **{html.escape(_keep['name'])}**, archive "
                                + ", ".join(f"**{html.escape(r['name'])}**" for r in _grp if r["id"] != _keep["id"]))
                    if st.button(f"Merge these {len(_grp)}", key=f"merge_{pid}_{_gi}"):
                        merge_runs(_keep["id"], [r["id"] for r in _grp if r["id"] != _keep["id"]])
                        st.toast("Duplicates merged and archived.")
                        st.rerun()

    if len(selected) == 1:
        run = selected[0]
        st.markdown(f"**{html.escape(run['name'])}** · {_local_time(run['created_at'])}"
                    + (" · archived" if run.get("archived") else ""))
        _c1, _c2, _c3 = st.columns([3, 1, 1], vertical_alignment="bottom")
        _new_name = _c1.text_input("Rename", value=run["name"], key=f"rename_{run['id']}", label_visibility="collapsed")
        if _c2.button("Rename", key=f"rename_btn_{run['id']}", disabled=not _new_name.strip() or _new_name.strip() == run["name"]):
            rename_run(pid, run["id"], _new_name)
            if st.session_state.current_run_id == run["id"]:
                st.session_state.current_run_name = _new_name.strip()
            st.rerun()
        if run.get("archived"):
            if _c3.button("Restore", key=f"unarchive_{run['id']}"):
                set_run_archived(run["id"], False)
                st.rerun()
        elif _c3.button("Archive", key=f"archive_{run['id']}", help="Hide it from lists. Nothing is deleted."):
            set_run_archived(run["id"], True)
            if st.session_state.current_run_id == run["id"]:
                _clear_results()
            st.rerun()
        if st.button("Open in Analysis view", key=f"open_{run['id']}", type="primary"):
            if _load_run_into_session(run["id"], run["name"]):
                st.session_state["_pending_view"] = "Analysis"
                st.rerun()
        _render_run_files(pid, run)
        with st.expander("Lineage (technical and scientific)"):
            _render_lineage(run["id"])
    elif len(selected) == 2:
        newer, older = sorted(selected, key=lambda r: (r["created_at"], r["id"]), reverse=True)
        st.markdown(f"#### Compare: {html.escape(older['name'])} → {html.escape(newer['name'])}")
        st.caption("Older run on the left of the arrow, newer on the right.")
        _render_run_comparison(older["id"], newer["id"], older["name"], newer["name"])
    elif len(selected) > 2:
        st.caption(f"{len(selected)} runs selected. Select exactly two to compare them directly.")
    if len(selected) >= 2:
        with st.expander("Repeatability across the selected runs"):
            if st.button("Compute repeatability score", key="compute_repeatability"):
                _render_repeatability([r["id"] for r in selected])
    if selected:
        with st.expander("Delete selected runs"):
            st.caption("Removes the runs, their feedback and their saved-file records from the database. "
                       "Prefer **Archive** if you might want them back.")
            for r in selected:
                _fp = run_footprint(pid, r["id"])
                st.markdown(f"- **{html.escape(r['name'])}**: {len(_fp['files'])} saved file(s)"
                            + (f" ({', '.join(_fp['files'][:4])})" if _fp["files"] else "")
                            + f", {_fp['feedback']} feedback item(s)")
            if erase_on_delete():
                st.caption("On this deployment a delete is permanent: the saved files go too, and the saved results kept for "
                           "papers are emptied.")
                _also_files = True
            else:
                _also_files = st.checkbox("Also delete the saved files from the project folder", key="delete_files_too")
            if (st.checkbox("I understand this cannot be undone", key="confirm_delete_runs")
                    and st.button(f"Delete {len(selected)} run(s)", key="delete_runs_btn")):
                for r in selected:
                    delete_run_everywhere(pid, r["id"], remove_files=_also_files)
                st.session_state["confirm_delete_runs"] = False
                if st.session_state.current_run_id in {r["id"] for r in selected}:
                    _clear_results()
                st.rerun()

    # ── Feedback ─────────────────────────────────────────────────────────────
    st.markdown("#### Feedback")
    fb_rows = list_feedback(project_id=pid)
    if not fb_rows:
        st.caption("No feedback yet. Use the Feedback button on any gap in the Analysis view "
                   "(Research Gaps tab), or add a note on a whole run.")
    else:
        run_names = {r["id"]: r["name"] for r in runs}
        fdf = pd.DataFrame([{
            "Run": run_names.get(f["run_id"], f["run_id"][:8]),
            "About": {"gap": "Gap", "proposal": "Proposal", "run": "Whole run"}[f["target_type"]],
            "Item": f["target_label"] or "",
            "Rating": {1: "Useful", -1: "Not useful"}.get(f["rating"], ""),
            "Reason": f["reason"] or "", "Comment": f["comment"] or "",
            "Updated": (f["updated_at"] or "")[:16].replace("T", " "),
        } for f in fb_rows])
        _table(fdf, hide_index=True)
        st.download_button("Download feedback (JSON)", data=json.dumps(fb_rows, indent=2, default=str),
                           file_name=f"{project_store.safe_filename(project['name'])}_feedback.json",
                           mime="application/json", key=f"dl_feedback_{pid}")

    # ── Files and downloads ──────────────────────────────────────────────────
    st.markdown("#### Files")
    pfiles = list_project_files(pid)
    n_papers = sum(1 for f in pfiles if f["kind"] == "paper")
    with st.expander(f"Project files ({len(pfiles)}) · {n_papers} paper(s)"):
        if pfiles:
            _table(pd.DataFrame([{
                "Kind": f["kind"].replace("_", " "), "File": f["filename"],
                "Size (KB)": round(f["size_bytes"] / 1024, 1), "Path": f["rel_path"],
            } for f in pfiles]), hide_index=True)
        else:
            st.caption("No files saved for this project yet.")
    with st.expander("Knowledge graph history"):
        _render_graph_history({r["id"] for r in runs})

    # ── Project settings ─────────────────────────────────────────────────────
    st.markdown("#### Project settings")
    with st.expander("Name, description and research setup"):
        _choices = dict(get_ui_domain_choices())
        _labels = list(_choices)
        _cur = next((l for l, k in _choices.items() if k == project.get("domain")), _labels[0])
        with st.form(key=f"project_settings_{pid}", border=False):
            _pname = st.text_input("Project name", value=project["name"])
            _pdesc = st.text_area("Description", value=project.get("description") or "", height=70)
            _pdom = st.selectbox("Default domain", _labels, index=_labels.index(_cur))
            _pint = st.text_area("Default research interest", value=project.get("interest") or "", height=70)
            if st.form_submit_button("Save settings", type="primary"):
                try:
                    update_project_settings(pid, _pname, _pdesc, _choices[_pdom], _pint)
                    st.toast("Project settings saved.")
                    st.rerun()
                except ValueError as e:
                    show_error(str(e))
    if pid != DEFAULT_PROJECT_ID:
        with st.expander("Delete this project"):
            _fp = project_footprint(pid)
            show_warning(f"This removes {len(_fp['runs'])} run(s) and {_fp['n_files']} file record(s) "
                       f"({_fp['n_papers']} paper(s)) from the database"
                       + (": " + ", ".join(_fp["runs"][:6]) + ("…" if len(_fp["runs"]) > 6 else "") if _fp["runs"] else "")
                       + (". Everything is erased permanently: the project folder, the saved results for papers, and any "
                          "copy an earlier delete kept." if erase_on_delete() else
                          ". The project folder is moved to a _deleted folder, not erased (Settings > Saved results can erase it)."))
            if (st.checkbox("I understand this deletes the project and its runs", key=f"confirm_delete_project_{pid}")
                    and st.button("Delete project", key=f"delete_project_btn_{pid}")):
                delete_project_everywhere(pid)
                _clear_results()
                st.session_state["_pending_project"] = DEFAULT_PROJECT_ID     # applied to the picker on the next run
                st.session_state.current_project_id = DEFAULT_PROJECT_ID
                st.session_state["view"] = "main"
                st.session_state["main_view"] = "Analysis"
                st.rerun()

    zip_key = f"project_zip_{pid}"
    if st.button("Prepare project download", key=f"prep_zip_{pid}"):
        st.session_state[zip_key] = project_store.build_project_zip(pid)
    if st.session_state.get(zip_key):
        st.download_button("Download project (.zip)", data=st.session_state[zip_key],
                           file_name=f"{project_store.safe_filename(project['name'])}.zip",
                           mime="application/zip", key=f"dl_zip_{pid}")
        st.caption("The zip holds the papers, every run's results and reports, and a database export "
                   "with the project's runs and feedback.")


# ── Project: feedback forms (used by the Analysis view) ──────────────────────
_FEEDBACK_REASONS = ["(none)"] + list(POSITIVE_REASONS) + [r for r in NEGATIVE_REASONS if r not in POSITIVE_REASONS]


def _feedback_form(form_key: str, *, project_id: str, run_id: str, target_type: str, target_id: str,
                   target_label: str, existing: dict | None, question: str) -> None:
    """One form for a gap / proposal / run: rating, reason, comment. Saving
    updates the single feedback row for this target; Clear removes it."""
    with st.form(key=f"fb_{form_key}", border=False):
        rating_idx = {1: 0, -1: 1}.get((existing or {}).get("rating"))
        rating = st.radio(question, ["Useful", "Not useful"], index=rating_idx, horizontal=True)
        old_reason = (existing or {}).get("reason") or "(none)"
        reason = st.selectbox("Reason", _FEEDBACK_REASONS,
                              index=_FEEDBACK_REASONS.index(old_reason) if old_reason in _FEEDBACK_REASONS else 0)
        comment = st.text_area("Comment (optional)", value=(existing or {}).get("comment") or "", height=80)
        c_save, c_clear, _ = st.columns([1, 1, 2])
        saved = c_save.form_submit_button("Save", type="primary")
        cleared = c_clear.form_submit_button("Clear") if existing else False
    if saved or cleared:
        if saved:
            upsert_feedback(project_id, run_id, target_type, target_id,
                            rating={"Useful": 1, "Not useful": -1}.get(rating),
                            reason="" if reason == "(none)" else reason, comment=comment,
                            target_label=target_label)
        else:
            upsert_feedback(project_id, run_id, target_type, target_id)   # empty = clear
        st.toast("Feedback saved" if saved else "Feedback cleared")
        st.rerun()


def _gap_feedback_key(gap: dict, idx: int) -> str:
    """The stable gap_id, so feedback follows the gap across runs; older runs
    saved before gap identity existed fall back to a hash of the title."""
    import hashlib
    return gap.get("gap_id") or "title:" + hashlib.sha1(
        (gap.get("title") or f"gap-{idx}").encode("utf-8")).hexdigest()[:12]


_GAP_LENS_LABELS = {
    "limitation_miner": "From the authors' limitations",
    "cross_paper_synthesizer": "Across papers",
    "methodology_auditor": "Methodology audit",
    "semantic": "Model-written",
    "deterministic": "Rule-based check",
    "graph_structural": "Graph signal",
}


def _gap_feedback(gap: dict, idx: int, run_id: str, project_id: str, existing: dict) -> None:
    gap_key = _gap_feedback_key(gap, idx)
    fb = existing.get(gap_key)
    tag = {1: "useful", -1: "not useful"}.get((fb or {}).get("rating"), "noted") if fb else None
    with st.popover("Feedback" + (f" · {tag}" if tag else "")):
        _feedback_form(f"gap_{run_id}_{gap_key}", project_id=project_id, run_id=run_id,
                       target_type="gap", target_id=gap_key, target_label=gap.get("title", ""),
                       existing=fb, question="Was this gap useful?")


# ── Pages: Settings, New project, New analysis (a four-step form) ──────────────────────────────
_ANY = "Any"
_GAP_TYPES = [_ANY, "Methodology", "Application", "Dataset", "Evaluation", "Theory", "Benchmark"]


def _option_widgets(store: dict, prefix: str) -> None:
    """The per-run options. Settings edits the defaults; the New analysis form edits this run's copy."""
    store["extract_refs"] = st.checkbox(
        "Include cited references", value=store["extract_refs"], key=f"{prefix}_refs",
        help="Looks up each paper's cited references to widen the corpus. Slow: about 3-5 seconds per reference "
             "(more when Semantic Scholar throttles), so 50 references per paper adds roughly 5-10 minutes per "
             "paper. A Semantic Scholar API key (Settings) speeds this up.")
    _limits = ["25", "50", "100", "All"]
    store["ref_limit"] = st.selectbox(
        "References per paper", _limits, index=_limits.index(store["ref_limit"]), key=f"{prefix}_reflimit",
        disabled=not store["extract_refs"], help="Higher limits take longer but improve reference coverage.")
    store["enable_quality_engine"] = st.checkbox(
        "Quality check", value=store["enable_quality_engine"], key=f"{prefix}_quality",
        help="Cross-checks each paper with a second parser and resolves cited references before gap analysis. "
             "The run is blocked if extraction quality is too low.")
    if store["enable_quality_engine"]:
        store["override_quality_gate"] = st.checkbox(
            "Continue even if the quality check fails", value=store["override_quality_gate"],
            key=f"{prefix}_override",
            help="A failed check blocks the run by default. Tick this to proceed anyway; the warning is still recorded.")
    else:
        store["override_quality_gate"] = False
    store["min_gaps_per_paper"] = int(st.number_input(
        "Each paper supports at least this many gaps (0 = off)", min_value=0, max_value=3,
        value=store["min_gaps_per_paper"], key=f"{prefix}_mingaps",
        help="After ranking, gaps are promoted from below the cut so no paper is left without one. "
             "The list can then run slightly longer."))
    store["enable_gap_challenger"] = st.checkbox(
        "Deep gap validation", value=store["enable_gap_challenger"], key=f"{prefix}_challenger",
        help="Adds an extra literature search and a six-level status for each gap. Slower: roughly 30 seconds per gap.")
    _mc = st.session_state["model_config"]
    if any(can_read_images(s) for s in (_mc.spec_for(ROLE_EXTRACTION), _mc.spec_for(ROLE_ANALYSIS), _mc.fallback) if s):
        store["use_vision"] = st.checkbox(
            "Analyze figures and tables", value=store["use_vision"], key=f"{prefix}_vision",
            help="Sends up to 5 figure-heavy pages per paper to a vision model. Slower and uses more tokens.")
    else:
        store["use_vision"] = False
        st.caption("Figure analysis needs a model that can read images (for example Gemini or NVIDIA).")


def _fmt_bytes(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{max(n, 0) // 1024} KB"


def _render_settings() -> None:
    st.button("← Back", key="settings_back", on_click=_go, args=("main",))
    st.markdown("## Settings")
    t_keys, t_models, t_defaults, t_cache, t_backup = st.tabs(
        ["API keys", "Models", "Analysis defaults", "Saved results", "Backup"])

    with t_keys:
        st.caption("Keys stay in this browser session's memory and are never written to disk. A key set in the "
                   "environment (.env, or the hosting platform's secrets) is used when the field is empty.")
        for _pk, _pcfg in PROVIDER_REGISTRY.items():
            _S["typed_keys"][_pk] = st.text_input(
                f"{_pcfg.label.split(' (')[0]} API key", type="password", placeholder="Paste key",
                value=_S["typed_keys"].get(_pk, ""), key=f"key_{_pk}", help=f"Leave blank to use {_pcfg.api_key_env}.")
        st.markdown("**Custom endpoint** — any OpenAI-compatible API")
        _S["custom_base"] = st.text_input(
            "Base URL", value=_S["custom_base"] or os.environ.get("CUSTOM_LLM_BASE_URL", ""),
            key="custom_base_url", placeholder="https://api.example.com/v1")
        _S["custom_key"] = st.text_input("Custom endpoint API key", type="password", placeholder="Paste key",
                                         value=_S["custom_key"], key="key_custom",
                                         help="Leave blank to use CUSTOM_LLM_API_KEY.")
        _S["ss_key"] = st.text_input(
            "Semantic Scholar API key (optional)", type="password", placeholder="Paste key",
            value=_S["ss_key"], key="key_semantic_scholar",
            help="Leave blank to use SEMANTIC_SCHOLAR_API_KEY. Without a key the free, rate-limited tier is used.")
        _now = resolve_keys(_S, PROVIDER_REGISTRY, CUSTOM_PROVIDER)
        st.session_state["_available_providers"] = _now["available"]     # what was just typed counts at once
        if _now.get("custom_base_problem"):
            show_warning(f"The custom endpoint address is not used: {_now['custom_base_problem']}")
        st.markdown("**Status**")
        for _pk in (pk for pk in (*PROVIDER_REGISTRY, CUSTOM_PROVIDER) if provider_allowed(pk)):
            st.caption(f"{_provider_name(_pk)}: {source_label(_now['sources'][_pk])}")
        st.caption(f"Semantic Scholar: {source_label(_now['ss_source'])}")

    with t_models:
        _render_model_picker()

    with t_defaults:
        st.caption("These are the starting values for every new analysis; you can change them per run.")
        _option_widgets(_S, "set")

    with t_cache:
        st.caption("Results of expensive steps are saved and reused when the same paper, model and settings come "
                   "back. Clear one to make the next run recompute it.")
        for _row in db_cache_stats():
            c1, c2, c3 = st.columns([3, 2, 1], vertical_alignment="center")
            c1.markdown(f"**{_row['label']}**")
            c2.caption(f"{_row['rows']} saved · {_fmt_bytes(_row['bytes'])}")
            if c3.button("Clear", key=f"clear_{_row['table']}", disabled=_row["rows"] == 0):
                _n = db_clear_cache(_row["table"])
                st.toast(f"Cleared {_n} saved result(s) for {_row['label']}.")
                st.rerun()
        _trash = deleted_folder_footprint()
        if _trash["projects"]:
            st.markdown("")
            t1, t2 = st.columns([4, 1], vertical_alignment="center")
            t1.markdown("**Deleted projects kept aside**")
            t1.caption(f"{_trash['projects']} project folder(s), {_fmt_bytes(_trash['bytes'])}. Deleting a project keeps its "
                       "folder here in case of a mistake; erase them when you are sure.")
            if t2.button("Erase", key="empty_deleted"):
                _n = empty_deleted_folder()
                st.toast(f"Erased {_n} deleted project folder(s).")
                st.rerun()
        if not hide_paths():
            st.caption(f"Database: {db_path_for_display()}")

    with t_backup:
        st.caption("A backup is one file with every run, paper and report. Keep it somewhere other than this "
                   "computer or server. To restore, stop the app and run `python scripts/backup.py restore <file>`.")
        if st.button("Create backup", key="make_backup"):
            try:
                st.session_state["_backup"] = backup_bytes()
            except Exception as e:
                show_error("The backup could not be created", exc=e)
        _bk = st.session_state.get("_backup")
        if _bk:
            st.download_button(f"Download {_bk[0]} ({_fmt_bytes(len(_bk[1]))})", _bk[1], file_name=_bk[0],
                               mime="application/zip", key="download_backup",
                               on_click=lambda: st.session_state.pop("_backup", None))


def _within_size_limit(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Keep the files under the size limit; say plainly which ones were refused and why."""
    kept = []
    for name, data in files:
        problem = pdf_limits.size_problem(len(data))
        if problem:
            show_warning(f"'{name}' was not added: it is {problem}.")
        else:
            kept.append((name, data))
    return kept


def _render_new_project() -> None:
    st.button("← Back", key="newproject_back", on_click=_go, args=("main",))
    st.markdown("## New project")
    st.caption("A project groups the papers you upload, every analysis of them, and your feedback.")
    _name = st.text_input("Project name", key="np_name", placeholder="e.g., Cystic fibrosis review")
    _desc = st.text_area("Description (optional)", key="np_desc", height=70, placeholder="What this project is about")
    _choices = dict(get_ui_domain_choices())
    _label = st.selectbox("Domain", list(_choices), key="np_domain")
    st.caption(get_domain_config(_choices[_label])["description"])
    _interest = st.text_area("Research interest (optional)", key="np_interest", height=70,
                             placeholder="e.g., Which outcomes are missing for patients under 12?")
    _files = st.file_uploader("Papers (optional, PDF)", type=["pdf"], accept_multiple_files=True, key="np_files")
    _rec = st.checkbox("Use recommended models", value=True, key="np_rec",
                       help="Picks the model for each job from the API keys you have.")
    c1, c2 = st.columns([1, 5])
    if c1.button("Create project", type="primary", key="np_create"):
        try:
            _project = project_store.create_project(_name, _desc, _choices[_label], _interest)
        except ValueError as e:
            show_error(str(e))
            return
        _ids = []
        if _files:
            _ids = project_store.save_papers(
                _project["id"], _within_size_limit([(f.name, f.getvalue()) for f in _files]))
        if _rec and _available:
            _apply_preset("recommended")
        _clear_results()
        st.session_state.current_project_id = _project["id"]
        st.session_state["_pending_project"] = _project["id"]
        st.session_state["_wiz"] = _new_wizard(_project, stored_ids=_ids)
        st.session_state["view"] = "new_analysis"             # straight on to the first analysis
        for _k in ("np_name", "np_desc", "np_interest", "np_files"):
            st.session_state.pop(_k, None)
        st.rerun()
    c2.button("Cancel", key="np_cancel", on_click=_go, args=("main",))


def _new_wizard(project: dict, stored_ids=()) -> dict:
    _choices = dict(get_ui_domain_choices())
    _label = next((lbl for lbl, key in _choices.items() if key == project.get("domain")), next(iter(_choices)))
    return {"step": 1, "project_id": project["id"], "uploads": [], "stored_ids": list(stored_ids), "up_n": 0,
            "domain_label": _label, "interest": project.get("interest") or "", "gap_type": _ANY,
            "opts": {k: _S[k] for k in DEFAULT_OPTIONS}, "run_name": "", "bg": True, "cap": DEFAULT_CAP_TOKENS}


def _wiz_cancel() -> None:
    st.session_state.pop("_wiz", None)
    st.session_state["view"] = "main"


def _wiz_step(n: int) -> None:
    st.session_state["_wiz"]["step"] = n


def _wiz_clear_uploads() -> None:
    w = st.session_state["_wiz"]
    w["uploads"], w["up_n"] = [], w["up_n"] + 1


_WIZ_STEPS = ["Papers", "Research setup", "Options", "Review and run"]


def _render_new_analysis() -> None:
    _proj = get_project(st.session_state.current_project_id) or get_project(DEFAULT_PROJECT_ID)
    w = st.session_state.get("_wiz")
    if not w or w["project_id"] != _proj["id"]:
        w = st.session_state["_wiz"] = _new_wizard(_proj)
    step = w["step"]
    st.markdown(f"## New analysis · {html.escape(_proj['name'])}")
    st.markdown(" → ".join(f"**{i}. {s}**" if i == step else f"{i}. {s}" for i, s in enumerate(_WIZ_STEPS, 1)))

    stored_all = project_store.list_papers(_proj["id"])

    def _selection():
        """(papers, notices): uploads plus the ticked stored papers, same file counted once."""
        try:
            stored_bytes = project_store.read_papers(
                _proj["id"], [p["id"] for p in stored_all if p["id"] in w["stored_ids"]])
        except (OSError, ValueError):
            stored_bytes = []
        return project_store.combine_papers(w["uploads"], stored_bytes)

    papers, notices = _selection()
    papers_ok = 2 <= len(papers) <= 5

    if step == 1:
        st.caption(f"Add 2–5 PDFs (up to {pdf_limits.max_pdf_bytes() // 1024 // 1024} MB and "
                   f"{pdf_limits.max_pdf_pages()} pages each). Gap detection compares papers against each other.")
        up = st.file_uploader("Research papers (PDF)", type=["pdf"], accept_multiple_files=True,
                              key=f"wiz_up_{w['up_n']}", label_visibility="collapsed")
        known = {hashlib.sha256(d).hexdigest() for _, d in w["uploads"]}
        for f in up or []:
            data = f.getvalue()
            if not _within_size_limit([(f.name, data)]):
                continue
            if hashlib.sha256(data).hexdigest() not in known:
                w["uploads"].append((f.name, data))
                known.add(hashlib.sha256(data).hexdigest())
        papers, notices = _selection()
        papers_ok = 2 <= len(papers) <= 5
        if w["uploads"]:
            st.caption("Added: " + ", ".join(n for n, _ in w["uploads"]))
            st.button("Remove uploaded files", key="wiz_clear", on_click=_wiz_clear_uploads)
        if stored_all:
            st.markdown("**Or use papers already in this project**")
            picked = []
            for p in stored_all:
                if st.checkbox(f"{p['filename']} · {p['kb']} KB", value=p["id"] in w["stored_ids"],
                               key=f"wiz_use_{_proj['id']}_{p['id']}"):
                    picked.append(p["id"])
            w["stored_ids"] = picked
        papers, notices = _selection()          # the ticks above changed the selection
        papers_ok = 2 <= len(papers) <= 5
        for n in notices:
            show_warning(n)
        st.caption(f"{len(papers)} paper(s) selected." + ("" if papers_ok else " Choose between 2 and 5."))

    elif step == 2:
        _choices = dict(get_ui_domain_choices())
        w["domain_label"] = st.selectbox("Domain", list(_choices), index=list(_choices).index(w["domain_label"]),
                                         key="wiz_domain")
        st.caption(get_domain_config(_choices[w["domain_label"]])["description"])
        w["interest"] = st.text_area("Research interest", value=w["interest"], key="wiz_interest", height=90,
                                     placeholder="e.g., Which outcomes are missing for patients under 12?")
        w["gap_type"] = st.selectbox("Gap type", _GAP_TYPES, index=_GAP_TYPES.index(w["gap_type"]), key="wiz_gaptype")

    elif step == 3:
        st.caption("Starting from your Settings defaults; changes here apply to this run only.")
        _option_widgets(w["opts"], "wiz")
        w["cap"] = int(st.number_input(
            "Stop the run if it uses more than (tokens)", min_value=50_000, max_value=50_000_000, value=w["cap"],
            step=100_000, key="wiz_cap",
            help="A safety limit on the estimated tokens one run may use. The run stops between stages."))

    else:
        _issues = _model_issues()
        st.markdown(f"**Papers ({len(papers)}):** " + ", ".join(html.escape(n) for n, _ in papers))
        st.markdown(f"**Domain:** {html.escape(w['domain_label'])} · **Gap type:** {w['gap_type']}")
        st.markdown(f"**Research interest:** {html.escape(w['interest']) or '—'}")
        _cfg = st.session_state["model_config"]
        st.caption("Models: " + " · ".join(f"{ROLE_LABELS[r]}: {_cfg.spec_for(r).model}" for r in MAIN_ROLES))
        st.button("Change models or keys", key="wiz_to_settings", on_click=_go, args=("settings",))
        for msg in _issues:
            show_error(msg)
        if papers:
            _est = estimate_run([_pdf_text_chars(hashlib.sha256(d).hexdigest(), d) for _, d in papers],
                                extract_refs=w["opts"]["extract_refs"], gap_challenger=w["opts"]["enable_gap_challenger"])
            _ms = _cfg.spec_for(ROLE_ANALYSIS)
            st.caption(describe_estimate(_est, w["cap"], estimate_cost(_est["tokens"], _ms.provider, _ms.model)))
        w["run_name"] = st.text_input("Run name (optional)", value=w["run_name"], key="wiz_runname",
                                      placeholder="e.g., Diabetes AI review")
        w["bg"] = st.checkbox("Keep running in the background (safe to refresh the page)", value=w["bg"],
                              key="wiz_bg")
        _busy = bool(run_jobs.list_jobs(project_id=_proj["id"], active_only=True, limit=1))
        if _busy:
            show_info("An analysis is already running in this project. Wait for it to finish.")

    # navigation
    cb, cn, cc = st.columns([1, 1, 4])
    if step > 1:
        cb.button("Back", key="wiz_back", on_click=_wiz_step, args=(step - 1,))
    if step < 4:
        cn.button("Next", key="wiz_next", type="primary", on_click=_wiz_step, args=(step + 1,),
                  disabled=(step == 1 and not papers_ok))
    else:
        if cn.button("Run analysis", key="wiz_run", type="primary",
                     disabled=bool(_model_issues()) or not papers_ok or _busy):
            _choices = dict(get_ui_domain_choices())
            st.session_state["_run_request"] = {
                "papers": papers, "run_name": w["run_name"], "domain": _choices[w["domain_label"]],
                "interest": w["interest"], "gap_type": w["gap_type"], "opts": dict(w["opts"]),
                "cap": w["cap"], "bg": w["bg"]}
            st.session_state.pop("_wiz", None)
            st.session_state["view"] = "main"
            st.rerun()
    cc.button("Cancel", key="wiz_cancel", on_click=_wiz_cancel)


# ── Project strip and view switch ────────────────────────────────────────────
_cur_project = get_project(st.session_state.current_project_id) or get_project(DEFAULT_PROJECT_ID)
_cur_project_stats = _project_by_id.get(_cur_project["id"], {})
_proj_runs = list_runs(limit=1000, project_id=_cur_project["id"])
st.markdown(
    '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:0.3rem 1rem;'
    'font-family:Inter,Segoe UI,system-ui,sans-serif;margin:0 0 0.5rem;">'
    '<span style="font-size:0.72rem;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;'
    'color:#4a6580;">Project</span>'
    f'<span style="font-size:1rem;font-weight:600;color:#0b1f3a;">{html.escape(_cur_project["name"])}</span>'
    f'<span style="font-size:0.82rem;color:#4a6580;">{len(_proj_runs)} run(s) · '
    f'{_cur_project_stats.get("paper_count", 0)} paper(s) saved</span>'
    '</div>', unsafe_allow_html=True)

# ── Which page ─────────────────────────────────────────────────────────────────────────────────
_page = st.session_state["view"]
if _page == "settings":
    _render_settings()
    st.stop()
if _page == "new_project":
    _render_new_project()
    st.stop()
if _page == "new_analysis":
    _render_new_analysis()
    st.stop()

st.session_state.setdefault("main_view", "Analysis")
if "_pending_view" in st.session_state:   # set by "Open in Analysis view"; the control can't be set after it exists
    st.session_state["main_view"] = st.session_state.pop("_pending_view")
_view = st.segmented_control("View", ["Analysis", "Project"], key="main_view", label_visibility="collapsed")
if _view == "Project":
    _render_project_view(_cur_project, _proj_runs)
    st.stop()

# Run header: the run on screen, whether loaded or just finished
if st.session_state.current_run_id and st.session_state.results:
    runs_meta = {r["id"]: r for r in list_runs()}
    run_meta  = runs_meta.get(st.session_state.current_run_id, {})
    _hdr = run_header(run_meta, st.session_state.current_run_name, st.session_state.results,
                      get_run_manifest(st.session_state.current_run_id),
                      getattr(st.context, "timezone", None))
    _rm_name, _rm_when, _rm_stats = _hdr["name"], _hdr["when"], _hdr["stats"]
    _chips = "".join(
        f'<span style="font-size:0.72rem;color:#004b93;background:#e5f2ff;border:1px solid #7ab8f5;'
        f'border-radius:10px;padding:0.1rem 0.5rem;">{chip_html}</span>' for chip_html in _hdr["chips"])
    st.markdown(
        '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:0.4rem 1rem;'
        'background:#edf6ff;border:1px solid #c9dff5;border-left:3px solid #0066cc;'
        'border-radius:8px;padding:0.65rem 1.1rem;margin-bottom:0.9rem;'
        'font-family:Inter,Segoe UI,system-ui,sans-serif;">'
        '<span style="font-size:0.72rem;font-weight:600;letter-spacing:0.08em;'
        'text-transform:uppercase;color:#004b93;">Run</span>'
        f'<span style="font-size:0.9rem;font-weight:600;color:#0b1f3a;">{_rm_name}</span>'
        f'<span style="font-size:0.82rem;color:#4a6580;">{esc(_rm_when)}{esc(_rm_stats)}</span>'
        f'<span style="display:flex;gap:0.4rem;margin-left:auto;">{_chips}</span>'
        '</div>',
        unsafe_allow_html=True)

# ── Background run: live checklist ────────────────────────────────────────────
def _fmt_secs(s) -> str:
    s = int(s or 0)
    return f"{s // 60} min {s % 60:02d} s" if s >= 60 else f"{s} s"


def _render_checklist(cl: dict) -> None:
    icons = {"done": "✅", "running": "⏳", "waiting": "⬜", "failed": "❌", "skipped": "➖"}
    st.progress(min(max(cl["pct"], 0), 100) / 100)
    lines = []
    for r in cl["rows"]:
        extra = f" — {_fmt_secs(r['elapsed'])}" if r["elapsed"] is not None and r["state"] in ("done", "running", "failed") else ""
        if r["state"] == "running":
            extra += f" (usually about {_fmt_secs(r['typical'])})"
        weight = "**" if r["state"] == "running" else ""
        lines.append(f"{icons[r['state']]} {weight}{r['label']}{weight}{extra}")
    st.markdown("  \n".join(lines))
    if cl["message"] and cl["status"] == "running":
        st.caption(cl["message"])
    if cl["notice"]:
        show_info(cl["notice"])


@st.fragment(run_every=2)
def _running_job_panel(job_id: str) -> None:
    job = run_jobs.get_job(job_id)
    if job is None or job["status"] in ("done", "failed"):
        if job and job["status"] == "done" and job.get("run_id"):
            if _load_run_into_session(job["run_id"], (job.get("summary_json") or {}).get("name", "")):
                st.session_state["_toast"] = "Analysis finished — results are open."
        st.rerun()                      # full rerun: results (or the failure note) take over
        return
    st.markdown("**Analysis running in the background** — you can refresh or leave this page; it keeps going.")
    _render_checklist(run_jobs.checklist(job))
    if job["warnings_json"]:
        with st.expander(f"{len(job['warnings_json'])} note(s) so far"):
            for w in job["warnings_json"]:
                st.caption(f"⚠️ {w}")


def _finished_job_note(job: dict) -> None:
    cl = run_jobs.checklist(job)
    if job["status"] == "done":
        s = job.get("summary_json") or {}
        if s.get("gate_blocked"):
            show_warning("The quality check failed, so gap analysis was skipped: " + "; ".join(s.get("gate_block_reasons", [])))
        else:
            st.success(f"✅ Done in {_fmt_secs(s.get('duration_seconds'))} — {s.get('n_gaps', 0)} gaps, "
                       f"{s.get('n_proposals', 0)} proposals. Saved as '{s.get('name', '')}'.")
    else:
        show_error("The analysis stopped: " + (job["error"] or "unknown error").split("\n")[0])
        with st.expander("Where it stopped and details"):
            _render_checklist(cl)
            st.code(job["error"] or "", language=None)
    if job["warnings_json"]:
        with st.expander(f"{len(job['warnings_json'])} note(s) from this run"):
            for w in job["warnings_json"]:
                st.caption(f"⚠️ {w}")
    if st.button("Dismiss", key=f"dismiss_{job['id']}"):
        run_jobs.dismiss_job(job["id"])
        st.session_state["active_job_id"] = None
        st.rerun()


if not st.session_state.get("_orphans_checked"):
    st.session_state["_orphans_checked"] = True
    run_jobs.fail_orphans()
if _t := st.session_state.pop("_toast", None):
    st.toast(_t, icon="✅")
_job = run_jobs.get_job(st.session_state["active_job_id"]) if st.session_state.get("active_job_id") else None
if _job is None or _job["project_id"] != _cur_project["id"]:
    _job = run_jobs.unacknowledged_job(_cur_project["id"])           # picked up again after a refresh
    st.session_state["active_job_id"] = _job["id"] if _job else None
if _job and not _job["dismissed"]:
    _job_id = _job["id"]
    if _job["status"] in ("queued", "running"):
        _running_job_panel(_job_id)
    else:
        _finished_job_note(_job)

# ── Empty state: three guided steps ─────────────────────────────────────────────────────────────
if not st.session_state.results and not (_job and not _job["dismissed"]) and not st.session_state.get("_run_request"):
    _has_key = bool(_available)
    st.markdown(
        '<div class="stage-card"><div class="stage-title">Start here</div><div class="stage-body">'
        f'<b>1. Add your keys.</b> {"✓ A key is set." if _has_key else "Open Settings and paste an API key."}<br>'
        f'<b>2. Choose 2–5 papers.</b> Upload PDFs{" or use the papers already in this project" if _cur_project_stats.get("paper_count") else ""}.<br>'
        '<b>3. Run.</b> Gaps with quoted evidence and proposals appear here, usually in 5–10 minutes.'
        '</div></div>', unsafe_allow_html=True)
    st.button("Start a new analysis", key="empty_new_analysis", type="primary", on_click=_go, args=("new_analysis",))

# ── A run requested from the New analysis form ──────────────────────────────────────────────────
_req = st.session_state.pop("_run_request", None)
run_btn = _req is not None
if _req:
    _papers, run_name = _req["papers"], _req["run_name"]
    selected_domain, interest, gap_type = _req["domain"], _req["interest"], _req["gap_type"]
    domain_cfg = get_domain_config(selected_domain)
    _o = _req["opts"]
    extract_refs, ref_limit = _o["extract_refs"], _o["ref_limit"]
    enable_quality_engine, override_quality_gate = _o["enable_quality_engine"], _o["override_quality_gate"]
    enable_gap_challenger, use_vision = _o["enable_gap_challenger"], _o["use_vision"]
    min_gaps_per_paper = _o["min_gaps_per_paper"]
    _token_cap, _run_in_background = _req["cap"], _req["bg"]
    _model_issues_now = _model_issues()

# ── Main Pipeline ─────────────────────────────────────────────────────────────
if run_btn and _papers:
    if _model_issues_now:
        show_error(" ".join(_model_issues_now))
        st.stop()
    if len(_papers) < 2:
        show_warning("Choose at least 2 papers.")
        st.stop()

    st.session_state.running        = True
    st.session_state.pipeline_trace = []
    st.session_state.loaded_run_id  = None

    # Clinova Phase 4, Epic 4.3 token instrumentation -- real, not
    # fabricated (see utils/token_meter.py).
    token_meter = TokenMeter()
    _model_cfg = st.session_state["model_config"]
    # One client-shaped router: each pipeline stage is sent to the model chosen for its role.
    client  = ModelRouter(_model_cfg, _keys, token_meter=token_meter)
    context = {
        "domain":   selected_domain,
        "interest": interest or "General research",
        "gap_type": gap_type,
    }

    _run_options = RunOptions(
        provider_key=_model_cfg.spec_for(ROLE_ANALYSIS).provider,
        model=_model_cfg.spec_for(ROLE_ANALYSIS).model,
        models=_model_cfg.to_dict(),
        use_vision=use_vision,
        extract_refs=extract_refs,
        ref_limit=None if ref_limit == "All" else int(ref_limit),
        enable_quality_engine=enable_quality_engine,
        override_quality_gate=override_quality_gate,
        enable_gap_challenger=enable_gap_challenger,
        enable_graph_persistence=True,   # SQLite makes this free; no longer an opt-in
        project_id=st.session_state.current_project_id,
        ss_api_key=ss_api_key,
        domain_config=domain_cfg,
        git_commit=_GIT_COMMIT,
        token_cap=_token_cap,
        min_gaps_per_paper=min_gaps_per_paper,
    )

    # In the background the run survives a refresh of this page; progress is polled from the database.
    if _run_in_background:
        st.session_state.running = False
        st.session_state["active_job_id"] = start_job(
            papers=_papers, context=context, client=client, options=_run_options,
            name=run_name, token_meter=token_meter)
        st.rerun()
    prog = st.progress(0)
    stat = st.empty()
    def upd(msg, pct):
        prog.progress(pct)
        with stat.container():
            loading_state(f"Analysis running: {msg}")

    try:
        # Clinova Phase 5, Epic 5.6: the Stage 1-6 orchestration that used to
        # live inline here now lives in pipeline/run_pipeline.py, so the web
        # app can run the exact same pipeline instead of a reimplementation.
        # Streamlit-specific concerns (progress bar, trace rows, warnings)
        # are injected as callbacks -- behaviour here is unchanged.
        outcome = run_full_pipeline(
            papers=_papers,
            context=context,
            client=client,
            name=run_name,
            options=_run_options,
            progress=upd,
            trace=_add_trace,
            warn=lambda m: show_warning(f"{m}"),
            token_meter=token_meter,
        )

        results = outcome.results
        st.session_state.results          = results
        st.session_state.ref_papers       = results.get("ref_papers", [])
        st.session_state.ref_diagnostics  = results.get("ref_diagnostics", {})
        st.session_state.ref_resolution_diagnostics = results.get("ref_resolution_diagnostics")
        st.session_state.corpus           = results.get("corpus", [])
        st.session_state.loaded_run_id    = None  # fresh run, not a loaded one
        st.session_state.current_run_id   = outcome.run_id
        st.session_state.current_run_name = outcome.name

        prog.progress(80)
        prog.empty(); stat.empty()
        if outcome.gate_blocked:
            show_warning(
                f"The quality check failed, so gap analysis was skipped: "
                f"{'; '.join(outcome.gate_block_reasons)}. "
                f"Fetched data ({outcome.n_papers} papers, {outcome.n_refs} refs, "
                f"{outcome.n_evidence} evidence objects) was saved as "
                f"'{outcome.name}' ({outcome.run_id[:8]}…). "
                "Run it again with “Continue even if the quality check fails” ticked in the New analysis options to force it."
            )
        else:
            st.success(f"✅ Done — {outcome.n_gaps} gaps, {outcome.n_proposals} proposals. "
                       f"Saved as '{outcome.name}' ({outcome.run_id[:8]}…)")

    except PipelineInputError as e:
        # A caller-input problem (too few papers), not a crash -- reported
        # the same way the old inline `len(uploaded_files) < 2` check was.
        prog.empty(); stat.empty()
        show_warning(str(e))
    except Exception as e:
        prog.empty(); stat.empty()
        show_error("The analysis hit an error", exc=e, details=traceback.format_exc())
    finally:
        st.session_state.running = False

# ── Result screens: Overview, Evidence, and quote-linked Wiki facts ──────────────────────────
def _render_overview(res: dict) -> None:
    c_stats, ref_sum = res.get("corpus_stats", {}), res.get("ref_summary", {})
    cols = st.columns(5)
    for col, (val, lbl) in zip(cols, overview(res)):
        with col:
            st.markdown(f'<div class="stat-box"><span class="stat-number">{esc(val)}</span>'
                        f'<span class="stat-label">{esc(lbl)}</span></div>', unsafe_allow_html=True)
    chips = quality_chips(res)
    if chips:
        st.caption(" · ".join(chips))

    _note = off_note(res)
    if c_stats and _note is None:
        t1, t2, t3, t4 = st.columns(4)
        for col, (val, lbl, color) in zip([t1, t2, t3, t4], [
            (c_stats.get("tier1", 0), "Uploaded PDFs", "#0066cc"),
            (c_stats.get("tier2", 0), "Cited (w/ abstract)", "#087f5b"),
            (c_stats.get("tier3", 0), "Distant refs", "#4a6580"),
            (ref_sum.get("total", 0), "Total corpus", "#8a5a00"),
        ]):
            with col:
                st.markdown(f'<div class="stat-box"><span class="stat-number" style="color:{color};">{esc(val)}</span>'
                            f'<span class="stat-label">{esc(lbl)}</span></div>', unsafe_allow_html=True)
    elif c_stats:
        st.caption(_note)

    warnings = warnings_summary(res)
    if warnings:
        with st.expander(f"⚠️ {len(warnings)} thing(s) to know about this run", expanded=len(warnings) <= 3):
            for w in warnings:
                st.markdown(f"- {html.escape(w)}")

    top = top_gaps(res)
    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Top gaps")
        if not top:
            st.caption("No gaps were found in this run." if not res.get("gate_blocked")
                       else "Gap analysis was skipped (quality gate).")
        for g in top:
            status = f" · {html.escape(g['status'].replace('_', ' '))}" if g["status"] else ""
            st.markdown(f"**{g['rank'] or '–'}. {html.escape(g['title'])}**  \n"
                        f"<span style='color:#4a6580;font-size:0.82rem;'>{g['papers']} supporting paper(s)"
                        f"{status}</span>", unsafe_allow_html=True)
        if top:
            st.button("See all gaps", key="ov_all_gaps", on_click=_set_tab, args=("Gaps",))
    with right:
        st.markdown("#### Leading proposal")
        prop = top_proposal(res)
        if prop is None:
            st.caption("No proposals in this run.")
        else:
            st.markdown(f"**{html.escape(prop['title'])}**")
            st.caption((prop["problem"] or "")[:300])
            st.button("See all proposals", key="ov_all_props", on_click=_set_tab, args=("Proposals",))

    with st.expander("Glossary: what the labels mean"):
        for _term in ("open", "partial", "solved", "unverified", "evidence item", "verified quote", "quote rate",
                      "paper coverage", "orphan signals", "communities", "measured", "opinion", "simulation skipped"):
            st.markdown(f"**{_term.title()}** — {glossary_lookup(_term)}")

    # One row per paper, so a paper that silently contributed nothing is visible.
    _cov = paper_coverage(res)
    if _cov:
        import pandas as pd
        _bad = [r for r in _cov if r["status"] != "ok"]
        with st.expander(f"Paper coverage — {len(_cov) - len(_bad)} of {len(_cov)} papers fully processed"
                         + (" · ⚠️ check" if _bad else ""), expanded=bool(_bad)):
            _table(pd.DataFrame([{
                "Paper": r["title"][:44] + ("…" if len(r["title"]) > 44 else ""),
                "Type": study_type_label(r["study_type"]).replace("systematic or narrative ", "")
                                                         .replace(" or questionnaire", "").replace(" or lab", ""),
                "Wiki": r["wiki_items"], "Evid.": r["evidence"], "Quoted": r["quoted"],
                "Entities": r["entities"], "Gaps": r["gaps"], "Props": r["proposals"],
                "OK": "✅" if r["status"] == "ok" else "⚠️ " + "; ".join(r["problems"]),
            } for r in _cov]), hide_index=True)
            st.caption("Wiki = facts compiled from the paper · Evid. = evidence items · Quoted = items with a verified "
                       "quote and page · Entities = knowledge-graph entities · Gaps / Props = gaps and proposals "
                       "that rest on the paper.")


def _set_tab(name: str) -> None:
    st.session_state["result_tab"] = name


def _render_evidence(res: dict) -> None:
    rows = evidence_rows(res)
    st.markdown("### Evidence")
    if not rows:
        empty_state("No stored evidence items", "Runs saved before evidence was kept do not have any; run the analysis again to get them.")
        return
    st.caption("Every item the reader extracted from the papers, with the passage it rests on. "
               "Filter, then read the quote in context.")
    c1, c2, c3 = st.columns([2, 2, 1])
    papers = sorted({r["paper"] for r in rows})
    titles = paper_titles(res)
    paper = c1.selectbox("Paper", ["All papers", *papers], key="ev_paper",
                         format_func=lambda p: p if p == "All papers" else titles.get(p, p)[:60])
    types = c2.multiselect("Type", sorted({r["type"] for r in rows}), key="ev_types")
    only_cited = c3.checkbox("Cited by a gap", key="ev_cited")
    d1, d2, d3 = st.columns([1, 1, 2])
    page_only = d1.checkbox("Has a page number", key="ev_page")
    quote_only = d2.checkbox("Has a quote", key="ev_quote")
    query = d3.text_input("Search the text", key="ev_query", placeholder="e.g., FEV1")
    shown = filter_evidence(rows, paper=None if paper == "All papers" else paper, types=tuple(types),
                            has_page=True if page_only else None, has_quote=True if quote_only else None,
                            cited_only=only_cited, query=query)
    st.caption(f"{len(shown)} of {len(rows)} items")
    for r in shown[:60]:
        where = citation(r)
        cited = ("  \n<span style='color:#087f5b;font-size:0.8rem;'>Cited by: "
                 + "; ".join(f"#{g['rank'] or '–'} {html.escape(g['title'][:70])}" for g in r["cited_by"])
                 + "</span>") if r["cited_by"] else ""
        quote = (f"  \n<span style='color:#4a6580;font-size:0.82rem;'>“{html.escape(r['quote'])}”</span>"
                 if r["quote"] else "  \n<span style='color:#8a5a00;font-size:0.8rem;'>no verified quote</span>")
        st.markdown(
            f"**{html.escape(r['type'])}** · {html.escape(titles.get(r['paper'], r['paper'])[:50])}"
            f"{' · ' + html.escape(where) if where else ''} · {html.escape(r['confidence'])}  \n"
            f"{html.escape(r['text'])}{quote}{cited}", unsafe_allow_html=True)
        st.markdown("---")
    if len(shown) > 60:
        st.caption(f"Showing the first 60 of {len(shown)}; narrow the filters to see the rest.")


def _fact(text: str, evidence: list, color: str = "#0b1f3a") -> None:
    """A wiki fact, with the page and quote it rests on when the evidence contains it."""
    hit = match_evidence(str(text), evidence)
    extra = ""
    if hit:
        where = citation(hit)
        extra = (f"<br><span style='color:#4a6580;font-size:0.76rem;'>{html.escape(where) + ' · ' if where else ''}"
                 f"{('“' + html.escape(hit['quote'][:160]) + '”') if hit['quote'] else 'evidence item'}</span>")
    st.markdown(f'<div class="wiki-item" style="color:{color};margin-bottom:0.3rem;">• {html.escape(str(text))}{extra}</div>',
                unsafe_allow_html=True)


# ── Gaps and Proposals screens ──────────────────────────────────────────────────────────────────
_STATUS_BADGES = {
    "open": ("Open", "#087f5b", "#e7f8f1", "#83d7b1"), "partial": ("Partial", "#8a5a00", "#fff7e6", "#f0c36a"),
    "solved": ("Solved", "#c81e1e", "#fff1f1", "#f0a0a0"), "pending": ("Pending", "#4a6580", "#f2f5f8", "#c9dff5"),
    "unverified": ("Not checked", "#8a5a00", "#fff4d6", "#e8c66a"),
}
_CHALLENGER_BADGES = {
    "INSUFFICIENT_EVIDENCE": ("Insufficient evidence", "#4a6580", "#f2f5f8", "#c9dff5"),
    "OPEN": ("Challenger: open", "#087f5b", "#e7f8f1", "#83d7b1"),
    "PARTIALLY_OPEN": ("Partially open", "#8a5a00", "#fff7e6", "#f0c36a"),
    "CONTESTED": ("Contested", "#a94ba0", "#f9edf8", "#dcaad9"),
    "LIKELY_CLOSED": ("Likely closed", "#c8681e", "#fff1e6", "#f0b380"),
    "CLOSED": ("Closed", "#c81e1e", "#fff1f1", "#f0a0a0"),
}
_STATUS_HELP = {
    "open": "No published paper found that already does this.", "partial": "Related work exists, but not this exactly.",
    "solved": "A published paper already does what this gap proposes.",
    "pending": "Not yet checked against the literature.",
    "unverified": "The literature search was unavailable, so this was not checked.",
}


def _go_evidence() -> None:
    st.session_state["result_tab"] = "Evidence"
    st.session_state["ev_cited"] = True


def _go_gaps() -> None:
    st.session_state["result_tab"] = "Gaps"


def _render_gaps(res: dict) -> None:
    rows = gap_rows(res)
    st.markdown("### Research gaps")
    if not rows:
        empty_state("No gaps in this run" if not res.get("gate_blocked") else "Gap analysis was skipped",
                    "Add more papers or a sharper research interest and run again." if not res.get("gate_blocked")
                    else "The quality check failed; see the Overview for the reasons.")
    else:
        counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("open", "partial", "solved")}
        st.caption(f"{len(rows)} gaps · {counts['open']} open · {counts['partial']} partial · {counts['solved']} solved. "
                   "Status says whether published work already covers the gap.")
        c1, c2, c3, c4 = st.columns([1.2, 1.4, 1.4, 1.6])
        how = c1.selectbox("Sort by", list(GAP_SORTS), key="gap_sort")
        statuses = c2.multiselect("Status", sorted({r["status"] for r in rows}), key="gap_status",
                                  format_func=lambda s: _STATUS_BADGES.get(s, (s.title(),))[0])
        finders = c3.multiselect("Found by", sorted({r["finder"] for r in rows}), key="gap_finders")
        titles = paper_titles(res)
        paper = c4.selectbox("Paper", ["All papers", *sorted(titles)], key="gap_paper",
                             format_func=lambda p: p if p == "All papers" else titles[p][:40])
        query = st.text_input("Search gaps", key="gap_query", placeholder="words in a title or description")
        shown = sort_gaps(filter_gaps(rows, statuses=tuple(statuses), finders=tuple(finders),
                                      paper=None if paper == "All papers" else paper, query=query), how)
        st.caption(f"Showing {len(shown)} of {len(rows)}")

        _fb_run = st.session_state.current_run_id
        _fb_project = (get_run_row(_fb_run) or {}).get("project_id") if _fb_run else None
        _fb_existing = ({f["target_id"]: f for f in list_feedback(run_id=_fb_run, target_type="gap")} if _fb_run else {})
        for r in shown[:40]:
            g = r["gap"]
            label, color, bg, border = _STATUS_BADGES.get(r["status"], (r["status"].title() or "—", "#4a6580", "#f2f5f8", "#c9dff5"))
            _def = glossary_lookup(label)
            chips = "".join(_badge(html.escape(str(p)[:28]), "#004b93", "#e5f2ff", "#7ab8f5") for p in r["papers"][:4])
            score = f" · {r['score']}/5" if r["score"] is not None else ""
            ch = _CHALLENGER_BADGES.get(g.get("challenger_status"))
            st.markdown(
                f'<div class="gap-card {esc(r["status"])}"><div class="gap-title">'
                f'{("#" + str(r["rank"]) + " ") if r["rank"] else ""}{html.escape(r["title"])}</div>'
                f'<div class="gap-meta">{_badge(label, color, bg, border, title=_def)}'
                f'{_badge(html.escape(r["finder"]) + score, "#4a6580", "#f2f5f8", "#c9dff5")}'
                f'{_badge(*ch, title=glossary_lookup(ch[0])) if ch else ""}</div><div style="margin-top:0.3rem;">{chips}</div></div>',
                unsafe_allow_html=True)
            with st.expander("Details, evidence and sources"):
                st.markdown(html.escape(str(g.get("description", ""))))
                st.caption(_STATUS_HELP.get(r["status"], ""))
                if g.get("validation_reasoning"):
                    st.markdown(f"**Literature check:** {html.escape(str(g['validation_reasoning']))}")
                if g.get("critique"):
                    _sc = g.get("scores") or {}
                    st.caption(f"Critic: {g['critique']} · novelty {_sc.get('novelty', '–')} · importance "
                               f"{_sc.get('importance', '–')} · feasibility {_sc.get('feasibility', '–')} (1–5)")
                if g.get("feedback_note"):
                    st.caption(f"Ranking adjusted by your earlier feedback: {g['feedback_note']}.")
                if g.get("confidence_caveat"):
                    st.caption(f"⚠️ {g['confidence_caveat']}")
                if g.get("evidence"):
                    st.markdown("**Evidence from the papers**")
                    for line in g["evidence"][:6]:
                        st.markdown(f"- {html.escape(str(line))}")
                if r["n_evidence"]:
                    st.button(f"See the {r['n_evidence']} evidence items", key=f"gap_ev_{r['index']}", on_click=_go_evidence)
                if r["links"]:
                    st.markdown("**Closest published work**")
                    for l in r["links"][:5]:
                        year = f" ({l['year']})" if l["year"] else ""
                        st.markdown(f"- [{l['title']}]({l['url']}){year}" if l["url"] else f"- {l['title']}{year} · no link")
                if g.get("search_query_used"):
                    st.caption("Searched: " + g["search_query_used"])
                funnel = g.get("challenge_funnel")
                if funnel:
                    st.caption(f"Gap Challenger: coverage {funnel.get('search_coverage_score', 0):.2f} (threshold 0.60) · "
                               f"{funnel.get('candidate_count', 0)} found → {funnel.get('relevant_count', 0)} relevant · "
                               f"{funnel.get('contradiction_count', 0)} contradicting")
                elif g.get("challenger_error"):
                    st.caption(f"Gap Challenger failed for this gap: {g['challenger_error']}")
            if _fb_project:
                _gap_feedback(g, r["index"], _fb_run, _fb_project, _fb_existing)
        if len(shown) > 40:
            st.caption(f"Showing the first 40 of {len(shown)}; narrow the filters to see the rest.")

    _rejected = res.get("rejected_gaps") or []
    if _rejected:
        with st.expander(f"Considered and set aside by the critic ({len(_rejected)})"):
            st.caption("Candidates the finder agents proposed that the critic merged into another gap, judged generic "
                       "or already answered, or ranked below the top list.")
            for g in _rejected:
                _item(f"{html.escape(g.get('title', 'Untitled'))} — {html.escape(str(g.get('rejected_reason', '')))}")
    _supp = res.get("supplementary_gaps") or []
    if _supp:
        with st.expander(f"Supplementary signals — not validated ({len(_supp)})"):
            st.caption("Rule-based checks and knowledge-graph hints. They are leads, not findings: they are not "
                       "searched against the literature or used for proposals.")
            for g in _supp:
                _item(f"{html.escape(g.get('title', 'Untitled'))}: {html.escape(str(g.get('description', '')))}")


def _render_proposals(res: dict, proposals: list) -> None:
    rows = proposal_rows(res)
    st.markdown("### Research proposals")
    _open_gaps = [g for g in res.get("gaps", []) if g.get("validation_status") in ("open", "partial")]
    if not proposals and _open_gaps:
        # A run can finish with no proposals (the model's reply was unreadable);
        # fill them in for this run instead of repeating the whole analysis.
        show_warning(f"This run has no proposals, although it found {len(_open_gaps)} open or partial gaps.")
        if st.button("Generate proposals now", key="gen_proposals_now", type="primary",
                     help="Runs only the proposal step on this run's gaps (about 10–30 seconds)."):
            try:
                with st.spinner("Generating proposals…"):
                    _pclient = ModelRouter(st.session_state["model_config"], _keys)
                    _new = redo_proposal_step(res, res.get("context", {}), _pclient, domain_config=get_domain_config(
                        res.get("context", {}).get("domain", "General AI/ML")))
                if not _new:
                    show_error("The model returned nothing usable. Try again, or choose another Analysis model.")
                else:
                    res["proposals"] = _new
                    st.session_state.results = res
                    _rid = st.session_state.current_run_id
                    if _rid:
                        update_run_proposals(_rid, _new)
                        try:
                            project_store.refresh_run_results(st.session_state.current_project_id, _rid, res,
                                                              res.get("context", {}), st.session_state.comp_results)
                        except Exception:
                            pass
                    st.rerun()
            except Exception as e:
                show_error("Could not generate proposals", exc=e)
    if not rows:
        return
    st.caption(f"{len(rows)} proposals. Star the ones worth pursuing: starred and unstarred choices feed later runs.")
    _fb_run = st.session_state.current_run_id
    _fb_project = (get_run_row(_fb_run) or {}).get("project_id") if _fb_run else None
    _stars = ({f["target_id"]: f for f in list_feedback(run_id=_fb_run, target_type="proposal")} if _fb_run else {})

    def _toggle_star(key: str, label: str, on: bool) -> None:
        if on:
            upsert_feedback(_fb_project, _fb_run, "proposal", key)                  # clear
        else:
            upsert_feedback(_fb_project, _fb_run, "proposal", key, rating=1, reason="Useful and well supported",
                            target_label=label)

    for r in rows:
        p = r["proposal"]
        starred = (_stars.get(r["key"]) or {}).get("rating") == 1
        verdict = f" · {r['verdict']}" if r["verdict"] else ""
        head = f"{'★ ' if starred else ''}#{r['index'] + 1} {r['title']}{verdict}"
        with st.expander(head):
            effort = r["effort"]
            ec = {"short": "#087f5b", "medium": "#8a5a00", "long": "#c81e1e"}.get(
                (effort.split()[0].lower() if effort else ""), "#4a6580")
            st.markdown(_badge((r["confidence"] or "–").title() + " confidence", "#004b93", "#e5f2ff", "#7ab8f5")
                        + (_badge(html.escape(effort), ec, "#e7f8f1", ec) if effort else "")
                        + (_badge("Risk: " + html.escape(str(r["risk"]))[:30], "#4a6580", "#f2f5f8", "#c9dff5") if r["risk"] else ""),
                        unsafe_allow_html=True)
            if r["gap_title"]:
                st.markdown(f"**Addresses gap #{r['gap_rank'] or '–'}:** {html.escape(r['gap_title'])}")
                st.button("Show the gaps", key=f"prop_gap_{r['index']}", on_click=_go_gaps)
            for label, key in (("Problem", "problem_statement"), ("Methodology", "methodology"),
                               ("Novelty", "novelty"), ("Expected contribution", "expected_contribution")):
                if p.get(key):
                    st.markdown(f"**{label}**  \n{html.escape(str(p[key]))}")
            _rv = p.get("review")
            if _rv:
                _rs = _rv.get("scores") or {}
                st.caption(f"Reviewer: {'revised after review' if _rv.get('revised') else _rv.get('verdict', '')} · "
                           f"specificity {_rs.get('specificity', '–')} · novelty {_rs.get('novelty', '–')} · "
                           f"feasibility {_rs.get('feasibility', '–')} · impact {_rs.get('impact', '–')} (1–5)"
                           + (f"  \nIssues raised: {'; '.join(_rv['issues'])}" if _rv.get("issues") else ""))
            if p.get("suggested_experiments"):
                st.markdown("**Suggested experiments**")
                for exp in p["suggested_experiments"]:
                    st.markdown(f"- {html.escape(str(exp))}")
            if p.get("builds_on"):
                st.markdown("**Builds on:** " + "; ".join(html.escape(str(b)) for b in p["builds_on"]))
            if _fb_project:
                st.button("Remove star" if starred else "★ Star this proposal", key=f"star_{r['index']}",
                          on_click=_toggle_star, args=(r["key"], r["title"], starred))

    if len(rows) >= 2:
        st.markdown("#### Compare two proposals")
        labels = {r["index"]: f"#{r['index'] + 1} {r['title'][:60]}" for r in rows}
        picked = st.multiselect("Choose two", list(labels), key="prop_compare", format_func=labels.get, max_selections=2)
        if len(picked) == 2:
            import pandas as pd
            a, b = rows[picked[0]], rows[picked[1]]
            _table(pd.DataFrame([{"": c["field"], labels[picked[0]]: c["a"], labels[picked[1]]: c["b"]}
                                 for c in compare_proposals(a, b)]), hide_index=True)


def _render_relations(res: dict, graph: dict) -> None:
    """The graph as a table: every relationship with the paper, page and quote it rests on."""
    ev_by_id = {r["id"]: r for r in evidence_rows(res)}
    rows = relation_rows(graph, ev_by_id)
    if not rows:
        return
    summary = grounding_summary(graph)
    st.markdown("#### Relations and their evidence")
    st.caption(f"{summary['grounded']} of {summary['relations']} relations cite a quoted passage of a paper."
               if summary["relations"] else "")
    c1, c2, c3 = st.columns([2, 2, 2])
    kinds = sorted({r["relation"] for r in rows})
    chosen = c1.multiselect("Relation", kinds, key="gr_relation")
    papers = sorted({r["paper"] for r in rows if r["paper"]})
    paper = c2.selectbox("Paper", ["All papers", *papers], key="gr_paper")
    entity = c3.text_input("Entity", key="gr_entity", placeholder="e.g., CFTR")
    shown = filter_relations(rows, relations=tuple(chosen), paper=None if paper == "All papers" else paper,
                             entity=entity)
    st.caption(f"{len(shown)} of {len(rows)} relations")
    import pandas as pd
    _table(pd.DataFrame([{
        "From": r["source"], "Relation": r["relation"], "To": r["target"],
        "Paper": r["paper"][:40], "Page": r["page"] if r["page"] is not None else "—",
        "Quote": (r["quote"][:140] + ("…" if len(r["quote"]) > 140 else "")),
    } for r in shown[:300]]), hide_index=True)
    note = orphan_explanation(graph)
    if note:
        st.caption(note)


# ── Results ────────────────────────────────────────────────────────────────────
if st.session_state.results:
    res        = st.session_state.results
    gaps       = res.get("gaps", [])
    proposals  = res.get("proposals", [])
    graph      = res.get("graph", {})
    wiki       = res.get("wiki", {})
    wiki_pages = wiki.get("pages", [])
    context    = res.get("context", {})
    ref_papers = st.session_state.ref_papers or res.get("ref_papers", [])
    ref_diagnostics = st.session_state.ref_diagnostics or res.get("ref_diagnostics", {})
    corpus     = st.session_state.corpus or res.get("papers", [])

    # Domain banner
    res_cfg = get_domain_config(context.get("domain","General AI/ML"))
    st.markdown(f"""
    <div style="background:#edf6ff;border:1px solid #7ab8f5;border-radius:8px;
                padding:0.8rem 1.2rem;margin:0.8rem 0;">
      <span style="font-size:1.4rem;">{res_cfg['icon']}</span>
      <span style="font-size:0.9rem;color:#0b1f3a;font-weight:500;margin-left:0.8rem;">
        {esc(context.get('domain',''))} — Domain-Tuned Analysis</span>
    </div>""", unsafe_allow_html=True)

    # Feedback on the whole run (per-gap feedback is in the Research Gaps tab).
    _rf_run = st.session_state.current_run_id
    _rf_project = (get_run_row(_rf_run) or {}).get("project_id") if _rf_run else None
    if _rf_project:
        _rf_existing = next(iter(list_feedback(run_id=_rf_run, target_type="run")), None)
        with st.expander("Feedback on this run" + (" · added" if _rf_existing else "")):
            _feedback_form(f"run_{_rf_run}", project_id=_rf_project, run_id=_rf_run, target_type="run",
                           target_id="", target_label="Overall analysis", existing=_rf_existing,
                           question="Was this analysis useful overall?")

    # B23 fix: this run's gate-blocked status must stay visible after the
    # original show_warning() toast is gone (e.g. reloading a saved run from
    # history) -- gaps/proposals being empty here is a gate block, not a
    # genuinely gap-free corpus, and that distinction matters to the user.
    if res.get("gate_blocked"):
        reasons = "; ".join(res.get("gate_block_reasons", [])) or "corpus below quality threshold"
        show_warning(
            f"This run's quality check failed, so gap analysis was skipped: {reasons}. "
            "Papers, references, wiki, and evidence below were still fetched and saved. "
            "Run it again with “Continue even if the quality check fails” ticked in the New analysis options to force it."
        )

    _TABS = ["Overview", "Evidence", "Wiki", "References", "Graph", "Gaps", "Proposals", "Lab", "Trace", "Export"]
    if st.session_state.get("result_tab") not in _TABS:
        st.session_state["result_tab"] = "Overview"
    _tab = st.segmented_control("Section", _TABS, key="result_tab", label_visibility="collapsed") or "Overview"

    # Only the section on screen is built: the other nine cost nothing until opened.
    if _tab == "Overview":
        _render_overview(res)

    if _tab == "Evidence":
        _render_evidence(res)

    # ── Tab 1: Wiki Pages ──────────────────────────────────────────────────────
    if _tab == "Wiki":
        st.markdown("### Compiled Wiki Pages")
        _wiki_evidence = evidence_rows(res)
        for i, paper_res in enumerate(res.get("papers",[])):
            page  = paper_res.get("wiki", {})
            title = page.get("title", paper_res.get("filename", f"Paper {i+1}"))
            with st.expander(f"T1 Uploaded PDF · {title}", expanded=False):
                st.markdown(
                    f'{_tier_badge(1)} '
                    f'<span style="font-weight:700;color:#004b93;">{html.escape(str(title))}</span>',
                    unsafe_allow_html=True,
                )
                _ev = [r for r in _wiki_evidence if r["paper"] == paper_res.get("filename")]
                _stype = (res.get("paper_profiles") or {}).get(paper_res.get("filename"), {}).get("study_type")
                if _stype:
                    st.caption(f"Study type: {study_type_label(_stype)} · {len(_ev)} evidence item(s)")
                c1,c2 = st.columns(2)
                with c1:
                    _section_label("Contributions")
                    for c in page.get("contributions",[])[:5]: _fact(c, _ev)
                    st.markdown("")
                    _section_label("Methods")
                    for m in page.get("methods",[])[:5]: _fact(m, _ev)
                with c2:
                    _section_label("Limitations ⚠️")
                    for lim in page.get("limitations",[])[:4]: _fact(lim, _ev, "#c81e1e")
                    st.markdown("")
                    _section_label("Future Work 🔭")
                    for fw in page.get("future_work",[])[:4]: _fact(fw, _ev, "#087f5b")
                tree_sum = paper_res.get("tree_summary","")
                if tree_sum:
                    with st.expander("🌲 PageIndex Tree"):
                        st.code(tree_sum, language=None)
                tables = paper_res.get("tables",[])
                if tables:
                    with st.expander(f"📊 {len(tables)} table(s)"):
                        for t in tables[:3]:
                            st.markdown(f"**Table p.{t['page']}:**")
                            st.code(t["content"][:400])

        cross_links = wiki.get("cross_links",{})
        shared = cross_links.get("shared_concepts",[])
        if shared:
            st.markdown("### Cross-Paper Links")
            for link in shared[:6]:
                st.markdown(_card(
                    "Shared Concept",
                    f"<strong>{esc(link.get('concept',''))}</strong> — {esc(link.get('context',''))}<br>"
                    f"<span style='font-family:\"DM Mono\",monospace;font-size:0.7rem;color:#0066cc;'>"
                    f"{esc(', '.join(link.get('papers',[])))}</span>"
                ), unsafe_allow_html=True)

    # ── Tab 2: Reference Corpus ────────────────────────────────────────────────
    if _tab == "References":
        st.markdown("### Reference Corpus")
        if ref_diagnostics:
            d1,d2,d3,d4 = st.columns(4)
            for col,(val,lbl,color) in zip([d1,d2,d3,d4],[
                (ref_diagnostics.get("raw_entries",0), "Raw Citations", "#0066cc"),
                (ref_diagnostics.get("structured_entries",0), "LLM Parsed", "#087f5b"),
                (ref_diagnostics.get("fallback_entries",0), "Fallback Parsed", "#8a5a00"),
                (ref_diagnostics.get("duplicates_skipped",0), "Duplicates", "#4a6580"),
            ]):
                with col:
                    st.markdown(f'<div class="stat-box"><span class="stat-number" '
                                f'style="font-size:1.3rem;color:{color};">{esc(val)}</span>'
                                f'<span class="stat-label">{esc(lbl)}</span></div>',
                                unsafe_allow_html=True)
            if ref_diagnostics.get("errors"):
                with st.expander("Reference extraction warnings"):
                    for err in ref_diagnostics.get("errors", [])[:20]:
                        show_warning(err)
            st.markdown("")

        if not ref_papers:
            if not res.get("ref_summary",{}).get("total"):
                show_info("No references are available yet. Tick “Include cited references” when you start an analysis.")
            else:
                show_info("Reference summary exists, but detailed references were not saved in this older run. Re-run once to persist them.")
        else:
            summary = summarise_reference_corpus(ref_papers)
            ra,rb,rc,rd = st.columns(4)
            for col,(val,lbl,color) in zip([ra,rb,rc,rd],[
                (summary["total"],"Total Refs","#0066cc"),
                (summary["tier2_abstract"],"With Abstract","#087f5b"),
                (summary["tier3_title"],"Title Only","#4a6580"),
                (summary["year_range"],"Year Range","#8a5a00"),
            ]):
                with col:
                    st.markdown(f'<div class="stat-box"><span class="stat-number" '
                                f'style="font-size:1.3rem;color:{color};">{esc(val)}</span>'
                                f'<span class="stat-label">{esc(lbl)}</span></div>',
                                unsafe_allow_html=True)
            st.markdown("")

            # Filter
            fc1,fc2,fc3 = st.columns([1, 1, 1])
            with fc1:
                tier_filter = st.selectbox("Filter by tier",
                                           ["All","Tier 2 (with abstract)","Tier 3 (title only)"],
                                           key="ref_tier_filter")
            with fc2:
                search_q = st.text_input("Search references", placeholder="keyword…",
                                          key="ref_search")
            with fc3:
                ref_view = st.selectbox("View references as",
                                        ["Grouped by source paper", "Cards", "Table"],
                                        key="ref_view")

            filtered = ref_papers
            if "Tier 2" in tier_filter:
                filtered = [r for r in ref_papers if r.get("tier")==2]
            elif "Tier 3" in tier_filter:
                filtered = [r for r in ref_papers if r.get("tier")==3]
            if search_q:
                q = search_q.lower()
                filtered = [r for r in filtered
                            if q in ((r.get("title") or "")+" "+(r.get("abstract") or "")).lower()]

            st.markdown(f'<div style="font-size:0.8rem;color:#4a6580;margin-bottom:0.8rem;">'
                        f'Showing {len(filtered)} of {len(ref_papers)} references</div>',
                        unsafe_allow_html=True)

            def _render_ref(ref, idx=None):
                tier    = ref.get("tier",3)
                t_class = "tier-2-card" if tier==2 else "tier-3-card"
                year    = ref.get("year","")
                doi     = ref.get("doi","")
                found_in = ref.get("found_in_paper","")
                title_text = html.escape(str(ref.get("title") or "Unknown"))
                abstract = html.escape(str(ref.get("abstract") or "")[:240])
                raw_reference = ref.get("raw_reference", "")
                source = html.escape(str(ref.get("source") or ""))
                citations = ref.get("citations", 0)
                oa_url = ref.get("open_access_url")
                url = ref.get("url") or (f"https://doi.org/{doi}" if doi else "")
                venue = html.escape(str(ref.get("venue") or ""))
                authors = html.escape(", ".join(ref.get("authors", [])[:4])) if isinstance(ref.get("authors"), list) else ""
                prefix = f"#{idx} " if idx is not None else ""

                st.markdown(
                    f'<div class="ref-card {t_class}">'
                    f'<div class="ref-title">{_tier_badge(tier)} {prefix}{title_text}</div>'
                    f'<div class="ref-meta">{html.escape(str(year))} &nbsp;·&nbsp; {html.escape(str(doi)[:40]) if doi else "no DOI"}'
                    f' &nbsp;·&nbsp; source: {source or "parsed"}'
                    f' &nbsp;·&nbsp; citations: {html.escape(str(citations or 0))}'
                    f' &nbsp;·&nbsp; cited in: {html.escape(str(found_in))}</div>'
                    + (f'<div style="font-size:0.76rem;color:#4a6580;margin-top:0.2rem;">{authors}</div>' if authors else '')
                    + (f'<div style="font-size:0.76rem;color:#4a6580;margin-top:0.2rem;font-style:italic;">{venue}</div>' if venue else '')
                    + (f'<div style="font-size:0.82rem;color:#344054;margin-top:0.5rem;line-height:1.55;">{abstract}…</div>'
                       if abstract else '')
                    + '</div>',
                    unsafe_allow_html=True,
                )
                link_cols = st.columns([1, 1, 5])
                if url:
                    link_cols[0].markdown(f"[DOI/Source]({url})")
                if oa_url:
                    link_cols[1].markdown(f"[Open PDF]({oa_url})")
                if raw_reference:
                    with st.expander(f"Raw citation: {title_text[:80]}"):
                        st.code(raw_reference, language=None)

            if ref_view == "Table":
                import pandas as pd
                rows = []
                for i, r in enumerate(filtered, 1):
                    rows.append({
                        "#": i,
                        "Title": r.get("title", "Unknown"),
                        "About / Abstract": (r.get("abstract") or r.get("raw_reference") or "")[:300],
                        "Year": r.get("year", ""),
                        "Tier": r.get("tier", ""),
                        "Source API": r.get("source", ""),
                        "Citations": r.get("citations", 0),
                        "Cited In": r.get("found_in_paper", ""),
                        "DOI": r.get("doi", ""),
                    })
                table_full_width(pd.DataFrame(rows), height=520)
            elif ref_view == "Grouped by source paper":
                grouped_refs = {}
                for r in filtered:
                    grouped_refs.setdefault(r.get("found_in_paper") or "Unknown source paper", []).append(r)
                for source_paper, refs_for_paper in grouped_refs.items():
                    with st.expander(f"{source_paper} · {len(refs_for_paper)} fetched references", expanded=False):
                        tier2_count = sum(1 for r in refs_for_paper if r.get("tier") == 2)
                        abstract_count = sum(1 for r in refs_for_paper if r.get("abstract"))
                        st.markdown(
                            f'<div class="stage-card"><div class="stage-title">Fetched From This Uploaded Paper</div>'
                            f'<div class="stage-body">{len(refs_for_paper)} references · {tier2_count} enriched · '
                            f'{abstract_count} with abstract/about text</div></div>',
                            unsafe_allow_html=True,
                        )
                        for i, ref in enumerate(refs_for_paper[:40], 1):
                            _render_ref(ref, idx=i)
                        if len(refs_for_paper) > 40:
                            show_info(f"Showing first 40 of {len(refs_for_paper)} references for this source paper. Use search or table view to inspect the rest.")
            else:
                for i, ref in enumerate(filtered[:80], 1):
                    _render_ref(ref, idx=i)

    # ── Tab 3: Knowledge Graph ─────────────────────────────────────────────────
    if _tab == "Graph":
        st.markdown("### Knowledge Graph (LazyGraphRAG)")
        stats = graph.get("stats",{})
        graph_diag = graph.get("diagnostics", {})
        if graph_diag.get("used_fallback"):
            show_warning("The model could not build a graph from the evidence, so a simpler graph was made from each paper's summary. It has fewer and weaker links.")
        elif graph_diag.get("grounded"):
            show_info(f"Built from the papers' quoted evidence: {graph_diag.get('llm_entities', 0)} entities and "
                    f"{graph_diag.get('llm_relationships', 0)} relationships, each citing the passage that states it.")
        elif graph_diag:
            if graph_diag.get("grounded_failure"):
                st.caption(f"Evidence-based graph not used: {graph_diag['grounded_failure']}.")
            show_info(f"The model built the graph from the paper summaries: {graph_diag.get('llm_entities', 0)} entities and {graph_diag.get('llm_relationships', 0)} relationships.")

        # Clinova Phase 3, Epic 3.1 (FR-7): graph build status + quality
        # score, computed by pipeline/graph_quality.py. None on a
        # gate-blocked run (Stage 3 never ran). A DEGRADED/FALLBACK badge
        # here is the same signal that already downgraded confidence on
        # any graph-structural gap -- surfaced, not just applied silently.
        gq = res.get("graph_quality")
        if gq:
            _status_style = {
                "CLEAN": ("✅", "#1a7f37"), "DEGRADED": ("⚠️", "#9a6700"), "FALLBACK": ("🛑", "#b42318"),
            }.get(gq["build_status"], ("ℹ️", "#57606a"))
            icon, color = _status_style
            st.markdown(
                f'<div style="border:1px solid {color}22; background:{color}11; '
                f'border-radius:8px; padding:0.6rem 0.9rem; margin-bottom:0.75rem;">'
                f'<span style="color:{color}; font-weight:600;">{icon} Graph Quality: {esc(gq["build_status"])}</span> '
                f'&nbsp;·&nbsp; score {gq["quality_score"]:.2f} '
                f'&nbsp;·&nbsp; extraction coverage {gq["extraction_coverage"]:.0%} '
                f'&nbsp;·&nbsp; evidence coverage {gq["evidence_coverage"]:.0%} '
                f'&nbsp;·&nbsp; duplicate rate {gq["duplicate_rate"]:.0%} '
                f'&nbsp;·&nbsp; unresolved-entity rate {gq["unresolved_entity_rate"]:.0%}'
                f'</div>', unsafe_allow_html=True)
            if gq["build_status"] != "CLEAN":
                st.caption("Graph-structural gaps derived from this build have had their confidence "
                           "downgraded accordingly — see each gap's caveat in the Research Gaps tab.")

        gc1,gc2,gc3,gc4 = st.columns(4)
        for col,(lbl,val) in zip([gc1,gc2,gc3,gc4],[
            ("Entities",stats.get("entity_count",0)),
            ("Relations",stats.get("relationship_count",0)),
            ("Communities",stats.get("community_count",0)),
            ("Orphan Signals",stats.get("orphan_count",0)),
        ]):
            with col:
                st.markdown(f'<div class="stat-box" title="{html.escape(glossary_lookup(lbl), quote=True)}"><span class="stat-number" '
                            f'style="font-size:1.5rem;">{esc(val)}</span>'
                            f'<span class="stat-label">{esc(lbl)}</span></div>',
                            unsafe_allow_html=True)
        st.markdown("")

        _render_relations(res, graph)

        # Network diagram
        network_data = graph.get("network_data",{})
        nodes = network_data.get("nodes",[])
        edges = network_data.get("edges",[])
        if nodes:
            try:
                import plotly.graph_objects as go, math, textwrap
                from pipeline.graph_builder import layout_positions, node_color
                n = len(nodes)
                for nd in nodes:                                   # also recolours runs saved with grey nodes
                    nd["color"] = node_color(nd.get("type"))
                if all("x" in nd for nd in nodes):                 # laid out by the pipeline
                    px = [nd["x"] for nd in nodes]; py = [nd["y"] for nd in nodes]
                else:                                              # runs saved before layouts existed
                    pos = layout_positions(n, edges)
                    px = [p[0] for p in pos]; py = [p[1] for p in pos]
                ex, ey, mx, my, mtext = [], [], [], [], []
                for e in edges:
                    si, ti = e["source_idx"], e["target_idx"]
                    if si < n and ti < n:
                        ex += [px[si], px[ti], None]; ey += [py[si], py[ti], None]
                        mx.append((px[si]+px[ti])/2); my.append((py[si]+py[ti])/2)
                        mtext.append(f"{esc(nodes[si]['name'])} → {esc(nodes[ti]['name'])}<br>"
                                     f"<b>{esc(str(e.get('relation','')).replace('_',' '))}</b>"
                                     + (f"<br>{esc(textwrap.shorten(e['evidence'], 140))}" if e.get("evidence") else ""))
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", showlegend=False,
                                         line=dict(width=1.6, color="#9db8d6"), hoverinfo="none"))
                fig.add_trace(go.Scatter(x=mx, y=my, mode="markers", showlegend=False,
                                         marker=dict(size=9, color="rgba(0,0,0,0)"),
                                         hovertext=mtext, hoverinfo="text"))
                for ntype in dict.fromkeys(nd["type"] for nd in nodes):   # one legend entry per type
                    idx = [i for i, nd in enumerate(nodes) if nd["type"] == ntype]
                    fig.add_trace(go.Scatter(
                        x=[px[i] for i in idx], y=[py[i] for i in idx],
                        mode="markers+text", name=str(ntype).replace("_", " "),
                        text=["<br>".join(textwrap.wrap(nodes[i]["name"], 22)) for i in idx],
                        textposition="top center", textfont=dict(size=10, color="#0b1f3a"),
                        marker=dict(size=[nodes[i]["size"] + 4 for i in idx], color=nodes[idx[0]]["color"],
                                    line=dict(width=1, color="#ffffff")),
                        hovertext=[f"<b>{esc(nodes[i]['name'])}</b><br>{esc(ntype)} · {esc(nodes[i]['importance'])} importance"
                                   f"<br>{esc('; '.join(nodes[i].get('papers', []))[:120])}" for i in idx],
                        hoverinfo="text"))
                fig.update_layout(paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                    font=dict(color="#0b1f3a", size=11),
                    xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-1.7, 1.7]),
                    yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-1.6, 1.6]),
                    height=620, margin=dict(l=10, r=10, t=40, b=10),
                    legend=dict(orientation="h", y=-0.02, x=0),
                    title="Knowledge Graph — Entity Network")
                plotly_full_width(fig)
                st.caption("Hover a line to see how two entities are related, and the supporting text.")
            except ImportError:
                show_info("The network diagram needs the plotly package, which is not installed here.")

        for comm in graph.get("communities",[]):
            with st.expander(f"🏘️ {comm.get('theme','Community')}"):
                st.markdown(f'<div class="stage-body">{esc(comm.get("summary",""))}</div>',
                            unsafe_allow_html=True)
                if comm.get("gap_signal"):
                    st.markdown(
                        f'<div style="background:#fff7e6;border:1px solid #f0c36a;border-radius:4px;'
                        f'padding:0.5rem 0.8rem;margin-top:0.5rem;font-size:0.82rem;color:#8a5a00;">'
                        f'⚠️ {esc(comm["gap_signal"])}</div>', unsafe_allow_html=True)

        entities = graph.get("entities",[])
        if entities:
            with st.expander(f"📋 All {len(entities)} entities"):
                import pandas as pd
                table_full_width(pd.DataFrame([{
                    "Name":e.get("name",""),"Type":e.get("type",""),
                    "Importance":e.get("importance",""),
                    "Papers":", ".join(e.get("papers",[]))[:60],
                } for e in entities]), height=260)

        orphans = graph.get("orphan_concepts",[])
        if orphans:
            st.markdown("#### Orphan Concepts")
            for o in orphans[:8]:
                ent = o.get("entity",{})
                st.markdown(
                    f'<div class="stage-card" style="padding:0.6rem 1rem;margin-bottom:0.3rem;">'
                    f'<span style="font-family:\'DM Mono\',monospace;color:#004b93;">{esc(ent.get("name",""))}</span>'
                    f'<span style="font-family:\'DM Mono\',monospace;color:#4a6580;font-size:0.7rem;'
                    f'margin-left:0.6rem;">[{esc(ent.get("type",""))}]</span>'
                    f'<div style="font-size:0.78rem;color:#4a6580;">{esc(o.get("signal",""))}</div></div>',
                    unsafe_allow_html=True)

    # ── Tab 4: Research Gaps ───────────────────────────────────────────────────
    if _tab == "Gaps":
        _render_gaps(res)

    # ── Tab 5: Proposals ───────────────────────────────────────────────────────
    if _tab == "Proposals":
        _render_proposals(res, proposals)

    # ── Tab 6: Computational Lab ───────────────────────────────────────────────
    if _tab == "Lab":
        st.markdown("### 📊 Computational Lab")
        st.markdown(
            '<div style="font-size:0.82rem;color:#4a6580;margin-bottom:1.5rem;">'
            'Parameter extraction (Tier 1 + Tier 2) → Cross-paper discovery → '
            'LLM Council model selection → Multi-algorithm simulation → '
            'Novel findings → Download package.</div>',
            unsafe_allow_html=True)

        cr_col, cn_col, ci_col = st.columns([1.3, 1.5, 2.2], vertical_alignment="center")
        with cr_col:
            run_comp = st.button("Run Computational Lab", key="run_comp")
        with cn_col:
            n_council_runs = st.select_slider(
                "Council runs", options=[1, 2, 3], value=2, key="n_council_runs",
                help="Run the insight council N times and merge the findings. More runs are slower but steadier.")
        with ci_col:
            st.markdown(
                '<div style="font-size:0.78rem;color:#4a6580;padding-top:0.5rem;">'
                f'Stages 7–12 · Uses Tier 1 + Tier 2 params · {n_council_runs}× council runs</div>',
                unsafe_allow_html=True)
        st.caption(f"Results are added to this run (“{st.session_state.current_run_name or 'current run'}”), "
                   "so the run and its Lab output stay together in one report.")

        if run_comp:
            comp_prog = st.progress(0)
            comp_stat = st.empty()
            def cupd(msg, pct):
                comp_prog.progress(pct)
                comp_stat.markdown(_card("Computational Lab", f"⟳ {esc(msg)}"),
                                   unsafe_allow_html=True)
            try:
                # Same per-role models as the main run; the council seats and chair
                # come from the Council rows under "Models for this run". The stages
                # (and the data-sufficiency gate on the simulation) live in pipeline/run_lab.py.
                client = ModelRouter(st.session_state["model_config"], _keys)
                _lab_results = (with_sections(st.session_state.current_run_id, res)
                                if st.session_state.current_run_id else res)    # runs load without section text
                st.session_state.comp_results = run_computational_lab(
                    _lab_results, context, client, domain_config=domain_cfg, n_council_runs=n_council_runs,
                    progress=cupd, trace=_add_trace)
                comp_prog.progress(100)
                # The Lab output belongs to the run it was computed from: attach it
                # there (one analysis = one run), and refresh that run's saved
                # results and report so they include it.
                if st.session_state.results:
                    try:
                        _run_id = st.session_state.current_run_id
                        if not (_run_id and attach_comp_results(_run_id, st.session_state.comp_results)):
                            _run_id = save_run(
                                st.session_state.current_run_name or f"Analysis — {datetime.now().strftime('%H:%M')}",
                                st.session_state.results, st.session_state.comp_results,
                                project_id=st.session_state.current_project_id)
                            st.session_state.current_run_id = _run_id
                            st.session_state.loaded_run_id = _run_id
                        st.session_state.report_bundle = None          # the old report lacks the Lab section
                        try:
                            project_store.refresh_run_results(
                                st.session_state.current_project_id, _run_id,
                                st.session_state.results, context, st.session_state.comp_results)
                        except Exception:
                            pass       # files are a convenience; the database copy is already saved
                    except Exception:
                        show_warning("The Lab finished but could not be saved to the run.")

                comp_prog.empty(); comp_stat.empty()
                _cr = st.session_state.comp_results
                _skip = _cr.get("simulation_skipped")
                st.success(
                    f"✅ Computational Lab saved — {len(_cr['params'])} params "
                    f"(T1:{_cr.get('t1_count', 0)} T2:{_cr.get('t2_count', 0)} derived:{_cr.get('derived_count', 0)}), "
                    + ("simulation skipped (not enough quantitative data), " if _skip else
                       f"{len(_cr['sim_results'].get('models_run', []))} simulations, ")
                    + f"{len(_cr['discovery'].get('hypotheses', []))} hypotheses. "
                    f"Added to this run; generate the final report in the Export tab.")
                if _cr.get("council_error"):
                    show_warning(f"{_cr['council_error']}. Run the Lab again in a few minutes, or choose "
                               "different Council models under “Models for this run”.")

            except Exception as e:
                comp_prog.empty(); comp_stat.empty()
                show_error("The Lab could not finish", exc=e, details=traceback.format_exc())

        # ── Comp results display ───────────────────────────────────────────────
        if st.session_state.comp_results:
            cr = st.session_state.comp_results
            params         = cr["params"]
            sufficiency    = cr["sufficiency"]
            discovery      = cr["discovery"]
            model_council  = cr["model_council"]
            sim_results    = cr["sim_results"]
            insight_council = cr["insight_council"]
            n_runs         = cr.get("n_runs", 1)

            st.markdown("---")

            # The verdict comes first: did the Lab simulate anything, and why (not)?
            _v = lab_verdict(cr)
            _vc = {"simulated": "#087f5b", "skipped": "#8a5a00"}[_v["state"]]
            st.markdown(
                f'<div style="border:1px solid {_vc};background:{_vc}12;border-radius:8px;padding:0.9rem 1.2rem;'
                f'margin-bottom:1rem;"><div style="font-weight:700;color:{_vc};">'
                f'{"Simulated" if _v["state"] == "simulated" else "Not simulated"}</div>'
                f'<div style="color:#0b1f3a;">{html.escape(_v["headline"])}</div></div>', unsafe_allow_html=True)
            for _why in _v["reasons"]:
                st.caption(f"• {_why}")
            if _v["algorithms"]:
                with st.expander("Algorithms: what ran and what was refused", expanded=_v["state"] == "skipped"):
                    for _a in _v["algorithms"]:
                        if _a["state"] == "ran":
                            st.markdown(f"✅ **{_a['name']}**")
                        else:
                            st.markdown(f"⛔ **{_a['name']}** refused: {html.escape(_a['reason'])}")

            # Data availability
            score      = sufficiency.get("coverage_score",0)
            sc         = "#087f5b" if score>=7 else "#8a5a00" if score>=4 else "#c81e1e"
            t1c, t2c   = cr.get("t1_count",0), cr.get("t2_count",0)
            st.markdown(f"""
            <div style="background:#ffffff;border:1px solid {sc};border-radius:8px;
                        padding:1rem 1.2rem;margin-bottom:1.2rem;">
              <div style="font-family:'DM Mono',monospace;font-size:0.65rem;color:{sc};
                          text-transform:uppercase;letter-spacing:0.1em;">Data Availability</div>
              <div style="font-size:1.2rem;color:{sc};font-family:'DM Mono',monospace;">{score}/10</div>
              <div style="font-size:0.85rem;color:#0b1f3a;margin-top:0.3rem;">
                {len(params)} total parameters — {_tier_badge(1)} {t1c} from uploaded PDFs &nbsp;
                {_tier_badge(2)} {t2c} from cited abstracts &nbsp;
                🔀 {cr.get('derived_count',0)} cross-paper derived
              </div>
              <div style="font-size:0.78rem;color:#4a6580;margin-top:0.3rem;">
                {esc(sufficiency.get('why_score_is_low',''))}
              </div>
            </div>""", unsafe_allow_html=True)

            # Per-paper coverage: a paper with no stated numbers (results shown only in figures, or a
            # narrative review) must be visible, not silent.
            _papers = res.get("papers", [])
            if _papers:
                import pandas as pd
                _rows = parameters_by_paper(cr, _papers)
                _table(pd.DataFrame([{"Paper": r["paper"][:48], "Parameters": r["total"], "Measured": r["measured"],
                                      "Opinions": r["opinion"], "Impossible": r["flagged"]} for r in _rows]),
                       hide_index=True)
                _none = [r["paper"] for r in _rows if not r["total"]]
                if _none:
                    st.caption("No parameters were found in " + ", ".join(_none) +
                               ": the paper may report its results in figures or prose rather than as stated numbers.")

            # Parameters grouped
            st.markdown("#### Stage 8 — Extracted Parameters")
            grouped = group_params_by_category(params)
            for cat, cat_params in list(grouped.items())[:10]:
                t1_in_cat = [p for p in cat_params if p.get("tier",1)==1]
                t2_in_cat = [p for p in cat_params if p.get("tier",1)==2]
                label = (f"📊 {cat.replace('_',' ').title()} "
                         f"({len(cat_params)} total: {len(t1_in_cat)} T1 + {len(t2_in_cat)} T2)")
                with st.expander(label):
                    for p in cat_params:
                        ci = (f" (CI: {p['ci_lower']}–{p['ci_upper']})"
                              if p.get("ci_lower") is not None else "")
                        tier_t = p.get("tier",1)
                        derived_t = (" 🔀" if p.get("is_derived") else "") + (
                            f" · <em>{kind_badge(p)}</em>" if kind_badge(p) else "")
                        conf_c = {"high":"#087f5b","medium":"#8a5a00","low":"#c81e1e"}.get(
                            p.get("confidence","medium"),"#4a6580")
                        st.markdown(
                            f'<div class="wiki-item" style="margin-bottom:0.4rem;">'
                            f'{_tier_badge(tier_t)}'
                            f'<span style="color:#004b93;">{esc(p.get("name",""))}</span> = '
                            f'<span style="color:{conf_c};font-family:\'DM Mono\',monospace;">'
                            f'{esc(p.get("value",""))}{ci}</span> {esc(p.get("unit",""))}'
                            f'<span style="color:#4a6580;font-size:0.7rem;"> '
                            f'[{esc(p.get("source_paper","")[:45])}]{derived_t}</span></div>',
                            unsafe_allow_html=True)

            st.download_button("⬇ Download parameters.csv", data=cr["csv_data"],
                               file_name="parameters.csv", mime="text/csv")

            # Discovery
            st.markdown("#### Stage 8B — Novel Hypotheses")
            for h in discovery.get("hypotheses",[]):
                conf  = h.get("confidence","medium")
                cc    = {"high":"#087f5b","medium":"#8a5a00","low":"#c81e1e"}.get(conf,"#4a6580")
                st.markdown(
                    f'<div style="background:#edf6ff;border:1px solid #7ab8f5;'
                    f'border-left:4px solid {cc};border-radius:8px;'
                    f'padding:1.2rem 1.5rem;margin-bottom:1rem;">'
                    f'<div style="font-size:1.05rem;color:#0b1f3a;font-weight:500;">'
                    f'{esc(h.get("hypothesis_id","H?"))}  {esc(h.get("title",""))}</div>'
                    f'<div style="font-size:0.87rem;color:#0b1f3a;margin-top:0.4rem;">'
                    f'{esc(h.get("claim",""))}</div>'
                    f'<div style="margin-top:0.5rem;">'
                    + _badge(f"Novelty {esc(h.get('novelty_score',0))}/10","#004b93","#e5f2ff","#7ab8f5")
                    + _badge(conf.title()+" Conf",cc,"#ffffff",cc)
                    + '</div></div>',
                    unsafe_allow_html=True)
                if h.get("unsupported_numbers"):
                    st.caption("⚠️ Contains figures no paper reports (" + ", ".join(h["unsupported_numbers"])
                               + "): unsupported, confidence lowered.")
                with st.expander(f"Evidence + opportunities for {h.get('hypothesis_id','')}"):
                    hc1,hc2 = st.columns(2)
                    with hc1:
                        _section_label("Mechanism"); _item(esc(h.get("mechanism","")))
                        st.markdown("")
                        _section_label("Validation Study"); _item(esc(h.get("validation_study","")),"#004b93")
                    with hc2:
                        _section_label("Clinical Opportunity"); _item(esc(h.get("clinical_opportunity","")),"#087f5b")
                        st.markdown("")
                        _section_label("Commercial Opportunity"); _item(esc(h.get("commercial_opportunity","")),"#8a5a00")

            # Simulation
            st.markdown(f"#### Stage 10 — Simulation: {sim_results.get('model_used','')}")
            if sim_results.get("skipped"):
                show_info("**Simulation skipped.** The papers do not contain enough usable quantitative parameters "
                        f"({sim_results.get('skip_reason', 'insufficient data')}). Running a model on this would "
                        "produce numbers with no real meaning, so the insights below are qualitative and make no "
                        "numerical prediction.")
            models_run = sim_results.get("models_run",[])
            if models_run:
                st.markdown("Algorithms run: " +
                            " ".join(_badge(m) for m in models_run),
                            unsafe_allow_html=True)

            sens = sim_results.get("sensitivity_ranking",[])
            if sens:
                st.markdown("**Top sensitivity drivers (% deviation from central value):**")
                for i,s in enumerate(sens[:6],1):
                    bar = int(min(s.get("importance",0),1.0)*100)
                    swing = s.get("swing_pct", "")
                    label_extra = f" — {swing}% range" if swing else ""
                    st.markdown(
                        f'<div style="margin-bottom:0.5rem;">'
                        f'<div style="font-family:\'DM Mono\',monospace;font-size:0.75rem;color:#0b1f3a;">'
                        f'{i}. {esc(s["parameter"])}{label_extra}</div>'
                        f'<div style="background:#c9dff5;border-radius:3px;height:6px;margin-top:2px;">'
                        f'<div style="background:#0066cc;width:{bar}%;height:6px;border-radius:3px;"></div>'
                        f'</div></div>', unsafe_allow_html=True)

            if cr.get("council_error"):
                show_warning(f"{cr['council_error']}. The insight sections below are empty for that reason; "
                           "run the Lab again in a few minutes, or choose different Council models.")
            # Council insights (multi-run merged)
            st.markdown(f"#### Stage 11 — Council Findings ({n_runs}× runs merged)")
            ic = insight_council
            cov = ic.get("coverage_stats",{})
            st.markdown(f"""
            <div style="background:#edf6ff;border:1px solid #7ab8f5;border-radius:8px;
                        padding:0.9rem 1.2rem;margin-bottom:1.2rem;">
              <div style="font-family:'DM Mono',monospace;font-size:0.65rem;color:#0066cc;
                          text-transform:uppercase;letter-spacing:0.1em;">Multi-Run Coverage</div>
              <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.8rem;margin-top:0.5rem;">
                <div style="text-align:center;">
                  <div style="font-size:1.4rem;color:#087f5b;font-family:'DM Mono',monospace;">
                    {cov.get('total_novel_findings',0)}</div>
                  <div style="font-size:0.68rem;color:#4a6580;text-transform:uppercase;">Novel Findings</div>
                </div>
                <div style="text-align:center;">
                  <div style="font-size:1.4rem;color:#004b93;font-family:'DM Mono',monospace;">
                    {cov.get('total_clinical_insights',0)}</div>
                  <div style="font-size:0.68rem;color:#4a6580;text-transform:uppercase;">Clinical Insights</div>
                </div>
                <div style="text-align:center;">
                  <div style="font-size:1.4rem;color:#8a5a00;font-family:'DM Mono',monospace;">
                    {cov.get('total_next_steps',0)}</div>
                  <div style="font-size:0.68rem;color:#4a6580;text-transform:uppercase;">Next Steps</div>
                </div>
              </div>
            </div>""", unsafe_allow_html=True)

            # Novel findings
            for g in ic.get("novel_finding_groups",[]):
                nf   = g["best"]
                cc   = g["confidence_color"]
                freq = g["frequency"]
                st.markdown(
                    f'<div style="background:#0a1f0a;border:2px solid {cc};border-radius:10px;'
                    f'padding:1.2rem 1.5rem;margin-bottom:1rem;">'
                    f'<div style="display:flex;justify-content:space-between;">'
                    f'<div style="font-family:\'DM Mono\',monospace;font-size:0.62rem;color:{cc};">🔬 NOVEL FINDING</div>'
                    f'<div>{_badge(esc(g["confidence"]),cc,"#ffffff",cc)}'
                    f'{_badge(freq,"#4a6580","#f2f5f8","#c9dff5")}</div></div>'
                    f'<div style="font-size:1.05rem;color:#0b1f3a;font-weight:600;margin:0.5rem 0 0.4rem;">'
                    f'{esc(nf.get("title",""))}</div>'
                    f'<div style="font-size:0.88rem;color:#0b1f3a;line-height:1.7;">{esc(nf.get("claim",""))}</div>'
                    f'<div style="font-size:0.75rem;color:#4a6580;margin-top:0.4rem;font-style:italic;">'
                    f'What\'s new: {esc(nf.get("what_makes_it_new",""))}</div></div>',
                    unsafe_allow_html=True)
                if nf.get("unsupported_numbers"):
                    st.caption("⚠️ This finding states figures no paper reports ("
                               + ", ".join(nf["unsupported_numbers"]) + "). Treat them as unsupported guesses; "
                               "the finding is a hypothesis to test, not a result.")

            # Insights grid
            def _show_groups(groups, icon):
                for g in groups:
                    cc = g["confidence_color"]
                    st.markdown(
                        f'<div style="background:#ffffff;border:1px solid #c9dff5;'
                        f'border-left:3px solid {cc};border-radius:5px;'
                        f'padding:0.6rem 0.9rem;margin-bottom:0.35rem;">'
                        f'<div style="display:flex;justify-content:space-between;">'
                        f'<div style="font-size:0.85rem;color:#0b1f3a;">{icon} {esc(g["representative"])}</div>'
                        f'<div>{_badge(esc(g["confidence"]),cc,"#ffffff",cc)}'
                        f'{_badge(g["frequency"],"#4a6580","#f2f5f8","#c9dff5")}</div></div></div>',
                        unsafe_allow_html=True)

            ic1,ic2 = st.columns(2)
            with ic1:
                if ic.get("clinical_insight_groups"):
                    st.markdown("##### Clinical Insights")
                    _show_groups(ic["clinical_insight_groups"],"🏥")
                if ic.get("next_step_groups"):
                    st.markdown("##### Next Steps")
                    _show_groups(ic["next_step_groups"],"→")
            with ic2:
                if ic.get("research_insight_groups"):
                    st.markdown("##### Research Insights")
                    _show_groups(ic["research_insight_groups"],"🔬")
                if ic.get("limitation_groups"):
                    st.markdown("##### Limitations")
                    _show_groups(ic["limitation_groups"],"⚠️")

            # Download
            st.markdown("---")
            st.markdown("#### Stage 12 — Download Report Package")
            st.markdown(
                '<div class="stage-card"><div class="stage-title">Contents</div>'
                '<div class="stage-body">📄 parameters.csv · 📊 simulation_results.json · '
                '🏛️ council_debate.md · 💡 insights.md · 📋 full_report.md · 🔬 novel_hypotheses.json'
                '</div></div>', unsafe_allow_html=True)
            st.download_button("⬇ Download ZIP",
                               data=cr["zip_bytes"],
                               file_name="computational_lab_output.zip",
                               mime="application/zip")

    # ── Tab 7: Pipeline Trace ──────────────────────────────────────────────────
    if _tab == "Trace":
        st.markdown("### 🔎 Pipeline Trace — Explainability View")
        trace = saved_trace(res, st.session_state.pipeline_trace)
        _ts = trace_summary(res, get_run_manifest(st.session_state.current_run_id)
                            if st.session_state.current_run_id else None)
        if _ts.get("models"):
            st.markdown("**Models used:** " + " · ".join(f"{html.escape(str(r))}: {html.escape(str(m))}"
                                                         for r, m in _ts["models"].items()))
        if _ts.get("fallback_count"):
            show_warning(f"{_ts['fallback_count']} call(s) used the fallback model: " + "; ".join(_ts["fallbacks"][:5]))
        if _ts.get("tokens_total"):
            st.caption(f"Tokens used: {_ts['tokens_total']:,} in total · "
                       + " · ".join(f"{k}: {v:,}" for k, v in _ts["tokens_by_stage"].items()))
        if not trace:
            show_info("This run has no stage trace stored (it was saved before traces were kept). "
                    "Run a new analysis to get one.")
        else:
            for entry in trace_rows(trace):
                i = entry["n"]
                st.markdown(
                    f'<div style="background:#ffffff;border:1px solid #c9dff5;'
                    f'border-left:3px solid #0066cc;border-radius:6px;'
                    f'padding:0.8rem 1.2rem;margin-bottom:0.5rem;">'
                    f'<div style="font-family:\'DM Mono\',monospace;font-size:0.7rem;color:#0066cc;">'
                    f'{esc(entry.get("status","✅"))} STAGE {i} — {esc(entry["stage"])}</div>'
                    f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:0.5rem;">'
                    f'<div><span style="font-family:\'DM Mono\',monospace;font-size:0.62rem;color:#4a6580;">IN: </span>'
                    f'<span style="font-size:0.8rem;color:#0b1f3a;">{esc(entry["inputs"])}</span></div>'
                    f'<div><span style="font-family:\'DM Mono\',monospace;font-size:0.62rem;color:#4a6580;">OUT: </span>'
                    f'<span style="font-size:0.8rem;color:#087f5b;">{esc(entry["outputs"])}</span></div>'
                    f'</div></div>',
                    unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("#### Active prompts")
        from pipeline.wiki_compiler import WIKI_SYSTEM_PROMPT
        from pipeline.gap_agents import _CRITIC_PROMPT, _FINDER_PROMPTS
        with st.expander("Wiki compiler prompt"):
            st.code(WIKI_SYSTEM_PROMPT, language=None)
        for _lens, _prompt in _FINDER_PROMPTS.items():
            with st.expander(f"Gap finder prompt: {_lens}"):
                st.code(_prompt, language=None)
        with st.expander("Gap critic prompt"):
            st.code(_CRITIC_PROMPT, language=None)

    # ── Tab 8: Export ──────────────────────────────────────────────────────────
    if _tab == "Export":
        st.markdown("### Export Results")
        st.markdown(
            '<div class="stage-card"><div class="stage-title">Polished Final Report</div>'
            '<div class="stage-body">One report for this run: cover page, executive summary, corpus overview, references, graph, gaps, validation, proposals, '
            'the Computational Lab results (when the Lab has been run), risks, and appendices.</div></div>',
            unsafe_allow_html=True)
        _lab_in_report = bool(st.session_state.comp_results)
        st.caption("Includes the Computational Lab results." if _lab_in_report else
                   "The Computational Lab has not been run for this run, so the report will not have a Lab section. "
                   "Run it in the Computational Lab tab first if you want it included.")
        _section_titles = dict(REPORT_SECTIONS)
        report_sections = st.multiselect(
            "Sections to include", ALL_SECTION_IDS,
            default=[sid for sid in ALL_SECTION_IDS if sid != "lab" or _lab_in_report],
            format_func=_section_titles.get, key="report_sections",
            help="Untick what you do not want in the report. The cover page is always included.")
        gen_col, mode_col = st.columns([1, 2])
        with gen_col:
            generate_report = st.button("Generate final report", key="generate_final_report",
                                        disabled=not report_sections)
        with mode_col:
            use_llm_report = st.checkbox("Use a model-written summary", value=True,
                                         help="Uses the Analysis model to write a concise report narrative from existing structured results only.")

        if generate_report:
            try:
                _report_spec = st.session_state["model_config"].spec_for(ROLE_ANALYSIS)
                report_client = (
                    ModelRouter(st.session_state["model_config"], _keys)
                    if (use_llm_report and _keys.get(_report_spec.provider)) else None
                )
                _comp = st.session_state.comp_results
                narrative = generate_report_narrative(res, context, client=report_client)
                html_report = to_enterprise_html_report(res, context, narrative=narrative, comp_results=_comp,
                                                        sections=report_sections)
                pdf_report = to_enterprise_pdf_report(res, context, narrative=narrative, comp_results=_comp,
                                                      sections=report_sections)
                st.session_state.report_bundle = {
                    "html": html_report,
                    "pdf": pdf_report,
                    "run_id": st.session_state.current_run_id,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "used_llm": bool(report_client),
                    "with_lab": bool(_comp) and "lab" in report_sections,
                    "sections": list(report_sections),
                    "saved": False,
                }
                st.success("Final report generated.")
            except Exception as e:
                show_error("The report could not be generated", exc=e, details=traceback.format_exc())

        bundle = st.session_state.report_bundle
        if bundle and bundle.get("run_id") == st.session_state.current_run_id:
            show_info(f"Report ready. Generated at {bundle.get('generated_at','')} · "
                    f"Model-written summary: {'yes' if bundle.get('used_llm') else 'no'} · "
                    f"Lab section: {'yes' if bundle.get('with_lab') else 'no'}")
            sv_col, dl1, dl2 = st.columns(3)
            with sv_col:
                if st.button("Save to project", key="save_final_report", type="primary",
                             disabled=not st.session_state.current_run_id,
                             help="Stores this report in the project folder and database, replacing the automatic one for this run."):
                    try:
                        project_store.save_report(st.session_state.current_project_id,
                                                  st.session_state.current_run_id,
                                                  bundle["html"], bundle["pdf"])
                        bundle["saved"] = True
                    except Exception as e:
                        show_error("Could not save the report", exc=e)
            with dl1:
                st.download_button("Download HTML Report",
                                   data=bundle["html"].encode("utf-8"),
                                   file_name="research_gap_final_report.html",
                                   mime="text/html")
            with dl2:
                st.download_button("Download PDF Report",
                                   data=bundle["pdf"],
                                   file_name="research_gap_final_report.pdf",
                                   mime="application/pdf")
            if bundle.get("saved"):
                st.success("Saved to the project. Find it any time under Project view → Files.")
            with st.expander("Preview the report", expanded=False):
                st.caption("Exactly what the HTML download and the saved report contain.")
                import streamlit.components.v1 as _components
                _components.html(bundle["html"], height=720, scrolling=True)

        st.markdown("---")
        ex1,ex2,ex3 = st.columns(3)
        with ex1:
            st.markdown('<div class="stage-card"><div class="stage-title">PDF Report</div>'
                        '<div class="stage-body">Legacy quick PDF summary.</div></div>',
                        unsafe_allow_html=True)
            try:
                st.download_button("Download Quick PDF",
                                   data=to_pdf_report(res, context),
                                   file_name="research_gap_report.pdf", mime="application/pdf")
            except Exception as e:
                show_error("PDF report generation failed", exc=e)
        with ex2:
            st.markdown('<div class="stage-card"><div class="stage-title">Markdown Report</div>'
                        '<div class="stage-body">Full analysis — wiki, gaps, proposals.</div></div>',
                        unsafe_allow_html=True)
            st.download_button("Download Markdown",
                               data=to_markdown_report(res, context),
                               file_name="research_gap_report.md", mime="text/markdown")
        with ex3:
            st.markdown('<div class="stage-card"><div class="stage-title">JSON Export</div>'
                        '<div class="stage-body">Complete structured data.</div></div>',
                        unsafe_allow_html=True)
            st.download_button("Download JSON",
                               data=to_json(res),
                               file_name="research_gap_analysis.json",
                               mime="application/json")
        with st.expander("Raw JSON"):
            st.json(res)
