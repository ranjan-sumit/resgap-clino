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
    page_title=_BRANDING["product_name"],
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS — dark editorial theme ────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap');

  /* ── Base ── */
  html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
    background-color: #ffffff;
    color: #0b1f3a;
  }
  .stApp { background-color: #ffffff; }

  /* ── Sidebar ── */
  [data-testid="stSidebar"] {
    background-color: #ffffff;
    border-right: 1px solid #c9dff5;
  }
  [data-testid="stSidebar"] .stMarkdown h1,
  [data-testid="stSidebar"] .stMarkdown h2,
  [data-testid="stSidebar"] .stMarkdown h3 {
    color: #0066cc;
    font-family: 'DM Mono', monospace;
    font-size: 0.75rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
  }

  /* ── Main header ── */
  .main-header {
    font-family: 'DM Serif Display', serif;
    font-size: 2.8rem;
    line-height: 1.1;
    background: linear-gradient(135deg, #0066cc 0%, #004b93 50%, #0093d0 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 0.2rem;
  }
  .sub-header {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.95rem;
    color: #55708f;
    font-weight: 300;
    letter-spacing: 0.02em;
    margin-bottom: 2rem;
  }

  /* ── Stage cards ── */
  .stage-card {
    background: #ffffff;
    border: 1px solid #c9dff5;
    border-radius: 8px;
    padding: 1.2rem 1.5rem;
    margin-bottom: 1rem;
  }
  .stage-title {
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    color: #0066cc;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 0.4rem;
  }
  .stage-body { font-size: 0.9rem; color: #0b1f3a; }

  /* ── Gap cards ── */
  .gap-card {
    background: #ffffff;
    border: 1px solid #c9dff5;
    border-left: 3px solid #0066cc;
    border-radius: 6px;
    padding: 1.2rem 1.5rem;
    margin-bottom: 1rem;
  }
  .gap-card.open { border-left-color: #087f5b; }
  .gap-card.partial { border-left-color: #b7791f; }
  .gap-card.solved { border-left-color: #c81e1e; }
  .gap-card.pending { border-left-color: #55708f; }
  .gap-title {
    font-family: 'DM Serif Display', serif;
    font-size: 1.1rem;
    color: #0b1f3a;
    margin-bottom: 0.5rem;
  }
  .gap-meta {
    font-family: 'DM Mono', monospace;
    font-size: 0.7rem;
    color: #55708f;
    margin-bottom: 0.6rem;
  }
  .gap-desc { font-size: 0.88rem; color: #0b1f3a; line-height: 1.6; }

  /* ── Proposal cards ── */
  .proposal-card {
    background: #edf6ff;
    border: 1px solid #7ab8f5;
    border-radius: 8px;
    padding: 1.4rem 1.8rem;
    margin-bottom: 1.2rem;
  }
  .proposal-title {
    font-family: 'DM Serif Display', serif;
    font-size: 1.25rem;
    color: #004b93;
    margin-bottom: 0.8rem;
  }
  .proposal-section {
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    color: #0066cc;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-top: 0.8rem;
    margin-bottom: 0.3rem;
  }
  .proposal-body { font-size: 0.88rem; color: #0b1f3a; line-height: 1.6; }

  /* ── Badges ── */
  .badge {
    display: inline-block;
    padding: 0.2rem 0.6rem;
    border-radius: 12px;
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    font-weight: 500;
    margin-right: 0.4rem;
  }
  .badge-open { background: #e7f8f1; color: #087f5b; border: 1px solid #83d7b1; }
  .badge-partial { background: #fff7e6; color: #b7791f; border: 1px solid #f0c36a; }
  .badge-solved { background: #fff1f1; color: #c81e1e; border: 1px solid #f0a0a0; }
  .badge-high { background: #e5f2ff; color: #004b93; border: 1px solid #7ab8f5; }
  .badge-medium { background: #fff7e6; color: #b7791f; border: 1px solid #f0c36a; }
  .badge-low { background: #f2f5f8; color: #55708f; border: 1px solid #c9dff5; }

  /* ── Wiki card ── */
  .wiki-card {
    background: #ffffff;
    border: 1px solid #c9dff5;
    border-radius: 8px;
    padding: 1.2rem 1.5rem;
    margin-bottom: 0.8rem;
  }
  .wiki-title {
    font-family: 'DM Serif Display', serif;
    font-size: 1.05rem;
    color: #0b1f3a;
    margin-bottom: 0.6rem;
  }
  .wiki-label {
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    color: #0066cc;
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }
  .wiki-item { font-size: 0.83rem; color: #0b1f3a; margin-left: 0.8rem; }

  /* ── Graph stats ── */
  .stat-box {
    background: #ffffff;
    border: 1px solid #c9dff5;
    border-radius: 6px;
    padding: 1rem;
    text-align: center;
  }
  .stat-number {
    font-family: 'DM Mono', monospace;
    font-size: 2rem;
    color: #0066cc;
    display: block;
  }
  .stat-label {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.75rem;
    color: #55708f;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  /* ── Buttons ── */
  .stButton > button {
    background: linear-gradient(135deg, #7ab8f5, #0066cc) !important;
    color: white !important;
    border: none !important;
    border-radius: 6px !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.05em !important;
    padding: 0.6rem 1.5rem !important;
    transition: all 0.2s !important;
  }
  .stButton > button:hover {
    background: linear-gradient(135deg, #0066cc, #0066cc) !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(0, 102, 204, 0.25) !important;
  }

  /* ── Inputs ── */
  .stTextInput > div > div > input,
  .stTextArea > div > div > textarea,
  .stSelectbox > div > div {
    background-color: #ffffff !important;
    border: 1px solid #c9dff5 !important;
    color: #0b1f3a !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 0.85rem !important;
    border-radius: 6px !important;
  }

  /* ── File uploader ── */
  [data-testid="stFileUploader"] {
    background: #ffffff;
    border: 2px dashed #c9dff5;
    border-radius: 8px;
    padding: 1rem;
  }
  [data-testid="stFileUploader"]:hover { border-color: #0066cc; }

  /* ── Tabs ── */
  .stTabs [data-baseweb="tab-list"] {
    gap: 0;
    background: #ffffff;
    border-radius: 8px 8px 0 0;
    border-bottom: 1px solid #c9dff5;
    padding: 0 0.5rem;
  }
  .stTabs [data-baseweb="tab"] {
    font-family: 'DM Mono', monospace !important;
    font-size: 0.78rem !important;
    letter-spacing: 0.05em !important;
    color: #55708f !important;
    padding: 0.7rem 1.2rem !important;
    text-transform: uppercase !important;
  }
  .stTabs [aria-selected="true"] {
    color: #0066cc !important;
    border-bottom: 2px solid #0066cc !important;
  }
  .stTabs [data-baseweb="tab-panel"] {
    background: #ffffff;
    border: 1px solid #c9dff5;
    border-top: none;
    border-radius: 0 0 8px 8px;
    padding: 1.5rem;
  }

  /* ── Expanders ── */
  .streamlit-expanderHeader {
    background: #ffffff !important;
    border: 1px solid #c9dff5 !important;
    border-radius: 6px !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 0.8rem !important;
    color: #0b1f3a !important;
  }
  .streamlit-expanderContent {
    background: #ffffff !important;
    border: 1px solid #c9dff5 !important;
    border-top: none !important;
  }

  /* ── Progress ── */
  .stProgress > div > div { background: linear-gradient(90deg, #7ab8f5, #0066cc) !important; }

  /* ── Divider ── */
  hr { border-color: #c9dff5 !important; }

  /* ── Code ── */
  code { font-family: 'DM Mono', monospace !important; color: #004b93 !important; }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: #ffffff; }
  ::-webkit-scrollbar-thumb { background: #c9dff5; border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: #0066cc; }
</style>
""", unsafe_allow_html=True)

# ── Enterprise UI overlay — Pfizer-inspired clinical productivity style ──────
st.markdown("""
<style>
  :root {
    --bg: #f5f9ff;
    --surface: #ffffff;
    --surface-muted: #edf6ff;
    --border: #c9dff5;
    --text: #0b1f3a;
    --muted: #55708f;
    --accent: #0066cc;
    --accent-strong: #004b93;
    --accent-soft: #e5f2ff;
    --success: #087f5b;
    --warning: #b7791f;
    --danger: #c81e1e;
  }
  html, body, [class*="css"], .stApp {
    background: var(--bg) !important;
    color: var(--text) !important;
    font-family: Inter, "Segoe UI", Roboto, Arial, sans-serif !important;
  }
  [data-testid="stSidebar"] {
    background: linear-gradient(180deg, #ffffff 0%, #f0f7ff 100%) !important;
    border-right: 1px solid var(--border) !important;
  }
  [data-testid="stSidebar"] * { color: var(--text); }
  [data-testid="stSidebar"] .stMarkdown h3,
  [data-testid="stSidebar"] .stMarkdown h4,
  [data-testid="stSidebar"] .stMarkdown h5 {
    color: var(--muted) !important;
    font-family: Inter, "Segoe UI", sans-serif !important;
    font-size: 0.72rem !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
  }
  .main-header {
    color: var(--accent-strong) !important;
    -webkit-text-fill-color: var(--accent-strong) !important;
    background: linear-gradient(90deg, var(--accent-strong), #0093d0) !important;
    -webkit-background-clip: text !important;
    background-clip: text !important;
    font-family: Inter, "Segoe UI", sans-serif !important;
    font-size: 2rem !important;
    font-weight: 700 !important;
    letter-spacing: 0 !important;
  }
  .sub-header {
    color: var(--muted) !important;
    font-size: 0.95rem !important;
    margin-bottom: 1.2rem !important;
  }
  .stage-card, .wiki-card, .gap-card, .proposal-card, .ref-card, .stat-box {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    box-shadow: 0 1px 3px rgba(0, 76, 147, 0.08) !important;
  }
  /* Status-coded left borders must survive the shorthand `border` override
     above (shorthand sets border-left-color too, so these need their own
     !important or they'd all render as the same flat --border colour). */
  .gap-card.open, .ref-card.tier-2-card { border-left: 3px solid var(--success) !important; }
  .gap-card.partial { border-left: 3px solid var(--warning) !important; }
  .gap-card.solved { border-left: 3px solid var(--danger) !important; }
  .gap-card.pending, .ref-card.tier-3-card { border-left: 3px solid var(--muted) !important; }
  .stage-title, .wiki-label, .proposal-section, .stat-label, .gap-meta, .ref-meta {
    color: var(--accent-strong) !important;
    font-family: Inter, "Segoe UI", sans-serif !important;
    letter-spacing: 0.04em !important;
  }
  .stage-body, .gap-desc, .proposal-body, .wiki-item, .ref-title {
    color: var(--text) !important;
  }
  .stat-number { color: var(--accent) !important; }
  .stButton > button, .stDownloadButton > button {
    background: var(--accent) !important;
    color: #ffffff !important;
    border: 1px solid var(--accent) !important;
    border-radius: 6px !important;
    box-shadow: none !important;
    font-family: Inter, "Segoe UI", sans-serif !important;
    font-size: 0.86rem !important;
    letter-spacing: 0 !important;
    padding: 0.48rem 0.9rem !important;
  }
  .stButton > button:hover, .stDownloadButton > button:hover {
    background: var(--accent-strong) !important;
    transform: none !important;
    box-shadow: none !important;
  }
  .stTextInput > div > div > input,
  .stTextArea > div > div > textarea,
  .stSelectbox > div > div {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: 6px !important;
    font-family: Inter, "Segoe UI", sans-serif !important;
  }
  [data-testid="stFileUploader"] {
    background: var(--surface) !important;
    border: 1px dashed #5aa9e6 !important;
  }
  .stTabs [data-baseweb="tab-list"] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
  }
  .stTabs [data-baseweb="tab"] {
    color: var(--muted) !important;
    font-family: Inter, "Segoe UI", sans-serif !important;
    font-size: 0.78rem !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
  }
  .stTabs [aria-selected="true"] {
    color: var(--accent) !important;
    border-bottom: 2px solid var(--accent) !important;
  }
  .stTabs [data-baseweb="tab-panel"] {
    background: transparent !important;
    border: none !important;
    padding: 1rem 0 !important;
  }
  .badge, .tier-badge {
    border-radius: 999px !important;
    font-family: Inter, "Segoe UI", sans-serif !important;
  }
  .tier-1 { background:#e5f2ff !important; color:#004b93 !important; border:1px solid #7ab8f5 !important; }
  .tier-2 { background:#e7f8f1 !important; color:#087f5b !important; border:1px solid #83d7b1 !important; }
  .tier-3 { background:#f2f5f8 !important; color:#55708f !important; border:1px solid #c9d6e2 !important; }
  .badge-high, .badge-open { background:#e7f8f1 !important; color:#087f5b !important; border-color:#83d7b1 !important; }
  .badge-medium, .badge-partial { background:#fff7e6 !important; color:#b7791f !important; border-color:#f0c36a !important; }
  .badge-low, .badge-solved { background:#fff1f1 !important; color:#c81e1e !important; border-color:#f0a0a0 !important; }
</style>
""", unsafe_allow_html=True)

# ── Extra CSS additions (skeleton, tier badges, run history) ──────────────────
st.markdown("""
<style>
  /* Skeleton loader */
  @keyframes shimmer {
    0%   { background-position: -800px 0; }
    100% { background-position:  800px 0; }
  }
  .skeleton {
    background: linear-gradient(90deg, #ffffff 25%, #edf6ff 50%, #ffffff 75%);
    background-size: 800px 100%;
    animation: shimmer 1.4s infinite;
    border-radius: 4px;
    height: 14px;
    margin-bottom: 8px;
  }
  .skeleton-card {
    background: #ffffff;
    border: 1px solid #c9dff5;
    border-radius: 8px;
    padding: 1.2rem;
    margin-bottom: 0.8rem;
  }

  /* Tier badges */
  .tier-1 { background:#e5f2ff; color:#0066cc; border:1px solid #7ab8f5; }
  .tier-2 { background:#e7f8f1; color:#087f5b; border:1px solid #83d7b1; }
  .tier-3 { background:#f2f5f8; color:#55708f; border:1px solid #c9dff5; }
  .tier-badge {
    display:inline-block; padding:0.15rem 0.55rem; border-radius:10px;
    font-family:'DM Mono',monospace; font-size:0.65rem; font-weight:500;
    margin-right:0.4rem; vertical-align:middle;
  }

  /* Run history cards */
  .run-card {
    background:#ffffff; border:1px solid #c9dff5; border-radius:6px;
    padding:0.65rem 0.9rem; margin-bottom:0.4rem; cursor:pointer;
    transition:border-color 0.15s;
  }
  .run-card:hover { border-color:#0066cc; }
  .run-card-title {
    font-size:0.82rem; color:#0b1f3a; font-weight:500; margin-bottom:0.2rem;
  }
  .run-card-meta {
    font-family:'DM Mono',monospace; font-size:0.65rem; color:#55708f;
  }

  /* Reference paper list */
  .ref-card {
    background:#ffffff; border:1px solid #c9dff5; border-left:3px solid #c9dff5;
    border-radius:5px; padding:0.6rem 0.9rem; margin-bottom:0.3rem;
  }
  .ref-card.tier-2-card { border-left-color:#087f5b; }
  .ref-card.tier-3-card { border-left-color:#55708f; }
  .ref-title { font-size:0.85rem; color:#0b1f3a; }
  .ref-meta  { font-family:'DM Mono',monospace; font-size:0.68rem; color:#55708f; margin-top:0.2rem; }
</style>
""", unsafe_allow_html=True)

# ── Imports ───────────────────────────────────────────────────────────────────
import streamlit as st
import tempfile, os, json, traceback
from datetime import datetime

from utils.azure_client import AzureOpenAIClient, MASTER_MODEL, FALLBACK_MODEL
from utils.model_providers import PROVIDER_REGISTRY, DEFAULT_PROVIDER_KEY, build_client
from utils.export import (
    to_json, to_markdown_report, to_pdf_report,
    generate_report_narrative, to_enterprise_html_report,
    to_enterprise_pdf_report,
)
from utils.database import (
    init_db, save_run, list_runs, load_run, delete_run,
    record_artifact, record_run_manifest,
)
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
    connect_ok as arcadedb_connect_ok, save_graph_snapshot, load_graph_snapshot,
    list_graph_snapshots, diff_graph_snapshots, GRAPH_PERSISTENCE_VERSION,
)
from pipeline.relevance_ranking import EMBEDDING_MODEL, RERANK_MODEL
from pipeline.academic_search import validate_gaps
from pipeline.proposal_generator import generate_proposals
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
from pipeline.doc_generator import build_zip
from domain_config import get_domain_display_options, parse_domain_selection, get_domain_config
# Clinova Phase 1 (Epics 1.2-1.3) -- opt-in Corpus Quality Engine + canonical
# reference resolution. Not imported into the always-on Stage 1-6 flow
# above: Docling (docling_parser.py) is measured heavy on CPU (~1.1GB RSS,
# ~86s/paper, evals/benchmarks/baseline/docling-resource-measurement.md),
# so this stays behind the "enable_quality_engine" sidebar toggle rather
# than silently adding that cost to every run.
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
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Helpers ───────────────────────────────────────────────────────────────────
def _badge(text, color="#0066cc", bg="#e5f2ff", border="#7ab8f5"):
    return (f'<span style="display:inline-block;padding:0.15rem 0.5rem;'
            f'border-radius:10px;font-family:\'DM Mono\',monospace;font-size:0.65rem;'
            f'font-weight:500;color:{color};background:{bg};border:1px solid {border};'
            f'margin-right:0.3rem;">{text}</span>')

def _tier_badge(tier: int) -> str:
    label, color, _ = TIER_LABELS.get(tier, ("Unknown","#55708f",""))
    bgs = {1:"#e5f2ff", 2:"#e7f8f1", 3:"#f2f5f8"}
    borders = {1:"#7ab8f5", 2:"#83d7b1", 3:"#c9dff5"}
    return _badge(f"T{tier} {label}", color, bgs.get(tier,"#f2f5f8"), borders.get(tier,"#c9dff5"))

def _card(title, body, color="#0066cc"):
    return (f'<div class="stage-card"><div class="stage-title" style="color:{color};">{title}</div>'
            f'<div class="stage-body">{body}</div></div>')

def _section_label(t):
    st.markdown(f'<div class="wiki-label">{t}</div>', unsafe_allow_html=True)

def _item(t, color="#0b1f3a"):
    st.markdown(f'<div class="wiki-item" style="color:{color};margin-bottom:0.25rem;">{t}</div>',
                unsafe_allow_html=True)

def _skeleton(lines=3):
    html = '<div class="skeleton-card">' + ''.join(
        f'<div class="skeleton" style="width:{w}%;"></div>'
        for w in ([90, 70, 55, 40][:lines])
    ) + '</div>'
    st.markdown(html, unsafe_allow_html=True)

def _add_trace(stage, inp, out, status="✅"):
    st.session_state.pipeline_trace.append(
        {"stage": stage, "inputs": inp, "outputs": out, "status": status}
    )

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"### 🔬 {_BRANDING['product_name']}")
    if _BRANDING["tagline"]:
        st.caption(_BRANDING["tagline"])
    st.markdown("---")

    # API config
    st.markdown("##### API Configuration")
    # B25 fix (2026-08-22): reads MASTER_MODEL/FALLBACK_MODEL from
    # utils/azure_client.py instead of hardcoding the label, so this panel
    # can't silently go stale the next time the master/fallback roles
    # change (exactly what happened here -- this label still said
    # "gpt-oss-120b" after B25 swapped the master model to gpt-oss-20b).
    _master_short = MASTER_MODEL.replace("openai/", "")
    _fallback_short = FALLBACK_MODEL.replace("openai/", "")
    st.markdown(f"""
    <div style="background:#edf6ff;border:1px solid #7ab8f5;border-radius:6px;
                padding:0.8rem 1rem;margin-bottom:0.8rem;">
      <div style="font-family:'DM Mono',monospace;font-size:0.65rem;color:#0066cc;
                  text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.5rem;">Model Stack</div>
      <div style="font-size:0.78rem;color:#0b1f3a;font-weight:500;">🧠 Master — {_master_short}</div>
      <div style="font-family:'DM Mono',monospace;font-size:0.62rem;color:#55708f;line-height:1.9;">
        Fallback · {_fallback_short}<br>
        Council A1 · gpt-oss-20b<br>Council A2 · llama-3.2-3b<br>
        Council A3 · nemotron-30b<br>Chair · gpt-oss-120b · NVIDIA NIM
      </div>
    </div>""", unsafe_allow_html=True)

    api_key = st.text_input("NVIDIA API Key", type="password",
                             placeholder="nvapi-••••••••••••••••")
    st.markdown('<div style="font-family:\'DM Mono\',monospace;font-size:0.62rem;color:#55708f;">'
                '🔗 <a href="https://build.nvidia.com" target="_blank" style="color:#0066cc;">'
                'Get key → build.nvidia.com</a></div>', unsafe_allow_html=True)

    ss_api_key = st.text_input("Semantic Scholar API Key (optional)", type="password",
                                placeholder="Leave blank to use the free, rate-limited tier")
    st.markdown('<div style="font-family:\'DM Mono\',monospace;font-size:0.62rem;color:#55708f;">'
                '🔗 <a href="https://www.semanticscholar.org/product/api" target="_blank" style="color:#0066cc;">'
                'Get key → semanticscholar.org/product/api</a></div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("##### Model Provider")
    # Model selector (2026-08-23): NVIDIA stays the default -- selecting it
    # changes nothing about existing behavior. The other three read their
    # key straight from .env (OPENAI_API_KEY/GEMINI_API_KEY/DASHSCOPE_API_KEY),
    # same convention as ARCADEDB_*/POSTGRES_* -- no sidebar re-entry, since
    # these aren't the primary always-visible credential the NVIDIA field is.
    _provider_keys = list(PROVIDER_REGISTRY.keys())
    selected_provider_key = st.selectbox(
        "Provider", options=_provider_keys,
        index=_provider_keys.index(DEFAULT_PROVIDER_KEY),
        format_func=lambda k: PROVIDER_REGISTRY[k].label,
        help="NVIDIA NIM is the current default. The others are structurally "
             "wired in but unverified against the real service this session "
             "-- see utils/model_providers.py's own docstring.",
    )
    _selected_cfg = PROVIDER_REGISTRY[selected_provider_key]
    if not _selected_cfg.verified_live:
        st.caption(f"⚠️ {_selected_cfg.label} is not yet live-verified in this app.")

    _model_options = list(_selected_cfg.known_models) + ["Custom…"]
    _model_choice = st.selectbox("Model", options=_model_options, index=0)
    selected_model = (
        st.text_input("Custom model ID", value=_selected_cfg.default_model)
        if _model_choice == "Custom…" else _model_choice
    )

    if selected_provider_key == "nvidia":
        provider_api_key = api_key
    else:
        provider_api_key = os.environ.get(_selected_cfg.api_key_env, "").strip()
        if not provider_api_key:
            st.caption(f"⚠️ No key found -- add {_selected_cfg.api_key_env} to .env to use {_selected_cfg.label}.")

    st.markdown("---")

    # Domain
    st.markdown("##### Research Domain")
    opts         = get_domain_display_options()
    default_idx  = next((i for i, d in enumerate(opts) if "Healthcare" in d), 0)
    sel_display  = st.selectbox("Select Domain", opts, index=default_idx)
    selected_domain = parse_domain_selection(sel_display)
    domain_cfg   = get_domain_config(selected_domain)

    st.markdown(f"""
    <div style="background:#edf6ff;border:1px solid #7ab8f5;border-radius:6px;
                padding:0.7rem 0.9rem;margin-top:0.3rem;">
      <div style="font-size:0.78rem;color:#0b1f3a;">{domain_cfg['description']}</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("##### Research Context")
    interest = st.text_area("Your Specific Interest",
                             placeholder=f"e.g., {domain_cfg.get('gap_examples','')[:80]}...",
                             height=70)
    gap_type = st.selectbox("Gap Type Focus",
                             ["Any","Methodology","Application","Dataset",
                              "Evaluation","Theory","Benchmark"])

    st.markdown("---")
    st.markdown("##### Options")
    use_vision = st.checkbox("🖼️ Vision (figures/tables)", value=False)
    extract_refs = st.checkbox("📚 Extract & enrich references (50+ papers)", value=True,
                               help="Parse cited papers, query Semantic Scholar for abstracts.")
    ref_limit = st.selectbox("Reference limit per paper",
                             ["25", "50", "100", "All"],
                             index=1,
                             help="Higher limits take longer but improve reference coverage.")
    show_prompts = st.checkbox("🔍 Show prompts (explainability)", value=False)
    n_council_runs = st.select_slider("🔄 Council runs", options=[1,2,3], value=2,
                                       help="Run insight council N times and merge findings.")

    enable_quality_engine = st.checkbox(
        "🔬 Corpus Quality Engine (multi-parser + gate)", value=False,
        help="Cross-checks each paper with a second parser (Docling) and canonically "
             "resolves references before gap analysis runs. Adds ~90s per NEW paper "
             "(cached after the first run on that paper). Blocks the run if quality is "
             "too low unless you check the override below.")
    override_quality_gate = False
    if enable_quality_engine:
        override_quality_gate = st.checkbox(
            "⚠️ Proceed even if the quality gate is FAIL", value=False,
            help="A FAIL gate blocks the run by default (Clinova Phase 1, Story 1.2.3). "
                 "Check this to proceed anyway -- the DEGRADED/FAIL provenance still "
                 "propagates into the results either way.")

    enable_gap_challenger = st.checkbox(
        "🥊 Gap Challenger (rich status + search coverage)", value=False,
        help="Clinova Phase 3, Epic 3.4. Replaces the plain open/partial/solved "
             "validation with the full 6-status lifecycle (INSUFFICIENT_EVIDENCE / "
             "OPEN / PARTIALLY_OPEN / CONTESTED / LIKELY_CLOSED / CLOSED), assigned "
             "deterministically from a measured Search Coverage Score -- a technically-"
             "empty search can never silently resolve to OPEN. Runs an extra search + "
             "LLM judgment per gap on top of the existing validation, adding real time "
             "(~30s+ per gap, live-measured) -- opt-in for that reason.")

    enable_graph_persistence = st.checkbox(
        "🗄️ Persist graph to ArcadeDB (cross-run graph history)", value=False,
        help="Clinova Phase 3, Epic 3.1. Saves this run's knowledge graph to a local "
             "ArcadeDB server so it can be compared against other runs later (which "
             "entities/relationships are new, which persist across analyses). Requires "
             "ArcadeDB running locally first -- see RESUME.md for setup. If the server "
             "isn't reachable, the run still completes normally; only the graph save is "
             "skipped, with a warning.")

    st.markdown("---")

    # ── Run History ────────────────────────────────────────────────────────────
    st.markdown("##### 🕑 Run History")
    runs = list_runs(limit=10)
    if not runs:
        st.markdown('<div style="font-family:\'DM Mono\',monospace;font-size:0.72rem;'
                    'color:#55708f;">No saved runs yet.</div>', unsafe_allow_html=True)
    else:
        for run in runs:
            ts_short = run["created_at"][:16].replace("T", " ")
            comp_dot = " 🧬" if run["has_comp"] else ""
            if st.button(
                f"📄 {run['name'][:22]}{comp_dot}",
                key=f"load_{run['id']}",
                help=f"{ts_short} · {run['domain']} · {run['n_papers']} papers · {run['n_gaps']} gaps",
            ):
                loaded = load_run(run["id"])
                if loaded.get("results"):
                    st.session_state.results      = loaded["results"]
                    st.session_state.comp_results = loaded.get("comp_results")
                    st.session_state.ref_papers   = loaded["results"].get("ref_papers", [])
                    st.session_state.ref_diagnostics = loaded["results"].get("ref_diagnostics", {})
                    st.session_state.corpus       = loaded["results"].get("corpus", loaded["results"].get("papers", []))
                    st.session_state.loaded_run_id = run["id"]
                    st.session_state.current_run_id = run["id"]
                    st.session_state.current_run_name = run["name"]
                    st.rerun()

            st.markdown(
                f'<div style="font-family:\'DM Mono\',monospace;font-size:0.62rem;'
                f'color:#55708f;margin-top:-0.5rem;margin-bottom:0.4rem;padding-left:0.2rem;">'
                f'{ts_short} · {run["n_papers"]}p · {run["n_gaps"]}g</div>',
                unsafe_allow_html=True,
            )

    if runs:
        # Clinova Phase 3, Epic 3.6: makes pipeline/repeatability_score.py
        # actually usable from the app, not just a standalone tested
        # module -- select 2+ saved runs (from repeated analyses of the
        # SAME corpus/context; this function can't verify that from gap
        # lists alone, so picking unrelated runs will just produce a low,
        # honestly-meaningless score, not an error) and see how stable
        # the gap output was across them.
        with st.expander("🔁 Repeatability Check (compare saved runs)"):
            run_options = {f"{r['name'][:30]} ({r['id'][:8]}, {r['n_gaps']}g)": r["id"] for r in runs}
            selected_labels = st.multiselect(
                "Pick 2+ runs from repeated analyses of the same corpus/context",
                options=list(run_options.keys()),
                key="repeatability_run_select",
            )
            if st.button("Compute Repeatability Score", key="compute_repeatability",
                         disabled=len(selected_labels) < 2):
                selected_ids = [run_options[lbl] for lbl in selected_labels]
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

        # Clinova Phase 3, Epic 3.1 -- browses graphs persisted to
        # ArcadeDB (opt-in "Persist graph to ArcadeDB" toggle above, per
        # run). A separate list from Run History above: only runs saved
        # WITH that toggle checked appear here, and ArcadeDB must be
        # reachable right now for this panel to show anything but a
        # clear "not connected" message.
        with st.expander("🗄️ Graph History (ArcadeDB, cross-run diff)"):
            ok, msg = arcadedb_connect_ok()
            if not ok:
                st.caption(f"Not connected -- {msg}")
            else:
                try:
                    graph_runs = list_graph_snapshots()
                except Exception as e:
                    graph_runs = []
                    st.error(f"Could not list saved graphs: {e}")
                if not graph_runs:
                    st.caption("No graphs persisted yet -- check the toggle above and run an analysis.")
                else:
                    graph_options = {
                        f"{g['name'][:30]} ({g['run_id'][:8]}, {g['entity_count']}e/{g['relationship_count']}r"
                        + (f", {g['build_status']} {g['quality_score']:.2f})" if g.get("build_status") else ")"): g["run_id"]
                        for g in graph_runs
                    }
                    selected_graph_labels = st.multiselect(
                        "Pick exactly 2 persisted graphs to diff",
                        options=list(graph_options.keys()),
                        key="graph_diff_select",
                    )
                    if st.button("Diff Graphs", key="diff_graphs",
                                 disabled=len(selected_graph_labels) != 2):
                        id_a, id_b = [graph_options[lbl] for lbl in selected_graph_labels]
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
                            if diff["entities_only_in_a"]:
                                st.markdown("")
                                _section_label(f"Entities only in {id_a[:8]}")
                                for name_ in diff["entities_only_in_a"][:15]:
                                    _item(f"🔹 {name_}")
                            if diff["entities_only_in_b"]:
                                st.markdown("")
                                _section_label(f"Entities only in {id_b[:8]}")
                                for name_ in diff["entities_only_in_b"][:15]:
                                    _item(f"🔹 {name_}")
                        except Exception as e:
                            st.error(f"Diff failed: {e}")

        # Clinova Phase 4, Epic 4.4's motivating slice (FR-28) -- unlike
        # Repeatability Check (aggregate stability metrics across N runs)
        # or Graph History (ArcadeDB-persisted graphs only), this diffs
        # any two saved runs directly, in full: papers, evidence counts,
        # graph entities/relationships, gaps (with confidence changes),
        # proposals, and the model/pipeline-version each run actually
        # used -- the real answer to "did switching models change the
        # result," not just a guess. Reads only already-saved data
        # (pipeline/run_compare.py), no new LLM calls.
        with st.expander("🔀 Compare Runs (what changed between two runs)"):
            compare_options = {f"{r['name'][:30]} ({r['id'][:8]}, {r['n_gaps']}g)": r["id"] for r in runs}
            compare_labels = st.multiselect(
                "Pick exactly 2 saved runs to compare",
                options=list(compare_options.keys()),
                key="compare_runs_select",
            )
            if st.button("Compare Runs", key="compare_runs_button",
                         disabled=len(compare_labels) != 2):
                id_a, id_b = [compare_options[lbl] for lbl in compare_labels]
                try:
                    cmp = compare_runs(id_a, id_b)
                    m = cmp["manifest"]
                    st.markdown(
                        f"**Model:** `{m['model_bundle_version_a'] or 'unknown'}` → "
                        f"`{m['model_bundle_version_b'] or 'unknown'}`  \n"
                        f"**Duration:** {m['run_duration_seconds_a'] or '?'}s → "
                        f"{m['run_duration_seconds_b'] or '?'}s  \n"
                        f"**Quality gate:** {m['quality_gate_results_a'] or 'unknown'} → "
                        f"{m['quality_gate_results_b'] or 'unknown'}"
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
                        _section_label(f"New gaps in {id_b[:8]}")
                        for t in gp["added"][:15]:
                            _item(f"🆕 {t}")
                    if gp["removed"]:
                        st.markdown("")
                        _section_label(f"Gaps no longer generated (present in {id_a[:8]} only)")
                        for t in gp["removed"][:15]:
                            _item(f"➖ {t}")
                    if gp["confidence_changes"]:
                        st.markdown("")
                        _section_label("Confidence changes")
                        for c in gp["confidence_changes"][:15]:
                            _item(f"🔀 {c['title']}: {c['confidence_a']} → {c['confidence_b']}")
                except ValueError as e:
                    st.error(str(e))

        # Clinova Phase 4, Epic 4.4 (FR-24) -- Technical lineage is a real
        # query over research_artifacts.parent_artifact (Epic 4.1's
        # registry, now populated per-stage instead of one row per run);
        # Scientific lineage is a pure in-memory join over one run's
        # already-saved results, tracing each gap back to the real
        # graph relationships/evidence objects that motivated it.
        with st.expander("🧬 Lineage (technical + scientific)"):
            lineage_options = {f"{r['name'][:30]} ({r['id'][:8]}, {r['n_gaps']}g)": r["id"] for r in runs}
            lineage_label = st.selectbox(
                "Pick a saved run", options=list(lineage_options.keys()),
                key="lineage_run_select",
            )
            if st.button("Show Lineage", key="lineage_button") and lineage_label:
                run_id = lineage_options[lineage_label]
                try:
                    tech = get_technical_lineage(run_id)
                    _section_label("Technical lineage (artifact chain)")
                    if tech["root"] is None:
                        st.caption("No artifact chain recorded for this run (predates Epic 4.4).")
                    else:
                        by_id = {n["artifact_id"]: n for n in tech["nodes"]}
                        for e in tech["edges"]:
                            child = by_id.get(e["child"], {})
                            _item(f"🔗 {e['parent']} → {e['child']} ({child.get('artifact_type','?')})")
                        if tech["fan_in_edges"]:
                            st.caption(f"{len(tech['fan_in_edges'])} fan-in edge(s) "
                                       f"(e.g. N papers → 1 evidence set)")
                        if tech["orphans"]:
                            st.warning(f"⚠️ {len(tech['orphans'])} artifact(s) with an unresolved parent.")

                    sci = get_scientific_lineage(run_id)
                    st.markdown("")
                    _section_label("Scientific lineage (per-gap chain)")
                    if not sci["gaps"] and not sci["n_gaps_without_identity"]:
                        st.caption("No gaps recorded for this run.")
                    if sci["n_gaps_without_identity"]:
                        st.caption(f"{sci['n_gaps_without_identity']} gap(s) on this run have no real gap_id "
                                   f"(predates Epic 4.4's identity fields) and are excluded below.")
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

        if st.button("🗑 Clear all history", key="clear_history"):
            for r in runs:
                delete_run(r["id"])
            st.rerun()

# ── Main header ───────────────────────────────────────────────────────────────
st.markdown(f'<div class="main-header">{html.escape(_BRANDING["product_name"])}</div>', unsafe_allow_html=True)

# Show loaded run banner
if st.session_state.loaded_run_id:
    runs_meta = {r["id"]: r for r in list_runs()}
    run_meta  = runs_meta.get(st.session_state.loaded_run_id, {})
    st.markdown(f"""
    <div style="background:#fff7e6;border:1px solid #f0c36a;border-radius:8px;
                padding:0.7rem 1.2rem;margin-bottom:0.5rem;">
      <span style="font-family:'DM Mono',monospace;font-size:0.68rem;color:#b7791f;">
        📂 Showing saved run: <strong>{run_meta.get('name','')}</strong>
        — {run_meta.get('created_at','')[:16].replace('T',' ')}
      </span>
      <span style="font-size:0.75rem;color:#55708f;margin-left:1rem;">
        Upload new papers above to run a fresh analysis</span>
    </div>""", unsafe_allow_html=True)

st.markdown('<div class="sub-header">Upload papers → AI discovers what the field hasn\'t found yet</div>',
            unsafe_allow_html=True)

uploaded_files = st.file_uploader(
    "Upload up to 5 research papers (PDF)",
    type=["pdf"], accept_multiple_files=True,
)
if uploaded_files and len(uploaded_files) > 5:
    st.warning("Maximum 5 papers. Only first 5 will be processed.")
    uploaded_files = uploaded_files[:5]

if uploaded_files:
    cols = st.columns(min(len(uploaded_files), 5))
    for i, (col, f) in enumerate(zip(cols, uploaded_files)):
        with col:
            st.markdown(
                f'<div class="stage-card" style="text-align:center;padding:0.8rem;">'
                f'<div class="stage-title">{_tier_badge(1)} Paper {i+1}</div>'
                f'<div class="stage-body" style="font-size:0.78rem;word-break:break-word;">{f.name}</div>'
                f'<div style="font-family:\'DM Mono\',monospace;font-size:0.65rem;color:#55708f;">'
                f'{len(f.getvalue())//1024} KB</div></div>',
                unsafe_allow_html=True)

st.markdown("")
run_col, name_col, _ = st.columns([1, 2, 1])
with run_col:
    run_btn = st.button("🚀 Run Analysis", disabled=st.session_state.running)
with name_col:
    run_name = st.text_input("Run name (for history)", value="", placeholder="e.g., Diabetes AI review",
                              label_visibility="collapsed")

# ── Main Pipeline ─────────────────────────────────────────────────────────────
if run_btn and uploaded_files:
    # provider_api_key == api_key when NVIDIA (the default) is selected --
    # this one check correctly covers both "no NVIDIA key entered" and "no
    # key configured for the selected non-NVIDIA provider," rather than two
    # separate checks that could disagree.
    if not provider_api_key:
        st.error(f"No API key configured for {_selected_cfg.label}. "
                 + (f"Add {_selected_cfg.api_key_env} to .env, or switch the sidebar's "
                    "Model Provider back to NVIDIA."
                    if selected_provider_key != "nvidia" else "Please enter your NVIDIA API key."))
        st.stop()
    if len(uploaded_files) < 2:
        st.warning("Upload at least 2 papers.")
        st.stop()

    st.session_state.running        = True
    st.session_state.pipeline_trace = []
    st.session_state.loaded_run_id  = None

    # Clinova Phase 4, Epic 4.3 token instrumentation (2026-08-24): real,
    # not fabricated -- see utils/token_meter.py. Wired into every real
    # pipeline run so run_manifests.token_usage gets its first non-NULL
    # values, per provider/model support (a provider that rejects
    # stream_options degrades honestly to no usage capture, never an
    # estimate).
    token_meter = TokenMeter()
    client  = build_client(selected_provider_key, provider_api_key, model=selected_model, token_meter=token_meter)
    context = {
        "domain":   selected_domain,
        "interest": interest or "General research",
        "gap_type": gap_type,
    }
    name = run_name.strip() or f"{selected_domain[:20]} — {datetime.now().strftime('%H:%M')}"

    # Clinova Phase 4, Epic 4.2 -- real wall-clock start, used for
    # RunManifest.run_duration_seconds below.
    _run_start_time = time.time()

    prog = st.progress(0)
    stat = st.empty()
    def upd(msg, pct):
        prog.progress(pct)
        stat.markdown(_card("Pipeline Running", f"⟳ {msg}"), unsafe_allow_html=True)

    try:
        all_papers, all_trees = [], []

        # Stage 1+2: Parse + PageIndex
        upd("Stage 1 — Parsing PDFs & building PageIndex trees…", 5)
        # Clinova Phase 1: when the Corpus Quality Engine is enabled, Stage
        # 2B below needs each paper's original PDF file (Docling operates
        # on the file, not the already-extracted text) -- keep the temp
        # files alive until Stage 2B runs instead of deleting them here.
        paper_tmp_paths = []
        for uf in uploaded_files:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(uf.getvalue()); tmp_path = tmp.name
            paper = parse_pdf(tmp_path, uf.name,
                              client=client if use_vision else None,
                              use_vision=use_vision)
            paper["tier"] = 1
            all_papers.append(paper)
            all_trees.append(build_tree(paper))
            if enable_quality_engine:
                paper_tmp_paths.append(tmp_path)
            else:
                os.unlink(tmp_path)

        _add_trace("Stage 1 — PDF Parse",
                   f"{len(uploaded_files)} PDFs",
                   f"{sum(p.get('char_count',0) for p in all_papers):,} chars extracted")
        prog.progress(12)

        # Stage 1B: Reference extraction (optional)
        ref_papers = []
        ref_diagnostics = {}
        ref_resolution_diagnostics = None
        if extract_refs:
            upd("Stage 1B — Extracting & enriching references (50+ paper corpus)…", 14)
            limit_value = None if ref_limit == "All" else int(ref_limit)
            def ref_upd(_current, _total, msg):
                upd(f"Stage 1B — {msg}", 14)
            ref_papers, ref_diagnostics = extract_and_enrich_references(
                all_papers,
                client,
                max_refs_per_paper=limit_value,
                progress_callback=ref_upd,
                return_diagnostics=True,
            )
            st.session_state.ref_papers = ref_papers
            st.session_state.ref_diagnostics = ref_diagnostics
            summary = summarise_reference_corpus(ref_papers)
            _add_trace("Stage 1B — Reference Extraction",
                       f"{len(uploaded_files)} PDFs scanned",
                       f"{summary['total']} refs from {ref_diagnostics.get('raw_entries',0)} raw entries: "
                       f"{summary['tier2_abstract']} with abstract, {summary['tier3_title']} title-only")

            # Stage 1C: Canonical reference resolution + filtering
            # (Clinova Phase 1, Story 1.3.3 -- default-safe corpus
            # filtering, opt-in via the same Corpus Quality Engine toggle).
            # Only VERIFIED/ACCEPTED references (a real DOI/PMID/OpenAlex-
            # ID/SS-ID match, or a full title+author+year match) feed the
            # rest of the pipeline; QUARANTINED (title-only partial match)
            # and UNRESOLVED references are dropped from what downstream
            # stages see, but counted in ref_resolution_diagnostics --
            # never silently discarded without a trace.
            if enable_quality_engine and ref_papers:
                upd("Stage 1C — Canonical reference resolution…", 21)
                trusted_refs, ref_resolution_diagnostics = filter_and_dedupe_references(ref_papers)
                ref_papers = trusted_refs
                st.session_state.ref_papers = ref_papers
                st.session_state.ref_resolution_diagnostics = ref_resolution_diagnostics
                sc = ref_resolution_diagnostics["status_counts"]
                _add_trace(
                    "Stage 1C — Reference Resolution",
                    f"{ref_resolution_diagnostics['input_count']} enriched refs",
                    f"{ref_resolution_diagnostics['trusted_count']} trusted "
                    f"(VERIFIED {sc['VERIFIED']}, ACCEPTED {sc['ACCEPTED']}), "
                    f"{sc['QUARANTINED']} quarantined, {sc['UNRESOLVED']} unresolved, "
                    f"{ref_resolution_diagnostics['duplicates_removed']} duplicates merged",
                )
        prog.progress(20)

        # Stage 2: Wiki
        upd("Stage 2 — Compiling LLM Wiki pages…", 22)
        client.set_stage("Stage 2 — LLM Wiki")
        wiki = build_wiki(all_papers, all_trees, client, domain_config=domain_cfg)
        _add_trace("Stage 2 — LLM Wiki",
                   f"{len(all_papers)} papers",
                   f"{len(wiki.get('pages',[]))} pages, "
                   f"{len(wiki.get('cross_links',{}).get('shared_concepts',[]))} links")
        prog.progress(34)

        # Stage 2B: Corpus Quality Engine (Clinova Phase 1, Epic 1.2, opt-in)
        # Cross-checks each paper against a second parser (Docling), scores
        # extraction completeness against the 05-data-architecture.md §4
        # field checklist, and enforces the PASS/DEGRADED/FAIL gate before
        # gap analysis is allowed to run (Story 1.2.3 / PRD FR-3).
        corpus_quality_metrics = None
        # B23 fix (2026-08-21): a FAIL gate used to raise all the way to the
        # outer except block, discarding EVERYTHING already fetched this run
        # (papers, references, wiki, evidence) with nothing saved -- a user
        # whose corpus happened to score FAIL got back nothing at all, not
        # even the data that had genuinely already been gathered. Now the
        # block is caught locally: gap-analysis stages (3-6) are skipped,
        # but Stage 1-2C's fetched data is still built into a normal results
        # dict and saved, with the gate's FAIL status/reasons visible in it.
        gate_blocked = False
        gate_block_reasons = []
        wiki_pages = wiki.get("pages", [])
        # docling_results defaults to all-None (honest: no real page
        # provenance available) when the Quality Engine toggle is off --
        # Stage 2C below runs unconditionally and degrades gracefully to
        # section-only/no provenance in that case, per Story 2.1.3's design.
        docling_results = [None] * len(all_papers)
        if enable_quality_engine:
            upd("Stage 2B — Corpus Quality Engine (multi-parser cross-check)…", 35)
            paper_scores = []
            docling_results = []
            for i, (paper, tmp_path) in enumerate(zip(all_papers, paper_tmp_paths)):
                upd(f"Stage 2B — Cross-checking paper {i+1}/{len(all_papers)} with Docling…", 35)
                wiki_page = wiki_pages[i] if i < len(wiki_pages) else {}
                docling_result = None
                try:
                    docling_result = extract_with_docling(tmp_path, paper.get("filename", uploaded_files[i].name))
                    reconciled = reconcile_paper(paper, docling_result, paper.get("filename", ""))
                except Exception:
                    # A Docling failure degrades the paper's score to
                    # "nothing reconciled" rather than aborting the whole
                    # run -- consistent with this file's existing B6/B12/B17
                    # philosophy of never letting one paper's failure kill
                    # processing that could otherwise proceed. This paper's
                    # doi/tables fields will score not-extracted/empty
                    # below, which correctly lowers its completeness score
                    # rather than silently pretending nothing was lost.
                    reconciled = {"fields": {}}
                docling_results.append(docling_result)
                score = score_paper_completeness(
                    reconciled, wiki_page,
                    ref_count=len(ref_papers), has_figures=bool(paper.get("figures")),
                )
                paper_scores.append(score)

            corpus_quality_metrics = compute_corpus_quality(
                paper_scores, ref_diagnostics, ref_papers=ref_papers,
            )
            try:
                corpus_quality_metrics = enforce_quality_gate(
                    corpus_quality_metrics,
                    override=override_quality_gate,
                    override_reason="user-checked override in sidebar" if override_quality_gate else "",
                    override_by="streamlit_user",
                )
            except QualityGateBlockedError as e:
                # B23 fix: previously re-raised here, which discarded every
                # paper/reference/wiki page already fetched this run -- now
                # caught locally so that data is still saved. Stage 3-6
                # (knowledge graph / gap detection / validation / proposals)
                # are skipped below since running gap analysis against a
                # FAIL-gated corpus would violate PRD FR-3; only that
                # gap-analysis output is empty, not the whole run.
                gate_blocked = True
                gate_block_reasons = e.reasons
                # Temp-file cleanup happens unconditionally a few lines below
                # (runs whether or not the gate blocked) -- no need to repeat it here.

            _add_trace(
                "Stage 2B — Corpus Quality Engine",
                f"{len(all_papers)} papers, {len(ref_papers)} refs",
                f"{corpus_quality_metrics['extraction_completeness']:.0%} extraction completeness, "
                f"{corpus_quality_metrics['doi_resolution_rate']:.0%} DOI resolution, "
                f"gate={corpus_quality_metrics['quality_gate']}",
            )

        for p in paper_tmp_paths:
            try:
                os.unlink(p)
            except OSError:
                pass

        # Stage 2C: Evidence Extraction (Clinova Phase 2, Epic 2.1/2.2).
        # Runs on EVERY run, independent of the Quality Engine toggle
        # (2026-08-21 fix -- previously tied to it unnecessarily): 6 of 13
        # evidence types are deterministic (zero LLM/Docling cost, derived
        # from the wiki page alone), so gating the whole stage behind
        # Docling's ~90s/paper cost meant users paid nothing to get nothing
        # unless they also opted into the heavier corpus-quality cross-
        # check. The other 7 types cost one small scoped LLM call per
        # paper (max_tokens=1500) -- cheap relative to the wiki/graph/gap
        # calls already made on every run regardless. Real page-level
        # provenance still depends on Stage 2B having run (docling_results
        # is honestly all-None otherwise, per Story 2.1.3's design) --
        # only the PROVENANCE QUALITY is gated by the toggle, not whether
        # evidence gets extracted at all.
        upd("Stage 2C — Extracting evidence objects…", 35)
        evidence_objects = {}
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
                # Same never-let-one-paper-kill-the-run philosophy as the
                # Docling cross-check above -- evidence extraction is
                # additive, not load-bearing for the rest of the run.
                evidence_dicts = []
            evidence_objects[filename] = evidence_dicts
            total_evidence += len(evidence_dicts)

        _add_trace(
            "Stage 2C — Evidence Extraction",
            f"{len(all_papers)} papers",
            f"{total_evidence} evidence objects extracted "
            f"({'with' if enable_quality_engine else 'without'} Docling page provenance)",
        )

        if not gate_blocked:
            # Stage 3: Knowledge Graph
            upd("Stage 3 — Building knowledge graph (LazyGraphRAG)…", 36)
            client.set_stage("Stage 3 — Knowledge Graph")
            graph = build_knowledge_graph(wiki, client, domain_config=domain_cfg,
                                          evidence_objects=evidence_objects)
            # Clinova Phase 3, Epic 3.1 (FR-7): every graph build is scored,
            # not just counted -- build_status/quality_score feed into the
            # gap confidence downgrade below (real success criterion: "a
            # degraded graph provably reduces the confidence of any gap
            # conclusion derived from it").
            graph_quality = score_graph_quality(graph, wiki)
            _add_trace("Stage 3 — Knowledge Graph",
                       "Wiki pages + cross-links",
                       f"{graph['stats']['entity_count']} entities, "
                       f"{graph['stats']['relationship_count']} relationships "
                       f"— {graph_quality['build_status']} "
                       f"(quality={graph_quality['quality_score']})")
            prog.progress(48)

            # Stage 4+5: Gaps + Validation
            upd("Stage 4 — Detecting research gaps…", 50)
            client.set_stage("Stage 4 — Gap Detection")
            gaps = detect_gaps(wiki, graph, context, client, domain_config=domain_cfg,
                               evidence_objects=evidence_objects)
            # Clinova Phase 3, Epic 3.2 (Hybrid Gap Engine): the deterministic
            # pattern library is a second, independent candidate-gap source,
            # evaluated directly against this run's real Evidence Objects
            # (Stage 2C) -- no LLM call, and additive to the existing
            # LLM-only detect_gaps() above, not a replacement for it. Every
            # gap from either source now carries a `source` tag (semantic vs
            # deterministic) per 04-ai-research-architecture.md §4's
            # provenance requirement. No-op outside Healthcare AI today (the
            # pattern library is domain-specific, per its own module docstring).
            det_gaps = detect_deterministic_gaps(evidence_objects, context.get("domain", ""))
            # Graph-structural signal (source 2 of 3): queries the local
            # entity/relationship graph Stage 3 just built above -- no Neo4j,
            # no LLM call, domain-agnostic (unlike the pattern library).
            # Neo4j itself (the "primary new infra" 10-phased-implementation-
            # plan.md names for Phase 3) is deferred pending Docker/admin
            # access on this machine; querying the graph structurally does
            # not actually require it, since a real graph is already built
            # for every run today.
            graph_gaps = detect_graph_structural_gaps(graph)
            gaps = gaps + det_gaps + graph_gaps
            # FR-7's success criterion, made real: a DEGRADED/FALLBACK graph
            # build downgrades confidence for gaps whose entire evidentiary
            # basis is that graph (source == "graph_structural") -- not
            # silently treated as equal-quality to a clean build.
            gaps = apply_graph_quality_to_gaps(gaps, graph_quality)
            upd("Stage 5 — Validating gaps (Semantic Scholar + arXiv)…", 58)
            client.set_stage("Stage 5 — Gap Validation")
            validated_gaps = validate_gaps(gaps, client, domain_config=domain_cfg, ss_api_key=ss_api_key.strip())
            _add_trace("Stage 4-5 — Gaps",
                       "Wiki + graph + domain context"
                       + (f" + {len(det_gaps)} deterministic-pattern candidates" if det_gaps else "")
                       + (f" + {len(graph_gaps)} graph-structural candidates" if graph_gaps else ""),
                       f"{len(validated_gaps)} gaps: "
                       f"{sum(1 for g in validated_gaps if g.get('validation_status')=='open')} open")
            prog.progress(66)

            # Stage 5b: Gap Challenger (Clinova Phase 3, Epic 3.4, opt-in --
            # additive enrichment on top of Stage 5's existing open/partial/
            # solved validation, not a replacement for it). Each gap gets
            # `challenger_state`/`challenger_status`/`challenge_funnel` keys
            # merged in; a per-gap failure degrades that one gap to no
            # enrichment rather than aborting the run, matching this file's
            # existing per-paper-failure-isolation philosophy elsewhere.
            if enable_gap_challenger:
                upd("Stage 5b — Gap Challenger (search coverage + terminal status)…", 62)
                client.set_stage("Stage 5b — Gap Challenger")
                for i, gap in enumerate(validated_gaps):
                    upd(f"Stage 5b — Challenging gap {i+1}/{len(validated_gaps)}…", 62)
                    try:
                        challenge = run_challenge(
                            gap, client, ss_api_key=ss_api_key.strip(), domain_config=domain_cfg,
                        )
                        gap.update(challenge)
                    except Exception as e:
                        gap["challenger_state"] = None
                        gap["challenger_status"] = None
                        gap["challenger_error"] = str(e)
                statuses = [g.get("challenger_status") for g in validated_gaps if g.get("challenger_status")]
                status_counts = {s: statuses.count(s) for s in sorted(set(statuses))}
                _add_trace(
                    "Stage 5b — Gap Challenger",
                    f"{len(validated_gaps)} gaps",
                    ", ".join(f"{v} {k}" for k, v in status_counts.items()) or "no gaps reached a terminal status",
                )

            # Stage 6: Proposals
            upd("Stage 6 — Generating proposals…", 68)
            client.set_stage("Stage 6 — Proposals")
            proposals = generate_proposals(validated_gaps, wiki, context, client,
                                           domain_config=domain_cfg)
            _add_trace("Stage 6 — Proposals", f"{len(validated_gaps)} gaps",
                       f"{len(proposals)} proposals")
            prog.progress(75)
        else:
            # B23 fix: gate-blocked runs skip gap analysis entirely (PRD
            # FR-3 -- must not analyze a FAIL-gated corpus) but still reach
            # this point with real fetched data to save below.
            upd("Quality gate FAILED — skipping gap analysis, saving fetched data…", 68)
            graph = {"stats": {"entity_count": 0, "relationship_count": 0}, "communities": []}
            graph_quality = None
            validated_gaps = []
            proposals = []
            _add_trace("Stage 3-6 — Skipped (quality gate FAIL)",
                       f"{len(all_papers)} papers, {len(ref_papers)} refs",
                       "; ".join(gate_block_reasons) or "corpus below quality threshold")
            prog.progress(75)

        # Build full corpus
        corpus = assign_tiers(all_papers, ref_papers)
        st.session_state.corpus = corpus

        # Store results
        results = {
            "papers": [
                {"filename": p["filename"], "wiki": w,
                 "char_count": p.get("char_count",0),
                 "sections": p.get("sections",{}),
                 "tables": p.get("tables",[]),
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
            "pipeline_trace": st.session_state.pipeline_trace,
            # B23 fix: surfaced so the Results view can explain why gaps/
            # proposals are empty on a gate-blocked run, distinct from a
            # genuinely gap-free corpus.
            "gate_blocked": gate_blocked,
            "gate_block_reasons": gate_block_reasons,
        }
        st.session_state.results = results

        # Auto-save to database -- happens regardless of gate_blocked, so a
        # FAIL-gated run's fetched papers/references/wiki/evidence are never
        # lost (B23 fix).
        saved_id = save_run(name, results)
        st.session_state.loaded_run_id = None  # fresh run, not a loaded one
        st.session_state.current_run_id = saved_id
        st.session_state.current_run_name = name

        # Clinova Phase 3, Epic 3.1 (opt-in) -- persists this run's graph to
        # ArcadeDB so it can be compared against other runs later. Skipped
        # (not attempted) when gate_blocked, since that path's graph is an
        # empty placeholder with nothing real to persist. A failure here
        # (most commonly: ArcadeDB isn't running) degrades to a warning,
        # never blocks the already-successful run from completing.
        if enable_graph_persistence and not gate_blocked:
            ok, msg = arcadedb_connect_ok()
            if ok:
                try:
                    gsummary = save_graph_snapshot(saved_id, name, graph, quality=graph_quality)
                    _add_trace(
                        "Graph Persistence (ArcadeDB)",
                        f"{gsummary['entity_count']} entities, {gsummary['relationship_count']} relationships",
                        f"Saved under run_id={saved_id[:8]}…",
                    )
                except Exception as e:
                    st.warning(f"⚠️ Graph persistence failed (run itself completed normally): {e}")
            else:
                st.warning(f"⚠️ Graph not persisted -- {msg}")

        # Clinova Phase 4, Epic 4.1/4.2 -- records this run as a
        # ResearchArtifact (artifact_type="pipeline") and its full
        # RunManifest (FR-22/FR-23). Always attempted, gate-blocked runs
        # included -- a FAIL-gated run is itself a real, worth-recording
        # research event, not a non-event. Failure here degrades to a
        # warning, same convention as graph persistence above -- the run
        # itself has already completed and saved successfully by this
        # point, so a registry-write failure must never look like the run
        # failed.
        lineage = {"artifact_ids": []}
        try:
            record_artifact(
                artifact_id=f"pipeline:{saved_id}", artifact_type="pipeline",
                artifact_version=f"pipeline:{saved_id}",
                project_id=context.get("domain") or "default",
                content_hash=saved_id, run_id=saved_id,
            )
            # Clinova Phase 4, Epic 4.4 (FR-24) -- writes the Technical
            # Lineage spine (corpus -> paper_extraction -> evidence_set ->
            # graph -> gap_set -> proposal_set) so the future Lineage view
            # has real per-stage artifacts to walk, not just the one
            # pipeline-level row above. Gate-blocked runs truncate the
            # spine after evidence_set (see pipeline/lineage.py).
            lineage = record_run_lineage(
                run_id=saved_id,
                project_id=context.get("domain") or "default",
                papers=all_papers, wiki=wiki, ref_papers=ref_papers,
                evidence_objects=evidence_objects,
                graph=None if gate_blocked else graph,
                gaps=None if gate_blocked else validated_gaps,
                proposals=None if gate_blocked else proposals,
                tooling={
                    "graph_builder": str(GRAPH_PERSISTENCE_VERSION) if enable_graph_persistence else None,
                    "embedding_model": EMBEDDING_MODEL if enable_gap_challenger else None,
                    "model_bundle": f"{selected_provider_key}:{selected_model}",
                },
                gate_blocked=gate_blocked,
            )
            record_run_manifest(
                run_id=saved_id,
                project_id=context.get("domain") or "default",
                git_commit=_GIT_COMMIT,
                parser_versions={
                    "pymupdf": None,  # no formal version constant exists for this stage yet
                    "docling": DOCLING_STAGE_VERSION if enable_quality_engine else None,
                },
                reference_resolver_version=str(REFERENCE_STAGE_VERSION),
                # Clinova model selector (2026-08-23): the real provider:model
                # this run actually used -- was always None before this
                # feature existed, since only one model was ever in play.
                model_bundle_version=f"{selected_provider_key}:{selected_model}",
                embedding_model_version=EMBEDDING_MODEL if enable_gap_challenger else None,
                reranker_version=RERANK_MODEL if enable_gap_challenger else None,
                graph_version=str(GRAPH_PERSISTENCE_VERSION) if enable_graph_persistence else None,
                search_strategy_version=str(GAP_CHALLENGER_STAGE_VERSION) if enable_gap_challenger else None,
                academic_search_date=datetime.now().date().isoformat(),
                search_providers=["semantic_scholar", "arxiv"],
                # Now real: the Technical Lineage spine's artifact ids
                # (Epic 4.4), not a fabricated reference.
                output_artifacts=lineage["artifact_ids"],
                warnings=gate_block_reasons if gate_blocked else [],
                quality_gate_results={
                    "corpus": corpus_quality_metrics.get("quality_gate") if corpus_quality_metrics else None,
                    "graph": graph_quality.get("build_status") if graph_quality else None,
                },
                run_duration_seconds=round(time.time() - _run_start_time, 1),
                # Clinova Phase 4, Epic 4.3 token instrumentation
                # (2026-08-24): real when the provider supports
                # stream_options and at least one call's usage was
                # captured; None (not a fabricated 0) otherwise -- see
                # utils/token_meter.py::to_manifest_dict().
                token_usage=token_meter.to_manifest_dict(),
            )
        except Exception as e:
            st.warning(f"⚠️ Run Manifest not recorded (run itself completed normally): {e}")

        prog.progress(80)
        prog.empty(); stat.empty()
        if gate_blocked:
            st.warning(
                f"⚠️ Quality gate FAILED — gap analysis skipped: {'; '.join(gate_block_reasons)}. "
                f"Fetched data ({len(all_papers)} papers, {len(ref_papers)} refs, "
                f"{total_evidence} evidence objects) was saved as '{name}' ({saved_id[:8]}…). "
                "Re-run with the sidebar override checked to force gap analysis anyway."
            )
        else:
            st.success(f"✅ Done — {len(validated_gaps)} gaps, {len(proposals)} proposals. "
                       f"Saved as '{name}' ({saved_id[:8]}…)")

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
        st.markdown("")

    # Summary row
    m1,m2,m3,m4,m5 = st.columns(5)
    for col,(val,lbl) in zip([m1,m2,m3,m4,m5],[
        (len(res.get("papers",[])), "Papers Analysed"),
        (graph.get("stats",{}).get("entity_count",0), "Graph Entities"),
        (graph.get("stats",{}).get("community_count",0), "Communities"),
        (len(gaps), "Gaps Found"),
        (len(proposals), "Proposals"),
    ]):
        with col:
            st.markdown(f'<div class="stat-box"><span class="stat-number">{val}</span>'
                        f'<span class="stat-label">{lbl}</span></div>', unsafe_allow_html=True)

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
                st.dataframe(pd.DataFrame(rows), use_container_width=True, height=520)
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
                import plotly.graph_objects as go, math
                n = len(nodes)
                angles = [2*math.pi*i/n for i in range(n)]
                radius = max(1, n/(2*math.pi))
                px = [radius*math.cos(a) for a in angles]
                py = [radius*math.sin(a) for a in angles]
                ex,ey = [],[]
                for e in edges:
                    si,ti = e["source_idx"],e["target_idx"]
                    if si<n and ti<n:
                        ex+=[px[si],px[ti],None]; ey+=[py[si],py[ti],None]
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=ex,y=ey,mode="lines",
                                         line=dict(width=1,color="#c9dff5"),hoverinfo="none"))
                fig.add_trace(go.Scatter(x=px,y=py,mode="markers+text",
                    text=[nd["name"][:18] for nd in nodes],textposition="top center",
                    textfont=dict(size=9,color="#0b1f3a"),
                    marker=dict(size=[nd["size"] for nd in nodes],
                                color=[nd["color"] for nd in nodes],
                                line=dict(width=1,color="#0b1f3a")),
                    hovertext=[f"{nd['name']}<br>Type: {nd['type']}" for nd in nodes],
                    hoverinfo="text"))
                fig.update_layout(showlegend=False,paper_bgcolor="#ffffff",
                    plot_bgcolor="#ffffff",font=dict(color="#0b1f3a",size=10),
                    xaxis=dict(showgrid=False,zeroline=False,showticklabels=False),
                    yaxis=dict(showgrid=False,zeroline=False,showticklabels=False),
                    height=430,margin=dict(l=10,r=10,t=30,b=10),
                    title="Knowledge Graph — Entity Network")
                st.plotly_chart(fig, use_container_width=True)
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
                st.dataframe(pd.DataFrame([{
                    "Name":e.get("name",""),"Type":e.get("type",""),
                    "Importance":e.get("importance",""),
                    "Papers":", ".join(e.get("papers",[]))[:60],
                } for e in entities]), use_container_width=True, height=260)

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
        for gap in gaps:
            status = gap.get("validation_status","pending")
            conf   = gap.get("confidence","medium")
            source = gap.get("source", "semantic")
            source_badge = _badge(source.replace("_", " ").title(), "#55708f", "#f2f5f8", "#c9dff5")
            challenger_status = gap.get("challenger_status")
            st.markdown(
                f'<div class="gap-card {status}">'
                f'<div class="gap-title">{gap.get("title","Untitled")}</div>'
                f'<div class="gap-meta">{status_badge.get(status,"")} '
                f'{_badge(conf.title()+" Conf","#004b93","#e5f2ff","#7ab8f5")} '
                f'{source_badge}'
                f'{challenger_badge.get(challenger_status, "")}</div>'
                f'<div class="gap-desc">{gap.get("description","")}</div></div>',
                unsafe_allow_html=True)
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

    # ── Tab 5: Proposals ───────────────────────────────────────────────────────
    with tab5:
        st.markdown("### Research Proposals")
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

        cr_col, ci_col = st.columns([1, 3])
        with cr_col:
            run_comp = st.button("🧬 Run Computational Lab", key="run_comp")
        with ci_col:
            st.markdown(
                '<div style="font-size:0.78rem;color:#55708f;padding-top:0.5rem;">'
                f'Stages 7–12 · Uses Tier 1 + Tier 2 params · {n_council_runs}× council runs</div>',
                unsafe_allow_html=True)
        default_lab_name = (
            st.session_state.current_run_name
            or context.get("domain")
            or f"Analysis — {datetime.now().strftime('%H:%M')}"
        )
        lab_run_name = st.text_input(
            "Computational Lab run name",
            value=f"{default_lab_name} · Computational Lab",
            key="comp_run_name",
            help="This name is used in run history after the lab output is saved.",
        )

        if run_comp:
            comp_prog = st.progress(0)
            comp_stat = st.empty()
            def cupd(msg, pct):
                comp_prog.progress(pct)
                comp_stat.markdown(_card("Computational Lab", f"⟳ {msg}"),
                                   unsafe_allow_html=True)
            try:
                client = build_client(selected_provider_key, provider_api_key, model=selected_model)

                # Stage 8A: Tier 1 parameter extraction
                papers_raw = [
                    {"sections": p.get("sections",{}), "tables": p.get("tables",[]),
                     "filename": p.get("filename","")}
                    for p in res.get("papers",[])
                ]
                cupd("Stage 8A — Extracting Tier 1 parameters…", 8)
                t1_params = extract_parameters(wiki, papers_raw, client)

                # Stage 8A-ext: Tier 2 parameters from reference abstracts
                t2_params = []
                tier2_refs = [r for r in ref_papers if r.get("tier")==2 and r.get("abstract")]
                if tier2_refs:
                    cupd(f"Stage 8A-T2 — Extracting Tier 2 params from {len(tier2_refs)} ref abstracts…", 14)
                    t2_params = extract_tier2_parameters(tier2_refs, client)

                params = t1_params + t2_params

                cupd("Stage 8A — Deriving cross-paper values…", 18)
                derived = derive_cross_paper_parameters(params, client)
                params += derived

                sufficiency = check_sufficiency(params, client)
                csv_data    = params_to_csv(params)
                _add_trace("Stage 8A — Parameters",
                           f"{len(papers_raw)} T1 papers + {len(tier2_refs)} T2 abstracts",
                           f"{len(t1_params)} T1 + {len(t2_params)} T2 + {len(derived)} derived = {len(params)} total")
                comp_prog.progress(25)

                # Stage 8B: Discovery
                cupd("Stage 8B — Cross-paper discovery engine…", 27)
                discovery = run_discovery_engine(wiki, params, context, client, domain_cfg)
                _add_trace("Stage 8B — Discovery",
                           f"{len(wiki.get('pages',[]))} wiki pages",
                           f"{len(discovery.get('hypotheses',[]))} novel hypotheses")
                comp_prog.progress(40)

                # Stage 9: Council model selection
                cupd(f"Stage 9 — LLM Council selecting model ({len(params)} params)…", 42)
                model_council = council_select_model(params, sufficiency, context, client)
                comp_prog.progress(55)

                # Stage 10: Multi-algorithm simulation
                simulation_params, _ = filter_confident_params(params)
                models_auto = resolve_models_to_run(simulation_params, model_council, sufficiency)
                cupd(f"Stage 10 — Running {len(models_auto)} algorithms: {', '.join(models_auto)}…", 57)
                sim_results = run_simulation(params, model_council, sufficiency)
                _add_trace("Stage 10 — Simulation",
                           f"{len(models_auto)} algorithms selected",
                           f"Models: {sim_results.get('models_run',[])} run")
                comp_prog.progress(72)

                # Stage 11: Multi-run council
                def _cp(run_num, total):
                    cupd(f"Stage 11 — Council run {run_num}/{total}…",
                         74 + int((run_num-1)/total*12))
                cupd(f"Stage 11 — Council synthesising insights ({n_council_runs}× runs)…", 74)
                merged_council = run_multi_council(
                    n_runs=n_council_runs,
                    sim_results=sim_results, discovery=discovery,
                    params=params, gaps=gaps, context=context,
                    client=client, progress_callback=_cp,
                )
                comp_prog.progress(88)

                # Stage 12: Package
                cupd("Stage 12 — Building report package…", 90)
                zip_bytes = build_zip(
                    params_csv=csv_data, sim_results=sim_results,
                    model_council=model_council, insight_council=merged_council,
                    context=context, params=params, sufficiency=sufficiency,
                    discovery=discovery,
                )
                comp_prog.progress(100)

                st.session_state.comp_results = {
                    "params": params, "derived_count": len(derived),
                    "t1_count": len(t1_params), "t2_count": len(t2_params),
                    "sufficiency": sufficiency, "csv_data": csv_data,
                    "discovery": discovery, "model_council": model_council,
                    "sim_results": sim_results, "insight_council": merged_council,
                    "n_runs": n_council_runs, "zip_bytes": zip_bytes,
                }
                # Save comp results to existing run
                if st.session_state.results:
                    try:
                        saved_comp_id = save_run(
                            lab_run_name.strip() or f"{default_lab_name} · Computational Lab",
                            st.session_state.results,
                            st.session_state.comp_results,
                        )
                        st.session_state.current_run_id = saved_comp_id
                        st.session_state.current_run_name = lab_run_name.strip() or f"{default_lab_name} · Computational Lab"
                        st.session_state.loaded_run_id = saved_comp_id
                    except Exception:
                        pass

                comp_prog.empty(); comp_stat.empty()
                st.success(
                    f"✅ Computational Lab saved — {len(params)} params "
                    f"(T1:{len(t1_params)} T2:{len(t2_params)} derived:{len(derived)}), "
                    f"{len(models_auto)} simulations, "
                    f"{len(discovery.get('hypotheses',[]))} hypotheses. "
                    f"Run history will show the 🧬 marker.")

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
        trace = st.session_state.pipeline_trace
        if not trace:
            st.info("Run the main analysis to see the pipeline trace here.")
        else:
            for i, entry in enumerate(trace, 1):
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

        if show_prompts:
            st.markdown("---")
            st.markdown("#### Active Prompts")
            from pipeline.wiki_compiler import WIKI_SYSTEM_PROMPT
            from pipeline.gap_detector import GAP_DETECTION_PROMPT
            with st.expander("Wiki Compiler Prompt"):
                st.code(WIKI_SYSTEM_PROMPT, language=None)
            with st.expander("Gap Detection Prompt"):
                st.code(GAP_DETECTION_PROMPT, language=None)

    # ── Tab 8: Export ──────────────────────────────────────────────────────────
    with tab8:
        st.markdown("### Export Results")
        st.markdown(
            '<div class="stage-card"><div class="stage-title">Polished Final Report</div>'
            '<div class="stage-body">Generates an enterprise HTML report and matching PDF with cover page, executive summary, corpus overview, references, graph, gaps, validation, proposals, risks, and appendices.</div></div>',
            unsafe_allow_html=True)
        gen_col, mode_col = st.columns([1, 2])
        with gen_col:
            generate_report = st.button("Generate final report", key="generate_final_report")
        with mode_col:
            use_llm_report = st.checkbox("Use LLM narrative polish", value=True,
                                         help="Uses the NVIDIA API key to write concise report narrative from existing structured results only.")

        if generate_report:
            try:
                report_client = (
                    build_client(selected_provider_key, provider_api_key, model=selected_model)
                    if (use_llm_report and provider_api_key) else None
                )
                narrative = generate_report_narrative(res, context, client=report_client)
                html_report = to_enterprise_html_report(res, context, narrative=narrative)
                pdf_report = to_enterprise_pdf_report(res, context, narrative=narrative)
                st.session_state.report_bundle = {
                    "html": html_report,
                    "pdf": pdf_report,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "used_llm": bool(report_client),
                }
                st.success("Final report generated.")
            except Exception as e:
                st.error(f"Final report generation failed: {e}")
                with st.expander("Report error details"):
                    st.code(traceback.format_exc())

        if st.session_state.report_bundle:
            bundle = st.session_state.report_bundle
            st.info(f"Report ready. Generated at {bundle.get('generated_at','')} · LLM narrative: {'yes' if bundle.get('used_llm') else 'no'}")
            dl1, dl2 = st.columns(2)
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
