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
    initial_sidebar_state="expanded",
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
from utils import project_store
from pipeline.feedback_context import POSITIVE_REASONS, NEGATIVE_REASONS
from pipeline.pdf_parser import parse_pdf
from pipeline.page_index import build_tree, tree_to_summary
from pipeline.wiki_compiler import build_wiki
from pipeline.graph_builder import build_knowledge_graph
from pipeline.gap_detector import detect_gaps
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
from pipeline.relevance_ranking import EMBEDDING_MODEL, RERANK_MODEL
from pipeline.academic_search import validate_gaps
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
from ui.components import (badge as _badge, tier_badge as _tier_badge, card as _card,
                           section_label as _section_label, item as _item, skeleton as _skeleton)


def _load_run_into_session(run_id: str, run_name: str) -> bool:
    """Make a saved run the one on screen. Returns False if it has no results
    (nothing is changed in that case)."""
    loaded = load_run(run_id)
    if not loaded.get("results"):
        return False
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
            st.error(str(e))
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
    options = [*PROVIDER_REGISTRY, CUSTOM_PROVIDER]
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
    c_role.markdown(f'<span title="{html.escape(tip)}" style="font-weight:600;font-size:0.9rem;">{label}</span>',
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
                            f'— {r["latency_s"]} s{json_note} <span style="color:#55708f;">({html.escape(roles)})</span>',
                            unsafe_allow_html=True)
            else:
                st.markdown(f'<span style="color:#c81e1e;font-weight:700;">✗</span> {html.escape(r["label"])} '
                            f'<span style="color:#55708f;">({html.escape(roles)})</span><br>'
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


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f'<div class="sb-brand">{html.escape(_BRANDING["product_name"])}</div>', unsafe_allow_html=True)

    # ── Project: every analysis, its papers and files, and feedback belong to one ──
    st.markdown("##### Project")
    _projects = list_projects()
    _project_ids = [p["id"] for p in _projects]
    _project_by_id = {p["id"]: p for p in _projects}
    if "_pending_project" in st.session_state:   # set by the New project dialog; the picker
        st.session_state["project_select"] = st.session_state.pop("_pending_project")   # can't be set after it exists
    if st.session_state.get("project_select") not in _project_ids:
        st.session_state["project_select"] = DEFAULT_PROJECT_ID
    st.session_state.current_project_id = st.session_state["project_select"]
    st.selectbox(
        "Project", _project_ids, key="project_select", on_change=_on_project_change,
        format_func=lambda pid: f"{_project_by_id[pid]['name']} ({_project_by_id[pid]['run_count']})",
        label_visibility="collapsed")
    if st.button("New project", key="new_project_btn"):
        _new_project_dialog()

    # Containers fix the on-screen ORDER (setup first, model last) while the
    # code below fills the model one first: the analysis options depend on the
    # selected provider (e.g. whether it supports image input).
    setup_c = st.container()
    options_c = st.container()
    model_c = st.container()

    # ── API keys & endpoints (set once; WHICH model does what is chosen next to Run) ──
    with model_c:
        with st.expander("API keys & endpoints"):
            st.caption("Keys stay in this session and are never written to disk. "
                       "Leave a field blank to use the environment variable named in its help.")
            _typed_keys = {}
            for _pk, _pcfg in PROVIDER_REGISTRY.items():
                _typed_keys[_pk] = st.text_input(
                    f"{_pcfg.label.split(' (')[0]} API key", type="password", placeholder="Paste key",
                    key=f"key_{_pk}", help=f"Leave blank to use {_pcfg.api_key_env}.")
            st.markdown("**Custom endpoint** — any OpenAI-compatible API")
            _typed_custom_base = st.text_input(
                "Base URL", key="custom_base_url", placeholder="https://api.example.com/v1",
                value=os.environ.get("CUSTOM_LLM_BASE_URL", ""),
                help="Anything that speaks the OpenAI chat format. Choose \"Custom endpoint\" as a provider below.")
            _typed_custom_key = st.text_input(
                "Custom endpoint API key", type="password", placeholder="Paste key", key="key_custom",
                help="Leave blank to use CUSTOM_LLM_API_KEY.")
            ss_api_key = st.text_input(
                "Semantic Scholar API key (optional)", type="password", placeholder="Paste key",
                help="Leave blank to use SEMANTIC_SCHOLAR_API_KEY from the environment; with neither, the free, "
                     "rate-limited tier is used. Get a key at semanticscholar.org/product/api.")
            # Like every other key, the environment is a valid source (it was ignored here, so
            # runs used the slow free tier even with a key in .env).
            ss_api_key = (ss_api_key or "").strip() or os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
            if ss_api_key:
                st.caption("Semantic Scholar key in use.")

        # An env var is a valid source for every key, so a deployed app can ship its
        # keys as secrets while users may still paste their own.
        _keys = {pk: (_typed_keys[pk] or os.environ.get(pcfg.api_key_env, "")).strip()
                 for pk, pcfg in PROVIDER_REGISTRY.items()}
        _custom_base = (_typed_custom_base or "").strip()
        _keys[CUSTOM_PROVIDER] = (_typed_custom_key or os.environ.get("CUSTOM_LLM_API_KEY", "")).strip()
        _available = {pk for pk in PROVIDER_REGISTRY if _keys[pk]}
        if _keys[CUSTOM_PROVIDER] and _custom_base:
            _available.add(CUSTOM_PROVIDER)
        st.session_state["_available_providers"] = _available
        st.session_state["_custom_base_url"] = _custom_base
        api_key = _keys["nvidia"]          # also used for relevance ranking in Deep gap validation
        if "model_config" not in st.session_state:
            st.session_state["model_config"] = load_config(_available)
        _found = [_provider_name(p) for p in (*PROVIDER_REGISTRY, CUSTOM_PROVIDER) if p in _available]
        st.caption(keys_line(_found, bool(ss_api_key)))

    # ── Research setup (used on every run -> always visible) ─────────────────
    with setup_c:
        st.markdown("##### Research setup")
        _domain_choices = dict(get_ui_domain_choices())          # label -> domain key
        _domain_label = st.selectbox("Domain", list(_domain_choices), index=0)
        selected_domain = _domain_choices[_domain_label]
        domain_cfg   = get_domain_config(selected_domain)
        st.caption(domain_cfg["description"])
        interest = st.text_area("Research interest",
                                 placeholder=f"e.g., {domain_cfg.get('gap_examples','')[:80]}...",
                                 height=80)
        gap_type = st.selectbox("Gap type", ["Any", "Methodology", "Application", "Dataset",
                                             "Evaluation", "Theory", "Benchmark"])

    # ── Analysis options ──────────────────────────────────────────────────────
    with options_c:
        st.markdown("##### Analysis")
        extract_refs = st.checkbox(
            "Include cited references", value=False,
            help="Looks up each paper's cited references on Semantic Scholar to widen the corpus. "
                 "Slow: about 3-5 seconds per reference (more when Semantic Scholar throttles), "
                 "so 50 references per paper adds roughly 5-10 minutes per paper. "
                 "An optional Semantic Scholar API key (Model & API keys) speeds this up.")
        ref_limit = st.selectbox(
            "References per paper", ["25", "50", "100", "All"], index=1,
            disabled=not extract_refs,
            help="Higher limits take longer but improve reference coverage.")

        with st.expander("Advanced options"):
            enable_quality_engine = st.checkbox(
                "Quality check", value=False,
                help="Cross-checks each paper with a second parser and resolves cited references "
                     "before gap analysis. The run is blocked if extraction quality is too low. "
                     "Adds a few seconds per new paper (cached afterwards).")
            override_quality_gate = False
            if enable_quality_engine:
                override_quality_gate = st.checkbox(
                    "Continue even if the quality check fails", value=False,
                    help="A failed check blocks the run by default. Tick this to proceed anyway; "
                         "the quality warning is still recorded in the results.")

            enable_gap_challenger = st.checkbox(
                "Deep gap validation", value=False,
                help="Adds an extra literature search and a six-level status "
                     "(open, partially open, contested, likely closed, closed, insufficient evidence) "
                     "for each gap, based on how thoroughly the literature was searched. "
                     "Slower: roughly 30 seconds per gap.")
            if enable_gap_challenger and not api_key:
                st.caption("No NVIDIA key found: candidate papers will not be relevance-ranked.")

            _mc = st.session_state["model_config"]
            if any(can_read_images(s) for s in (_mc.spec_for(ROLE_EXTRACTION), _mc.spec_for(ROLE_ANALYSIS), _mc.fallback) if s):
                use_vision = st.checkbox(
                    "Analyze figures and tables", value=False,
                    help="Sends up to 5 figure-heavy pages per paper to a vision model. "
                         "Slower and uses more tokens.")
            else:
                use_vision = False
                st.caption("Figure analysis needs a model that can read images (for example Gemini or NVIDIA "
                           "as extraction, analysis or fallback model).")

    st.markdown("---")

    # ── Recent runs (this project) ─────────────────────────────────────────────
    st.markdown("##### Recent runs")
    runs = list_runs(limit=5, project_id=st.session_state.current_project_id)
    if not runs:
        st.caption("No saved runs in this project yet.")
    else:
        for run in runs:
            ts_short = run["created_at"][:16].replace("T", " ")
            on_screen = "● " if run["id"] == st.session_state.current_run_id else ""
            if st.button(
                f"{on_screen}{run['name'][:30]}",
                key=f"load_{run['id']}",
                help=f"{ts_short} · {run['domain']} · {run['n_papers']} papers · {run['n_gaps']} gaps",
            ):
                if _load_run_into_session(run["id"], run["name"]):
                    st.rerun()

            st.markdown(
                f'<div style="font-size:0.72rem;color:#55708f;'
                f'margin-top:-0.5rem;margin-bottom:0.4rem;padding-left:0.2rem;">'
                f'{ts_short} · {run["n_papers"]} papers · {run["n_gaps"]} gaps'
                f'{" · Lab ✓" if run["has_comp"] else ""}</div>',
                unsafe_allow_html=True,
            )
        st.caption("All runs, comparison, files and feedback: Project view.")

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
    f'<div class="hero-point">{_CHECK}<div><b>{t}</b><span>{d}</span></div></div>' for t, d in _hero_points)
