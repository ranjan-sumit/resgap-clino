"""The app's stylesheet, moved out of app.py unchanged. `apply_theme()` injects it."""

from pathlib import Path

import streamlit as st

CSS_BASE = """
<style>
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
    color: #4a6580;
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
  .gap-card.partial { border-left-color: #8a5a00; }
  .gap-card.solved { border-left-color: #c81e1e; }
  .gap-card.pending { border-left-color: #4a6580; }
  .gap-title {
    font-family: 'DM Serif Display', serif;
    font-size: 1.1rem;
    color: #0b1f3a;
    margin-bottom: 0.5rem;
  }
  .gap-meta {
    font-family: 'DM Mono', monospace;
    font-size: 0.7rem;
    color: #4a6580;
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
  .badge-partial { background: #fff7e6; color: #8a5a00; border: 1px solid #f0c36a; }
  .badge-solved { background: #fff1f1; color: #c81e1e; border: 1px solid #f0a0a0; }
  .badge-high { background: #e5f2ff; color: #004b93; border: 1px solid #7ab8f5; }
  .badge-medium { background: #fff7e6; color: #8a5a00; border: 1px solid #f0c36a; }
  .badge-low { background: #f2f5f8; color: #4a6580; border: 1px solid #c9dff5; }

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
    color: #4a6580;
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
    color: #4a6580 !important;
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
"""

CSS_ENTERPRISE = """
<style>
  :root {
    --bg: #f5f9ff;
    --surface: #ffffff;
    --surface-muted: #edf6ff;
    --border: #c9dff5;
    --text: #0b1f3a;
    --muted: #4a6580;
    --accent: #0066cc;
    --accent-strong: #004b93;
    --accent-soft: #e5f2ff;
    --success: #087f5b;
    --warning: #8a5a00;
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
  .tier-3 { background:#f2f5f8 !important; color:#4a6580 !important; border:1px solid #c9d6e2 !important; }
  .badge-high, .badge-open { background:#e7f8f1 !important; color:#087f5b !important; border-color:#83d7b1 !important; }
  .badge-medium, .badge-partial { background:#fff7e6 !important; color:#8a5a00 !important; border-color:#f0c36a !important; }
  .badge-low, .badge-solved { background:#fff1f1 !important; color:#c81e1e !important; border-color:#f0a0a0 !important; }
</style>
"""