_flow_html = "".join(
    f'<div class="flow-step"><div class="flow-dot">{i}</div><div class="flow-label">{s}</div></div>'
    for i, s in enumerate(_hero_steps, 1))
# The hero is for first-time visitors: once the project has a run, results come first.
_show_hero = not (st.session_state.results or list_runs(limit=1, project_id=st.session_state.current_project_id))
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

def _render_run_comparison(id_a: str, id_b: str) -> None:
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
        st.markdown(f"**Papers:** {p['common_count']} common · "
                    f"{len(p['added'])} added · {len(p['removed'])} removed")
        e = cmp["evidence"]
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
            _section_label(f"New gaps in the newer run ({id_b[:8]})")
            for t in gp["added"][:15]:
                _item(f"🆕 {t}")
        if gp["removed"]:
            st.markdown("")
            _section_label(f"Gaps no longer generated (in the older run, {id_a[:8]}, only)")
            for t in gp["removed"][:15]:
                _item(f"➖ {t}")
        if gp["confidence_changes"]:
            st.markdown("")
            _section_label("Confidence changes")
            for c in gp["confidence_changes"][:15]:
                _item(f"🔀 {c['title']}: {c['confidence_a']} → {c['confidence_b']}")
    except ValueError as e:
        st.error(str(e))


def _render_repeatability(selected_ids: list[str]) -> None:
    """How stable the gap output was across repeated analyses of the same
    corpus/context (pipeline/repeatability_score.py). Unrelated runs just give
    a low, honestly-meaningless score, not an error."""
    gap_sets = [load_run(rid).get("results", {}).get("gaps", []) for rid in selected_ids]
    try:
        report = compute_repeatability_score(gap_sets, run_ids=selected_ids)
        st.markdown(
            f"**Gap overlap:** {report['gap_overlap_mean']} · "
            f"**Claim stability:** {report['claim_stability_mean']} · "
            f"**Ranking correlation:** {report['ranking_correlation_mean']} · "
            f"**Confidence drift:** {report['confidence_drift_mean']}"
        )
        if report.get("duplicate_run_note"):
            st.warning(
                f"⚠️ {report['n_duplicate_pairs_excluded']} pair(s) excluded from the "
                f"averages above -- {report['duplicate_run_note']}"
            )
        st.caption(report["ranking_proxy_note"])
        st.markdown("")
        _section_label("Per-Pair Detail")
        for p in report["pairs"]:
            dup = " ⚠️ likely duplicate (excluded above)" if p["likely_duplicate_run"] else ""
            st.markdown(
                f"`{p['run_a'][:8]}` vs `{p['run_b'][:8]}`{dup} — "
                f"overlap {p['gap_overlap']}, stability {p['claim_stability']}, "
                f"ranking corr {p['ranking_correlation']}, drift {p['confidence_drift']} "
                f"({p['n_common_gaps']} common gaps)"
            )
    except ValueError as e:
        st.error(str(e))


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
                _item(f"🔗 {e['parent']} → {e['child']} ({child.get('artifact_type','?')})")
            if tech["fan_in_edges"]:
                st.caption(f"{len(tech['fan_in_edges'])} fan-in edge(s) (e.g. N papers → 1 evidence set)")
            if tech["orphans"]:
                st.warning(f"⚠️ {len(tech['orphans'])} artifact(s) with an unresolved parent.")

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
                f"🧩 {g['title']} [{g['source']}/{g['evidence_basis']}] — "
                f"{len(c['evidence'])} evidence · {len(c['relationships'])} relationships · "
                f"{len(c['proposals'])} proposal(s)"
                + (f" · ⚠️ {n_unresolved} unresolved id(s)" if n_unresolved else "")
            )
    except ValueError as e:
        st.error(str(e))