CSS_EXTRA = """
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
  .tier-3 { background:#f2f5f8; color:#4a6580; border:1px solid #c9dff5; }
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
    font-family:'DM Mono',monospace; font-size:0.65rem; color:#4a6580;
  }

  /* Reference paper list */
  .ref-card {
    background:#ffffff; border:1px solid #c9dff5; border-left:3px solid #c9dff5;
    border-radius:5px; padding:0.6rem 0.9rem; margin-bottom:0.3rem;
  }
  .ref-card.tier-2-card { border-left-color:#087f5b; }
  .ref-card.tier-3-card { border-left-color:#4a6580; }
  .ref-title { font-size:0.85rem; color:#0b1f3a; }
  .ref-meta  { font-family:'DM Mono',monospace; font-size:0.68rem; color:#4a6580; margin-top:0.2rem; }

  /* ── UI-02: one button system, one field style, a smaller heading scale ──────────────────────
     Primary = solid blue, for the one action a screen is about. Everything else is outlined.
     Destructive actions are outlined in red until the user confirms. */
  [data-testid="stMainBlockContainer"] { padding-top: 2.5rem !important; }

  .stButton > button[kind="secondary"], .stButton > button[kind="secondaryFormSubmit"],
  .stDownloadButton > button:not([kind="primary"]) {
    background: var(--surface) !important; color: #243b53 !important;
    border: 1px solid #9fb3c8 !important; font-weight: 500 !important;
  }
  .stButton > button[kind="secondary"]:hover:not(:disabled), .stButton > button[kind="secondaryFormSubmit"]:hover:not(:disabled),
  .stDownloadButton > button:not([kind="primary"]):hover:not(:disabled) {
    background: #f1f6fc !important; border-color: #243b53 !important; color: #0b1f3a !important;
  }
  .stButton > button[kind="primary"], .stButton > button[kind="primaryFormSubmit"], .stDownloadButton > button[kind="primary"] {
    background: var(--accent) !important; color: #ffffff !important; border: 1px solid var(--accent) !important; font-weight: 600 !important;
  }
  .stButton > button[kind="primary"]:hover:not(:disabled), .stButton > button[kind="primaryFormSubmit"]:hover:not(:disabled),
  .stDownloadButton > button[kind="primary"]:hover:not(:disabled) { background: var(--accent-strong) !important; }
  .stButton > button:disabled, .stDownloadButton > button:disabled {
    background: transparent !important; color: #8aa0b8 !important; border: 1px solid #d3e0ee !important; cursor: not-allowed;
  }
  [class*="st-key-clear_"] .stButton > button[kind="secondary"], [class*="st-key-delete_"] .stButton > button[kind="secondary"],
  .st-key-empty_deleted .stButton > button[kind="secondary"] { color: #9b1c1c !important; border-color: #e3a8a8 !important; }
  [class*="st-key-clear_"] .stButton > button[kind="secondary"]:hover:not(:disabled),
  [class*="st-key-delete_"] .stButton > button[kind="secondary"]:hover:not(:disabled),
  .st-key-empty_deleted .stButton > button[kind="secondary"]:hover:not(:disabled) {
    background: #fff1f1 !important; border-color: #c81e1e !important; color: #9b1c1c !important;
  }

  /* text, text-area and number fields share one white field with one border (Streamlit tints the outer
     element with the theme's secondary background, which left a blue ring and blue number boxes) */
  [data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"], [data-testid="stNumberInputContainer"] {
    background-color: var(--surface) !important;
  }
  [data-testid="stTextAreaRootElement"], [data-testid="stNumberInputContainer"] { border: 1px solid var(--border) !important; border-radius: 6px !important; }

  /* headings: Streamlit's defaults (2.5rem for a page title) are far larger than the rest of the screen */
  [data-testid="stMainBlockContainer"] h1 { font-size: 1.9rem !important; letter-spacing: -0.02em; }
  [data-testid="stMainBlockContainer"] h2 { font-size: 1.55rem !important; font-weight: 700 !important; letter-spacing: -0.015em; }
  [data-testid="stMainBlockContainer"] h3 { font-size: 1.2rem !important; font-weight: 600 !important; letter-spacing: -0.01em; }
  [data-testid="stMainBlockContainer"] h4 { font-size: 1.02rem !important; font-weight: 600 !important; }
</style>
"""



# Accessibility: AA text contrast for the colours the framework derives (captions, the selected section),
# and a visible keyboard focus ring everywhere. The values come from ui/tokens.py.
CSS_A11Y = """
<style>
  [data-testid="stCaptionContainer"] { opacity: 1 !important; }      /* the framework fades captions to 60%: below AA */
  [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p, .stCaption, small { color: #4a6580 !important; }
  button[role="radio"][aria-checked="true"], button[role="radio"][aria-checked="true"] * { color: #004b93 !important; }   /* selected section */
  [data-testid="stFileUploaderDropzoneInstructions"], [data-testid="stFileUploaderDropzoneInstructions"] * { color: #4a6580 !important; opacity: 1 !important; }
  :focus-visible { outline: 3px solid #0066cc !important; outline-offset: 2px !important; border-radius: 4px; }
  [data-testid="stSidebar"] :focus-visible { outline-color: #004b93 !important; }
  @media (max-width: 640px) {
    .main .block-container, [data-testid="stMainBlockContainer"] { padding-left: 1rem !important; padding-right: 1rem !important; }
    .stat-box .stat-number { font-size: 1.6rem !important; }
  }
</style>
"""


def font_css() -> str:
    """The @font-face rules for the self-hosted fonts in static/fonts (served by Streamlit at /app/static/). Empty if missing."""
    try:
        return "<style>\n" + (Path(__file__).resolve().parent.parent / "static" / "fonts" / "fonts.css").read_text(encoding="utf-8") + "</style>"
    except OSError:
        return ""


def apply_theme() -> None:
    for css in (font_css(), CSS_BASE, CSS_ENTERPRISE, CSS_EXTRA, CSS_A11Y):
        st.markdown(css, unsafe_allow_html=True)