def _render_graph_history(project_run_ids: set) -> None:
    """Knowledge graphs saved for this project's runs, and a diff of any two."""
    ok, msg = graph_store_connect_ok()
    if not ok:
        st.caption(f"Not connected -- {msg}")
        return
    try:
        graph_runs = [g for g in list_graph_snapshots() if g["run_id"] in project_run_ids]
    except Exception as e:
        st.error(f"Could not list saved graphs: {e}")
        return
    if not graph_runs:
        st.caption("No saved graphs for this project yet. Run an analysis first.")
        return
    graph_options = {
        f"{g['name'][:30]} ({g['run_id'][:8]}, {g['entity_count']}e/{g['relationship_count']}r"
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
                f"{len(diff['entities_only_in_a'])} only in `{id_a[:8]}` · "
                f"{len(diff['entities_only_in_b'])} only in `{id_b[:8]}`"
            )
            st.markdown(
                f"**Relationships:** {len(diff['relationships_common'])} common · "
                f"{len(diff['relationships_only_in_a'])} only in `{id_a[:8]}` · "
                f"{len(diff['relationships_only_in_b'])} only in `{id_b[:8]}`"
            )
            for key, rid in (("entities_only_in_a", id_a), ("entities_only_in_b", id_b)):
                if diff[key]:
                    st.markdown("")
                    _section_label(f"Entities only in {rid[:8]}")
                    for name_ in diff[key][:15]:
                        _item(f"🔹 {name_}")
        except Exception as e:
            st.error(f"Diff failed: {e}")


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
    st.caption(f"Folder: `{project_store.project_path(pid)}`")

    # ── Runs ─────────────────────────────────────────────────────────────────
    st.markdown("#### Runs")
    selected: list[dict] = []
    if not runs:
        st.info("No analyses in this project yet. Switch to **Analysis**, add papers and run one. "
                "Run it again with different settings to compare the results here.")
    else:
        fb_rows = list_feedback(project_id=pid)
        fb_by_run = Counter(f["run_id"] for f in fb_rows)
        df = pd.DataFrame([{
            "Run": r["name"], "Created": r["created_at"][:16].replace("T", " "),
            "Papers": r["n_papers"], "Gaps": r["n_gaps"], "Proposals": r["n_proposals"],
            "Feedback": fb_by_run.get(r["id"], 0), "ID": r["id"][:8],
        } for r in runs])
        st.caption("Select one run to open or download it, two to compare them, "
                   "two or more to check how repeatable the results are.")
        event = _table(df, hide_index=True, on_select="rerun",
                             selection_mode="multi-row", key=f"project_runs_{pid}")
        selected = [runs[i] for i in event.selection.rows if i < len(runs)]

    if len(selected) == 1:
        run = selected[0]
        st.markdown(f"**{html.escape(run['name'])}** · {run['created_at'][:16].replace('T', ' ')}")
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
        _render_run_comparison(older["id"], newer["id"])
    elif len(selected) > 2:
        st.caption(f"{len(selected)} runs selected. Select exactly two to compare them directly.")
    if len(selected) >= 2:
        with st.expander("Repeatability across the selected runs"):
            if st.button("Compute repeatability score", key="compute_repeatability"):
                _render_repeatability([r["id"] for r in selected])
    if selected:
        with st.expander("Delete selected runs"):
            st.caption("Removes the runs and their feedback from the database. "
                       "Files already saved in the project folder are kept.")
            if (st.checkbox("I understand this cannot be undone", key="confirm_delete_runs")
                    and st.button(f"Delete {len(selected)} run(s)", key="delete_runs_btn")):
                for r in selected:
                    delete_run(r["id"])
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


# ── Project strip and view switch ────────────────────────────────────────────
_cur_project = get_project(st.session_state.current_project_id) or get_project(DEFAULT_PROJECT_ID)
_cur_project_stats = _project_by_id.get(_cur_project["id"], {})
_proj_runs = list_runs(limit=1000, project_id=_cur_project["id"])
st.markdown(
    '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:0.3rem 1rem;'
    'font-family:Inter,Segoe UI,system-ui,sans-serif;margin:0 0 0.5rem;">'
    '<span style="font-size:0.72rem;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;'
    'color:#55708f;">Project</span>'
    f'<span style="font-size:1rem;font-weight:600;color:#0b1f3a;">{html.escape(_cur_project["name"])}</span>'
    f'<span style="font-size:0.82rem;color:#55708f;">{len(_proj_runs)} run(s) · '
    f'{_cur_project_stats.get("paper_count", 0)} paper(s) saved</span>'
    '</div>', unsafe_allow_html=True)
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
                      get_run_manifest(st.session_state.current_run_id))
    _rm_name, _rm_when, _rm_stats = _hdr["name"], _hdr["when"], _hdr["stats"]
    _chips = "".join(
        f'<span style="font-size:0.72rem;color:#004b93;background:#e5f2ff;border:1px solid #7ab8f5;'
        f'border-radius:10px;padding:0.1rem 0.5rem;">{c}</span>' for c in _hdr["chips"])
    st.markdown(
        '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:0.4rem 1rem;'
        'background:#edf6ff;border:1px solid #c9dff5;border-left:3px solid #0066cc;'
        'border-radius:8px;padding:0.65rem 1.1rem;margin-bottom:0.9rem;'
        'font-family:Inter,Segoe UI,system-ui,sans-serif;">'
        '<span style="font-size:0.72rem;font-weight:600;letter-spacing:0.08em;'
        'text-transform:uppercase;color:#004b93;">Run</span>'
        f'<span style="font-size:0.9rem;font-weight:600;color:#0b1f3a;">{_rm_name}</span>'
        f'<span style="font-size:0.82rem;color:#55708f;">{_rm_when}{_rm_stats}</span>'
        f'<span style="display:flex;gap:0.4rem;margin-left:auto;">{_chips}</span>'
        '</div>',
        unsafe_allow_html=True)

# With a run on screen the form folds away so the results are the first thing seen.
_has_run_on_screen = bool(st.session_state.results)
with st.expander("New analysis", expanded=not _has_run_on_screen):
    st.markdown('<div class="section-label">New analysis</div>'
                '<div class="section-hint">Add 2&ndash;5 PDFs (up to 200 MB each). '
                'Gap detection compares papers against each other, so at least two are needed.</div>',
                unsafe_allow_html=True)
    uploaded_files = st.file_uploader(
        "Research papers (PDF)", type=["pdf"], accept_multiple_files=True,
        label_visibility="collapsed",
    )

    # Papers this project already holds can be analysed again (new model, new question)
    # without uploading them a second time.
    _stored = project_store.list_papers(_cur_project["id"])
    _chosen_ids = []
    if _stored:
        st.markdown('<div class="section-hint" style="margin-top:0.6rem;">Or use papers already in this project:</div>',
                    unsafe_allow_html=True)
        for _p in _stored:
            if st.checkbox(f"{_p['filename']} · {_p['kb']} KB", key=f"use_paper_{_cur_project['id']}_{_p['id']}"):
                _chosen_ids.append(_p["id"])
    try:
        _stored_papers = project_store.read_papers(_cur_project["id"], _chosen_ids)
    except (OSError, ValueError) as e:
        st.warning(f"A stored paper could not be read: {e}")
        _stored_papers = []
    _papers, _paper_notices = project_store.combine_papers(
        [(f.name, f.getvalue()) for f in (uploaded_files or [])], _stored_papers)
    for _n in _paper_notices:
        st.warning(_n)

    if _papers:
        cols = st.columns(min(len(_papers), 5))
        for i, (col, (_pname, _pdata)) in enumerate(zip(cols, _papers)):
            with col:
                st.markdown(
                    f'<div class="stage-card" style="text-align:center;padding:0.8rem;">'
                    f'<div class="stage-title">{_tier_badge(1)} Paper {i+1}</div>'
                    f'<div class="stage-body" style="font-size:0.78rem;word-break:break-word;">{html.escape(_pname)}</div>'
                    f'<div style="font-size:0.7rem;color:#55708f;">'
                    f'{len(_pdata)//1024} KB</div></div>',
                    unsafe_allow_html=True)

    run_name = st.text_input(
        "Run name (optional)", value="", placeholder="e.g., Diabetes AI review",
        help="Used to find this analysis later in Run History. Leave blank to name it automatically.")

    st.markdown("---")
    _model_issues = _render_model_picker()      # which model does which job, and a test, in the same step as Run

    _n_files = len(_papers)
    run_col, status_col = st.columns([1, 5], vertical_alignment="center")
    with run_col:
        run_btn = st.button("Run analysis", type="primary",
                            disabled=st.session_state.running or _n_files < 2 or bool(_model_issues))
    with status_col:
        if st.session_state.running:
            _status, _cls = "Analysis in progress…", ""
        elif _model_issues:
            _status, _cls = html.escape(_model_issues[0]), ""
        elif _n_files >= 2:
            _status, _cls = (f"✓ {_n_files} papers ready · saved to project "
                             f"“{html.escape(_cur_project['name'])}” · a run usually takes 5–10 minutes"), " ready"
        elif _n_files == 1:
            _status, _cls = "Add at least one more paper to begin.", ""
        else:
            _status, _cls = "Add 2–5 PDFs, or tick papers already in the project, to begin.", ""
        st.markdown(f'<div class="run-status{_cls}">{_status}</div>', unsafe_allow_html=True)

# ── Main Pipeline ─────────────────────────────────────────────────────────────
if run_btn and _papers:
    # The Run button is already held when a needed key is missing; this is the
    # same check again for any path that reaches here anyway.
    if _model_issues:
        st.error(" ".join(_model_issues))
        st.stop()
    if len(_papers) < 2:
        st.warning("Choose at least 2 papers.")
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

    prog = st.progress(0)
    stat = st.empty()
    def upd(msg, pct):
        prog.progress(pct)
        stat.markdown(_card("Pipeline Running", f"⟳ {msg}"), unsafe_allow_html=True)

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
            options=RunOptions(
                provider_key=_model_cfg.spec_for(ROLE_ANALYSIS).provider,
                model=_model_cfg.spec_for(ROLE_ANALYSIS).model,
                models=_model_cfg.to_dict(),
                use_vision=use_vision,
                extract_refs=extract_refs,
                ref_limit=None if ref_limit == "All" else int(ref_limit),
                enable_quality_engine=enable_quality_engine,
                override_quality_gate=override_quality_gate,
                enable_gap_challenger=enable_gap_challenger,
                nvidia_api_key=api_key,
                enable_graph_persistence=True,   # SQLite makes this free; no longer an opt-in
                project_id=st.session_state.current_project_id,
                ss_api_key=ss_api_key,
                domain_config=domain_cfg,
                git_commit=_GIT_COMMIT,
            ),
            progress=upd,
            trace=_add_trace,
            warn=lambda m: st.warning(f"⚠️ {m}"),
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
            st.warning(
                f"⚠️ Quality gate FAILED — gap analysis skipped: "
                f"{'; '.join(outcome.gate_block_reasons)}. "
                f"Fetched data ({outcome.n_papers} papers, {outcome.n_refs} refs, "
                f"{outcome.n_evidence} evidence objects) was saved as "
                f"'{outcome.name}' ({outcome.run_id[:8]}…). "
                "Re-run with the sidebar override checked to force gap analysis anyway."
            )
        else:
            st.success(f"✅ Done — {outcome.n_gaps} gaps, {outcome.n_proposals} proposals. "
                       f"Saved as '{outcome.name}' ({outcome.run_id[:8]}…)")

    except PipelineInputError as e:
        # A caller-input problem (too few papers), not a crash -- reported
        # the same way the old inline `len(uploaded_files) < 2` check was.
        prog.empty(); stat.empty()
        st.warning(str(e))
    except Exception as e:
        prog.empty(); stat.empty()
        st.error(f"Pipeline error: {e}")
        with st.expander("Error details"):
            st.code(traceback.format_exc())
    finally:
        st.session_state.running = False

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
        {context.get('domain','')} — Domain-Tuned Analysis</span>
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
    # original st.warning() toast is gone (e.g. reloading a saved run from
    # history) -- gaps/proposals being empty here is a gate block, not a
    # genuinely gap-free corpus, and that distinction matters to the user.
    if res.get("gate_blocked"):
        reasons = "; ".join(res.get("gate_block_reasons", [])) or "corpus below quality threshold"
        st.warning(
            f"⚠️ This run's quality gate FAILED, so gap analysis was skipped: {reasons}. "
            "Papers, references, wiki, and evidence below were still fetched and saved. "
            "Re-run with the sidebar override checked to force gap analysis anyway."
        )

    # Corpus stats bar
    c_stats = res.get("corpus_stats", {})
    ref_sum = res.get("ref_summary", {})
    if c_stats:
        # No reference diagnostics means the reference stage never ran (it is
        # off by default); "Off" is honest where "0" reads like a failure.
        _note = off_note(res)
        if _note is None:
            t1,t2,t3,t4 = st.columns(4)
            for col,(val,lbl,color) in zip([t1,t2,t3,t4],[
                (c_stats.get("tier1",0), "Uploaded PDFs", "#0066cc"),
                (c_stats.get("tier2",0), "Cited (w/ abstract)", "#087f5b"),
                (c_stats.get("tier3",0), "Distant refs", "#55708f"),
                (ref_sum.get("total",0), "Total corpus", "#b7791f"),
            ]):
                with col:
                    st.markdown(f'<div class="stat-box"><span class="stat-number" '
                                f'style="color:{color};">{val}</span>'
                                f'<span class="stat-label">{lbl}</span></div>',
                                unsafe_allow_html=True)
        else:
            st.caption(_note)
        st.markdown("")

    # Summary row
    m1,m2,m3,m4,m5 = st.columns(5)
    for col,(val,lbl) in zip([m1,m2,m3,m4,m5], overview(res)):
        with col:
            st.markdown(f'<div class="stat-box"><span class="stat-number">{val}</span>'
                        f'<span class="stat-label">{lbl}</span></div>', unsafe_allow_html=True)

    # One row per paper, so a paper that silently contributed nothing is visible.
    _cov = paper_coverage(res)
    if _cov:
        import pandas as pd
        _bad = [r for r in _cov if r["status"] != "ok"]
        with st.expander(f"Paper coverage — {len(_cov) - len(_bad)} of {len(_cov)} papers fully processed"
                         + (" · ⚠️ check" if _bad else ""), expanded=bool(_bad)):
            _table(pd.DataFrame([{
                "Paper": r["title"][:44] + ("…" if len(r["title"]) > 44 else ""),
                "Type": (r["study_type"] or "—").replace("_", " ").replace("systematic or narrative ", "")
                                                .replace(" or questionnaire", "").replace(" or lab", ""),
                "Wiki": r["wiki_items"], "Evid.": r["evidence"], "Quoted": r["quoted"],
                "Entities": r["entities"], "Gaps": r["gaps"], "Props": r["proposals"],
                "OK": "✅" if r["status"] == "ok" else "⚠️ " + "; ".join(r["problems"]),
            } for r in _cov]), hide_index=True)
            st.caption("Wiki = facts compiled from the paper · Evid. = evidence items · Quoted = items with a verified "
                       "quote and page · Entities = knowledge-graph entities · Gaps / Props = gaps and proposals "
                       "that rest on the paper.")

    st.markdown("")

    tab1,tab2,tab3,tab4,tab5,tab6,tab7,tab8 = st.tabs([
        "📄 Wiki Pages",
        "📚 Reference Corpus",
        "🕸️ Knowledge Graph",
        "🔍 Research Gaps",
        "💡 Proposals",
        "📊 Computational Lab",
        "🔎 Pipeline Trace",
        "📦 Export",
    ])

    # ── Tab 1: Wiki Pages ──────────────────────────────────────────────────────
    with tab1:
        st.markdown("### Compiled Wiki Pages")
        for i, paper_res in enumerate(res.get("papers",[])):
            page  = paper_res.get("wiki", {})
            title = page.get("title", paper_res.get("filename", f"Paper {i+1}"))
            with st.expander(f"T1 Uploaded PDF · {title}", expanded=False):
                st.markdown(
                    f'{_tier_badge(1)} '
                    f'<span style="font-weight:700;color:#004b93;">{html.escape(str(title))}</span>',
                    unsafe_allow_html=True,
                )
                c1,c2 = st.columns(2)
                with c1:
                    _section_label("Contributions")
                    for c in page.get("contributions",[])[:5]: _item(f"• {c}")
                    st.markdown("")
                    _section_label("Methods")
                    for m in page.get("methods",[])[:5]: _item(f"• {m}")
                with c2:
                    _section_label("Limitations ⚠️")
                    for lim in page.get("limitations",[])[:4]: _item(f"• {lim}","#c81e1e")
                    st.markdown("")
                    _section_label("Future Work 🔭")
                    for fw in page.get("future_work",[])[:4]: _item(f"• {fw}","#087f5b")
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
                    f"<strong>{link.get('concept','')}</strong> — {link.get('context','')}<br>"
                    f"<span style='font-family:\"DM Mono\",monospace;font-size:0.7rem;color:#0066cc;'>"
                    f"{', '.join(link.get('papers',[]))}</span>"
                ), unsafe_allow_html=True)

    # ── Tab 2: Reference Corpus ────────────────────────────────────────────────
    with tab2:
        st.markdown("### Reference Corpus")
        if ref_diagnostics:
            d1,d2,d3,d4 = st.columns(4)
            for col,(val,lbl,color) in zip([d1,d2,d3,d4],[
                (ref_diagnostics.get("raw_entries",0), "Raw Citations", "#0066cc"),
                (ref_diagnostics.get("structured_entries",0), "LLM Parsed", "#087f5b"),
                (ref_diagnostics.get("fallback_entries",0), "Fallback Parsed", "#b7791f"),
                (ref_diagnostics.get("duplicates_skipped",0), "Duplicates", "#55708f"),
            ]):
                with col:
                    st.markdown(f'<div class="stat-box"><span class="stat-number" '
                                f'style="font-size:1.3rem;color:{color};">{val}</span>'
                                f'<span class="stat-label">{lbl}</span></div>',
                                unsafe_allow_html=True)
            if ref_diagnostics.get("errors"):
                with st.expander("Reference extraction warnings"):
                    for err in ref_diagnostics.get("errors", [])[:20]:
                        st.warning(err)
            st.markdown("")

        if not ref_papers:
            if not res.get("ref_summary",{}).get("total"):
                st.info("No references are available yet. Enable reference extraction in the sidebar and run the analysis.")
            else:
                st.info("Reference summary exists, but detailed references were not saved in this older run. Re-run once to persist them.")
        else:
            summary = summarise_reference_corpus(ref_papers)
            ra,rb,rc,rd = st.columns(4)
            for col,(val,lbl,color) in zip([ra,rb,rc,rd],[
                (summary["total"],"Total Refs","#0066cc"),
                (summary["tier2_abstract"],"With Abstract","#087f5b"),
                (summary["tier3_title"],"Title Only","#55708f"),
                (summary["year_range"],"Year Range","#b7791f"),
            ]):
                with col:
                    st.markdown(f'<div class="stat-box"><span class="stat-number" '
                                f'style="font-size:1.3rem;color:{color};">{val}</span>'
                                f'<span class="stat-label">{lbl}</span></div>',
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

            st.markdown(f'<div style="font-size:0.8rem;color:#55708f;margin-bottom:0.8rem;">'
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
                    + (f'<div style="font-size:0.76rem;color:#55708f;margin-top:0.2rem;">{authors}</div>' if authors else '')
                    + (f'<div style="font-size:0.76rem;color:#55708f;margin-top:0.2rem;font-style:italic;">{venue}</div>' if venue else '')
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
                            st.info(f"Showing first 40 of {len(refs_for_paper)} references for this source paper. Use search or table view to inspect the rest.")
            else:
                for i, ref in enumerate(filtered[:80], 1):
                    _render_ref(ref, idx=i)

    # ── Tab 3: Knowledge Graph ─────────────────────────────────────────────────
    with tab3:
        st.markdown("### Knowledge Graph (LazyGraphRAG)")
        stats = graph.get("stats",{})
        graph_diag = graph.get("diagnostics", {})
        if graph_diag.get("used_fallback"):
            st.warning("The LLM graph extraction returned no entities, so a deterministic fallback graph was built from wiki concepts, methods, datasets, limitations, and findings.")
        elif graph_diag:
            st.info(f"LLM graph extraction produced {graph_diag.get('llm_entities', 0)} entities and {graph_diag.get('llm_relationships', 0)} relationships.")

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
                f'<span style="color:{color}; font-weight:600;">{icon} Graph Quality: {gq["build_status"]}</span> '
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
                st.markdown(f'<div class="stat-box"><span class="stat-number" '
                            f'style="font-size:1.5rem;">{val}</span>'
                            f'<span class="stat-label">{lbl}</span></div>',
                            unsafe_allow_html=True)
        st.markdown("")

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
                        mtext.append(f"{nodes[si]['name']} → {nodes[ti]['name']}<br>"
                                     f"<b>{str(e.get('relation','')).replace('_',' ')}</b>"
                                     + (f"<br>{textwrap.shorten(e['evidence'], 140)}" if e.get("evidence") else ""))
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
                        hovertext=[f"<b>{nodes[i]['name']}</b><br>{ntype} · {nodes[i]['importance']} importance"
                                   f"<br>{'; '.join(nodes[i].get('papers', []))[:120]}" for i in idx],
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
                st.info("pip install plotly for network diagram")

        for comm in graph.get("communities",[]):
            with st.expander(f"🏘️ {comm.get('theme','Community')}"):
                st.markdown(f'<div class="stage-body">{comm.get("summary","")}</div>',
                            unsafe_allow_html=True)
                if comm.get("gap_signal"):
                    st.markdown(
                        f'<div style="background:#fff7e6;border:1px solid #f0c36a;border-radius:4px;'
                        f'padding:0.5rem 0.8rem;margin-top:0.5rem;font-size:0.82rem;color:#b7791f;">'
                        f'⚠️ {comm["gap_signal"]}</div>', unsafe_allow_html=True)

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
                    f'<span style="font-family:\'DM Mono\',monospace;color:#004b93;">{ent.get("name","")}</span>'
                    f'<span style="font-family:\'DM Mono\',monospace;color:#55708f;font-size:0.7rem;'
                    f'margin-left:0.6rem;">[{ent.get("type","")}]</span>'
                    f'<div style="font-size:0.78rem;color:#55708f;">{o.get("signal","")}</div></div>',
                    unsafe_allow_html=True)

    # ── Tab 4: Research Gaps ───────────────────────────────────────────────────
    with tab4:
        st.markdown("### Identified Research Gaps")
        open_n    = sum(1 for g in gaps if g.get("validation_status")=="open")
        partial_n = sum(1 for g in gaps if g.get("validation_status")=="partial")
        solved_n  = sum(1 for g in gaps if g.get("validation_status")=="solved")
        f1,f2,f3 = st.columns(3)
        for col,(lbl,cnt,color) in zip([f1,f2,f3],[
            ("🟢 Open",open_n,"#087f5b"),
            ("🟡 Partial",partial_n,"#b7791f"),
            ("🔴 Solved",solved_n,"#c81e1e"),
        ]):
            with col:
                st.markdown(f'<div class="stat-box"><span class="stat-number" '
                            f'style="color:{color};font-size:1.5rem;">{cnt}</span>'
                            f'<span class="stat-label">{lbl}</span></div>',
                            unsafe_allow_html=True)
        st.markdown("")

        status_badge = {
            "open":    _badge("Open","#087f5b","#e7f8f1","#83d7b1"),
            "partial": _badge("Partial","#b7791f","#fff7e6","#f0c36a"),
            "solved":  _badge("Solved","#c81e1e","#fff1f1","#f0a0a0"),
            "pending": _badge("Pending","#55708f","#f2f5f8","#c9dff5"),
            "unverified": _badge("Not checked — search unavailable","#8a5a00","#fff4d6","#e8c66a"),
        }
        # Clinova Phase 3, Epic 3.4 -- only present when the opt-in Gap
        # Challenger toggle ran; additive to status_badge above, not a
        # replacement (Stage 5's simple validation_status still renders too).
        challenger_badge = {
            "INSUFFICIENT_EVIDENCE": _badge("Insufficient Evidence","#55708f","#f2f5f8","#c9dff5"),
            "OPEN":                  _badge("Challenger: Open","#087f5b","#e7f8f1","#83d7b1"),
            "PARTIALLY_OPEN":        _badge("Partially Open","#b7791f","#fff7e6","#f0c36a"),
            "CONTESTED":             _badge("Contested","#a94ba0","#f9edf8","#dcaad9"),
            "LIKELY_CLOSED":         _badge("Likely Closed","#c8681e","#fff1e6","#f0b380"),
            "CLOSED":                _badge("Closed","#c81e1e","#fff1f1","#f0a0a0"),
        }
        _gap_fb_run = st.session_state.current_run_id
        _gap_fb_project = (get_run_row(_gap_fb_run) or {}).get("project_id") if _gap_fb_run else None
        _gap_fb_existing = ({f["target_id"]: f for f in list_feedback(run_id=_gap_fb_run, target_type="gap")}
                            if _gap_fb_run else {})
        for gap_idx, gap in enumerate(gaps):
            status = gap.get("validation_status","pending")
            conf   = gap.get("confidence","medium")
            source = gap.get("source", "semantic")
            _lens = source.split(":", 1)[1] if source.startswith("agent:") else source
            source_badge = _badge(_GAP_LENS_LABELS.get(_lens, _lens.replace("_", " ").title()),
                                  "#55708f", "#f2f5f8", "#c9dff5")
            rank_badge = (_badge(f"#{gap['rank']} · {gap['composite_score']}/5", "#0b1f3a", "#eaf1fb", "#9db8d6")
                          if gap.get("rank") and gap.get("composite_score") is not None else "")
            challenger_status = gap.get("challenger_status")
            st.markdown(
                f'<div class="gap-card {status}">'
                f'<div class="gap-title">{gap.get("title","Untitled")}</div>'
                f'<div class="gap-meta">{rank_badge} {status_badge.get(status,"")} '
                f'{_badge(conf.title()+" Conf","#004b93","#e5f2ff","#7ab8f5")} '
                f'{source_badge}'
                f'{challenger_badge.get(challenger_status, "")}</div>'
                f'<div class="gap-desc">{gap.get("description","")}</div></div>',
                unsafe_allow_html=True)
            if gap.get("critique"):
                _sc = gap.get("scores") or {}
                st.caption(f"Critic: {gap['critique']}  \n"
                           f"novelty {_sc.get('novelty', '–')} · importance {_sc.get('importance', '–')} · "
                           f"feasibility {_sc.get('feasibility', '–')} (1–5)")
            if gap.get("confidence_caveat"):
                st.caption(f"⚠️ {gap['confidence_caveat']}")
            with st.expander("Evidence + validation"):
                ec1,ec2 = st.columns(2)
                with ec1:
                    _section_label("Evidence from Papers")
                    for ev in gap.get("evidence",[]): _item(f"📎 {ev}")
                    if gap.get("search_query_used"):
                        st.markdown("")
                        _section_label("Search Query Used")
                        st.code(gap["search_query_used"], language=None)
                with ec2:
                    for ep in gap.get("existing_papers",[])[:4]:
                        _item(f"📄 {ep.get('title','N/A')} ({ep.get('year','')}) [{ep.get('source','')}]")

                funnel = gap.get("challenge_funnel")
                if funnel:
                    st.markdown("")
                    _section_label("Gap Challenger — Search Coverage Funnel")
                    st.markdown(
                        f"Coverage score: **{funnel.get('search_coverage_score', 0):.2f}** "
                        f"(threshold 0.60) · candidates found: {funnel.get('candidate_count', 0)} → "
                        f"deduped: {funnel.get('post_dedup_count', 0)} · "
                        f"relevant: {funnel.get('relevant_count', 0)} · "
                        f"contradicting: {funnel.get('contradiction_count', 0)} · "
                        f"converging (high-conf, direct): {funnel.get('converging_count', 0)}"
                    )
                    providers = funnel.get("provider_success", {})
                    if providers:
                        st.markdown(
                            "Providers: " + ", ".join(
                                f"{'✅' if ok else '❌'} {name.replace('_', ' ')}"
                                for name, ok in providers.items()
                            )
                        )
                    for q in funnel.get("query_families", []):
                        st.code(q, language=None)
                elif gap.get("challenger_error"):
                    st.caption(f"Gap Challenger failed for this gap: {gap['challenger_error']}")
            if _gap_fb_project:
                _gap_feedback(gap, gap_idx, _gap_fb_run, _gap_fb_project, _gap_fb_existing)

        _rejected = res.get("rejected_gaps") or []
        if _rejected:
            with st.expander(f"Considered and set aside by the critic ({len(_rejected)})"):
                st.caption("Candidates the finder agents proposed that the critic merged into another gap, "
                           "judged generic or already answered, or ranked below the top list.")
                for g in _rejected:
                    _item(f"{g.get('title', 'Untitled')} — {g.get('rejected_reason', '')}")
        _supp = res.get("supplementary_gaps") or []
        if _supp:
            with st.expander(f"Supplementary signals — not validated ({len(_supp)})"):
                st.caption("Rule-based checks (only for papers whose study type they fit) and knowledge-graph hints. "
                           "They are leads, not findings: they are not searched against the literature or used for proposals.")
                for g in _supp:
                    _item(f"{g.get('title', 'Untitled')}: {g.get('description', '')}")

    # ── Tab 5: Proposals ───────────────────────────────────────────────────────
    with tab5:
        st.markdown("### Research Proposals")
        _open_gaps = [g for g in res.get("gaps", []) if g.get("validation_status") in ("open", "partial")]
        if not proposals and _open_gaps:
            # A run can finish with no proposals (the model's reply was unreadable);
            # fill them in for this run instead of repeating the whole analysis.
            st.warning(f"This run has no proposals, although it found {len(_open_gaps)} open or partial gaps.")
            if st.button("Generate proposals now", key="gen_proposals_now", type="primary",
                         help="Runs only the proposal step on this run's gaps (about 10–30 seconds)."):
                try:
                    with st.spinner("Generating proposals…"):
                        _pclient = ModelRouter(st.session_state["model_config"], _keys)
                        _new = redo_proposal_step(res, context, _pclient, domain_config=domain_cfg)
                    if not _new:
                        st.error("The model returned nothing usable. Try again, or choose another Analysis model.")
                    else:
                        res["proposals"] = _new
                        st.session_state.results = res
                        _rid = st.session_state.current_run_id
                        if _rid:
                            update_run_proposals(_rid, _new)
                            try:
                                project_store.refresh_run_results(
                                    st.session_state.current_project_id, _rid, res, context,
                                    st.session_state.comp_results)
                            except Exception:
                                pass
                        st.rerun()
                except Exception as e:
                    st.error(f"Could not generate proposals: {e}")
        for i, proposal in enumerate(proposals, 1):
            conf   = proposal.get("confidence","medium")
            effort = proposal.get("effort_estimate","")
            ec     = {"short":"#087f5b","medium":"#b7791f","long":"#c81e1e"}.get(
                (effort.split()[0].lower() if effort else ""), "#55708f")
            st.markdown(
                f'<div class="proposal-card">'
                f'<div class="proposal-title">#{i}  {proposal.get("title","Untitled")}</div>'
                f'<div>{_badge(conf.title()+" Conf","#004b93","#e5f2ff","#7ab8f5")}'
                f'{_badge(effort,ec,"#e7f8f1",ec)}</div>'
                f'<div class="proposal-section">Problem Statement</div>'
                f'<div class="proposal-body">{proposal.get("problem_statement","")}</div>'
                f'<div class="proposal-section">Proposed Methodology</div>'
                f'<div class="proposal-body">{proposal.get("methodology","")}</div>'
                f'<div class="proposal-section">Novelty</div>'
                f'<div class="proposal-body">{proposal.get("novelty","")}</div></div>',
                unsafe_allow_html=True)
            _rv = proposal.get("review")
            if _rv:
                _rs = _rv.get("scores") or {}
                st.caption(
                    f"Reviewer: {'revised after review' if _rv.get('revised') else _rv.get('verdict', '')} · "
                    f"specificity {_rs.get('specificity', '–')} · novelty {_rs.get('novelty', '–')} · "
                    f"feasibility {_rs.get('feasibility', '–')} · impact {_rs.get('impact', '–')} (1–5)"
                    + (f"  \nIssues raised: {'; '.join(_rv['issues'])}" if _rv.get("issues") else ""))
            with st.expander("Experiments + datasets"):
                e1,e2 = st.columns(2)
                with e1:
                    for exp in proposal.get("suggested_experiments",[]): _item(f"🧪 {exp}")
                with e2:
                    for src in proposal.get("builds_on",[]): _item(f"📎 {src}")

    # ── Tab 6: Computational Lab ───────────────────────────────────────────────
    with tab6:
        st.markdown("### 📊 Computational Lab")
        st.markdown(
            '<div style="font-size:0.82rem;color:#55708f;margin-bottom:1.5rem;">'
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
                '<div style="font-size:0.78rem;color:#55708f;padding-top:0.5rem;">'
                f'Stages 7–12 · Uses Tier 1 + Tier 2 params · {n_council_runs}× council runs</div>',
                unsafe_allow_html=True)
        st.caption(f"Results are added to this run (“{st.session_state.current_run_name or 'current run'}”), "
                   "so the run and its Lab output stay together in one report.")

        if run_comp:
            comp_prog = st.progress(0)
            comp_stat = st.empty()
            def cupd(msg, pct):
                comp_prog.progress(pct)
                comp_stat.markdown(_card("Computational Lab", f"⟳ {msg}"),
                                   unsafe_allow_html=True)
            try:
                # Same per-role models as the main run; the council seats and chair
                # come from the Council rows under "Models for this run". The stages
                # (and the data-sufficiency gate on the simulation) live in pipeline/run_lab.py.
                client = ModelRouter(st.session_state["model_config"], _keys)
                st.session_state.comp_results = run_computational_lab(
                    res, context, client, domain_config=domain_cfg, n_council_runs=n_council_runs,
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
                        st.warning("The Lab finished but could not be saved to the run.")

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
                    st.warning(f"⚠️ {_cr['council_error']}. Run the Lab again in a few minutes, or choose "
                               "different Council models under “Models for this run”.")

            except Exception as e:
                comp_prog.empty(); comp_stat.empty()
                st.error(f"Error: {e}")
                with st.expander("Error details"):
                    st.code(traceback.format_exc())

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

            # Data availability
            score      = sufficiency.get("coverage_score",0)
            sc         = "#087f5b" if score>=7 else "#b7791f" if score>=4 else "#c81e1e"
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
              <div style="font-size:0.78rem;color:#55708f;margin-top:0.3rem;">
                {sufficiency.get('why_score_is_low','')}
              </div>
            </div>""", unsafe_allow_html=True)

            # Per-paper coverage: a paper with no stated numbers (results shown
            # only in figures, or a narrative review) must be visible, not silent.
            _papers = res.get("papers", [])
            if _papers:
                _per = {}
                for _p in params:
                    if not _p.get("is_derived") and _p.get("paper_index") is not None:
                        _per[_p["paper_index"]] = _per.get(_p["paper_index"], 0) + 1
                st.caption("Parameters per paper: " + " · ".join(
                    f"{pp.get('filename', f'Paper {i + 1}')}: {_per.get(i, 0)}"
                    for i, pp in enumerate(_papers)))
                _none = [pp.get("filename", f"Paper {i + 1}") for i, pp in enumerate(_papers) if not _per.get(i)]
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
                        derived_t = " 🔀" if p.get("is_derived") else ""
                        conf_c = {"high":"#087f5b","medium":"#b7791f","low":"#c81e1e"}.get(
                            p.get("confidence","medium"),"#55708f")
                        st.markdown(
                            f'<div class="wiki-item" style="margin-bottom:0.4rem;">'
                            f'{_tier_badge(tier_t)}'
                            f'<span style="color:#004b93;">{p.get("name","")}</span> = '
                            f'<span style="color:{conf_c};font-family:\'DM Mono\',monospace;">'
                            f'{p.get("value","")}{ci}</span> {p.get("unit","")}'
                            f'<span style="color:#55708f;font-size:0.7rem;"> '
                            f'[{p.get("source_paper","")[:45]}]{derived_t}</span></div>',
                            unsafe_allow_html=True)

            st.download_button("⬇ Download parameters.csv", data=cr["csv_data"],
                               file_name="parameters.csv", mime="text/csv")

            # Discovery
            st.markdown("#### Stage 8B — Novel Hypotheses")
            for h in discovery.get("hypotheses",[]):
                conf  = h.get("confidence","medium")
                cc    = {"high":"#087f5b","medium":"#b7791f","low":"#c81e1e"}.get(conf,"#55708f")
                st.markdown(
                    f'<div style="background:#edf6ff;border:1px solid #7ab8f5;'
                    f'border-left:4px solid {cc};border-radius:8px;'
                    f'padding:1.2rem 1.5rem;margin-bottom:1rem;">'
                    f'<div style="font-size:1.05rem;color:#0b1f3a;font-weight:500;">'
                    f'{h.get("hypothesis_id","H?")}  {h.get("title","")}</div>'
                    f'<div style="font-size:0.87rem;color:#0b1f3a;margin-top:0.4rem;">'
                    f'{h.get("claim","")}</div>'
                    f'<div style="margin-top:0.5rem;">'
                    + _badge(f"Novelty {h.get('novelty_score',0)}/10","#004b93","#e5f2ff","#7ab8f5")
                    + _badge(conf.title()+" Conf",cc,"#ffffff",cc)
                    + '</div></div>',
                    unsafe_allow_html=True)
                if h.get("unsupported_numbers"):
                    st.caption("⚠️ Contains figures no paper reports (" + ", ".join(h["unsupported_numbers"])
                               + "): unsupported, confidence lowered.")
                with st.expander(f"Evidence + opportunities for {h.get('hypothesis_id','')}"):
                    hc1,hc2 = st.columns(2)
                    with hc1:
                        _section_label("Mechanism"); _item(h.get("mechanism",""))
                        st.markdown("")
                        _section_label("Validation Study"); _item(h.get("validation_study",""),"#004b93")
                    with hc2:
                        _section_label("Clinical Opportunity"); _item(h.get("clinical_opportunity",""),"#087f5b")
                        st.markdown("")
                        _section_label("Commercial Opportunity"); _item(h.get("commercial_opportunity",""),"#b7791f")

            # Simulation
            st.markdown(f"#### Stage 10 — Simulation: {sim_results.get('model_used','')}")
            if sim_results.get("skipped"):
                st.info("**Simulation skipped.** The papers do not contain enough usable quantitative parameters "
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
                        f'{i}. {s["parameter"]}{label_extra}</div>'
                        f'<div style="background:#c9dff5;border-radius:3px;height:6px;margin-top:2px;">'
                        f'<div style="background:#0066cc;width:{bar}%;height:6px;border-radius:3px;"></div>'
                        f'</div></div>', unsafe_allow_html=True)

            if cr.get("council_error"):
                st.warning(f"⚠️ {cr['council_error']}. The insight sections below are empty for that reason; "
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
                  <div style="font-size:0.68rem;color:#55708f;text-transform:uppercase;">Novel Findings</div>
                </div>
                <div style="text-align:center;">
                  <div style="font-size:1.4rem;color:#004b93;font-family:'DM Mono',monospace;">
                    {cov.get('total_clinical_insights',0)}</div>
                  <div style="font-size:0.68rem;color:#55708f;text-transform:uppercase;">Clinical Insights</div>
                </div>
                <div style="text-align:center;">
                  <div style="font-size:1.4rem;color:#b7791f;font-family:'DM Mono',monospace;">
                    {cov.get('total_next_steps',0)}</div>
                  <div style="font-size:0.68rem;color:#55708f;text-transform:uppercase;">Next Steps</div>
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
                    f'<div>{_badge(g["confidence"],cc,"#ffffff",cc)}'
                    f'{_badge(freq,"#55708f","#f2f5f8","#c9dff5")}</div></div>'
                    f'<div style="font-size:1.05rem;color:#0b1f3a;font-weight:600;margin:0.5rem 0 0.4rem;">'
                    f'{nf.get("title","")}</div>'
                    f'<div style="font-size:0.88rem;color:#0b1f3a;line-height:1.7;">{nf.get("claim","")}</div>'
                    f'<div style="font-size:0.75rem;color:#55708f;margin-top:0.4rem;font-style:italic;">'
                    f'What\'s new: {nf.get("what_makes_it_new","")}</div></div>',
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
                        f'<div style="font-size:0.85rem;color:#0b1f3a;">{icon} {g["representative"]}</div>'
                        f'<div>{_badge(g["confidence"],cc,"#ffffff",cc)}'
                        f'{_badge(g["frequency"],"#55708f","#f2f5f8","#c9dff5")}</div></div></div>',
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
    with tab7:
        st.markdown("### 🔎 Pipeline Trace — Explainability View")
        trace = saved_trace(res, st.session_state.pipeline_trace)
        _ts = trace_summary(res, get_run_manifest(st.session_state.current_run_id)
                            if st.session_state.current_run_id else None)
        if _ts.get("models"):
            st.markdown("**Models used:** " + " · ".join(f"{html.escape(str(r))}: {html.escape(str(m))}"
                                                         for r, m in _ts["models"].items()))
        if _ts.get("fallback_count"):
            st.warning(f"{_ts['fallback_count']} call(s) used the fallback model: " + "; ".join(_ts["fallbacks"][:5]))
        if _ts.get("tokens_total"):
            st.caption(f"Tokens used: {_ts['tokens_total']:,} in total · "
                       + " · ".join(f"{k}: {v:,}" for k, v in _ts["tokens_by_stage"].items()))
        if not trace:
            st.info("This run has no stage trace stored (it was saved before traces were kept). "
                    "Run a new analysis to get one.")
        else:
            for entry in trace_rows(trace):
                i = entry["n"]
                st.markdown(
                    f'<div style="background:#ffffff;border:1px solid #c9dff5;'
                    f'border-left:3px solid #0066cc;border-radius:6px;'
                    f'padding:0.8rem 1.2rem;margin-bottom:0.5rem;">'
                    f'<div style="font-family:\'DM Mono\',monospace;font-size:0.7rem;color:#0066cc;">'
                    f'{entry.get("status","✅")} STAGE {i} — {entry["stage"]}</div>'
                    f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:0.5rem;">'
                    f'<div><span style="font-family:\'DM Mono\',monospace;font-size:0.62rem;color:#55708f;">IN: </span>'
                    f'<span style="font-size:0.8rem;color:#0b1f3a;">{entry["inputs"]}</span></div>'
                    f'<div><span style="font-family:\'DM Mono\',monospace;font-size:0.62rem;color:#55708f;">OUT: </span>'
                    f'<span style="font-size:0.8rem;color:#087f5b;">{entry["outputs"]}</span></div>'
                    f'</div></div>',
                    unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("#### Active prompts")
        from pipeline.wiki_compiler import WIKI_SYSTEM_PROMPT
        from pipeline.gap_detector import GAP_DETECTION_PROMPT
        with st.expander("Wiki compiler prompt"):
            st.code(WIKI_SYSTEM_PROMPT, language=None)
        with st.expander("Gap detection prompt"):
            st.code(GAP_DETECTION_PROMPT, language=None)

    # ── Tab 8: Export ──────────────────────────────────────────────────────────
    with tab8:
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
        gen_col, mode_col = st.columns([1, 2])
        with gen_col:
            generate_report = st.button("Generate final report", key="generate_final_report")
        with mode_col:
            use_llm_report = st.checkbox("Use LLM narrative polish", value=True,
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
                html_report = to_enterprise_html_report(res, context, narrative=narrative, comp_results=_comp)
                pdf_report = to_enterprise_pdf_report(res, context, narrative=narrative, comp_results=_comp)
                st.session_state.report_bundle = {
                    "html": html_report,
                    "pdf": pdf_report,
                    "run_id": st.session_state.current_run_id,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "used_llm": bool(report_client),
                    "with_lab": bool(_comp),
                    "saved": False,
                }
                st.success("Final report generated.")
            except Exception as e:
                st.error(f"Final report generation failed: {e}")
                with st.expander("Report error details"):
                    st.code(traceback.format_exc())

        bundle = st.session_state.report_bundle
        if bundle and bundle.get("run_id") == st.session_state.current_run_id:
            st.info(f"Report ready. Generated at {bundle.get('generated_at','')} · "
                    f"LLM narrative: {'yes' if bundle.get('used_llm') else 'no'} · "
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
                        st.error(f"Could not save the report: {e}")
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
                st.error(f"PDF report generation failed: {e}")
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
