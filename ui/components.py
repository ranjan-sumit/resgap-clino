"""Small HTML/Streamlit building blocks shared by the screens (moved out of app.py unchanged)."""
import html

import streamlit as st

from pipeline.paper_manager import TIER_LABELS


# ── states: one look for "nothing here", "something went wrong" and "working" ─────────────────────
def _state_box(icon: str, title: str, hint: str, color: str, role: str) -> str:
    hint_html = (f'<div style="font-size:0.85rem;color:#4a6580;margin-top:0.2rem;">{html.escape(hint)}</div>'
                 if hint else "")
    return (f'<div role="{role}" style="border:1px dashed {color};border-radius:8px;padding:0.9rem 1.1rem;'
            f'margin:0.6rem 0;background:#ffffff;"><div style="font-weight:600;color:#0b1f3a;">'
            f'<span aria-hidden="true">{icon}</span> {html.escape(title)}</div>{hint_html}</div>')


def empty_state(title: str, hint: str = "") -> None:
    """Nothing to show here yet, and what to do about it."""
    st.markdown(_state_box("○", title, hint, "#7ab8f5", "status"), unsafe_allow_html=True)


def error_state(title: str, hint: str = "") -> None:
    """Something failed, in words, with what the reader can try."""
    st.markdown(_state_box("!", title, hint, "#c81e1e", "alert"), unsafe_allow_html=True)


def loading_state(message: str) -> None:
    """Work in progress, announced politely to screen readers."""
    st.markdown(_state_box("…", message, "", "#7ab8f5", "status"), unsafe_allow_html=True)


def badge(text, color="#0066cc", bg="#e5f2ff", border="#7ab8f5", title=""):
    hint = f' title="{html.escape(str(title), quote=True)}"' if title else ""
    return (f'<span{hint} style="display:inline-block;padding:0.15rem 0.5rem;'
            f'border-radius:10px;font-family:\'DM Mono\',monospace;font-size:0.65rem;'
            f'font-weight:500;color:{color};background:{bg};border:1px solid {border};'
            f'margin-right:0.3rem;">{text}</span>')


def esc(value) -> str:
    """Text for putting inside HTML: every character that could start markup is escaped. Use it for anything that
    came from a paper, a model or a user (titles, claims, names, error text); tests refuse unescaped values."""
    return html.escape("" if value is None else str(value), quote=True)


def sidebar_collapse_script(max_width: int = 768) -> str:
    """The script that closes the sidebar on a narrow screen (a no-op on a wide one). It lives here, as a
    plain string, so its content can be tested; app.py hands it to a zero-height frame."""
    return ("<script>const p = window.parent; if (p.innerWidth <= " + str(int(max_width)) + ") { "
            "const b = p.document.querySelector('[data-testid=\"stSidebarCollapseButton\"] button'); "
            "if (b) b.click(); }</script>")


def collapse_sidebar_on_phones() -> None:
    import streamlit.components.v1 as components
    components.html(sidebar_collapse_script(), height=0)


def tier_badge(tier: int) -> str:
    label, color, _ = TIER_LABELS.get(tier, ("Unknown", "#4a6580", ""))
    bgs = {1: "#e5f2ff", 2: "#e7f8f1", 3: "#f2f5f8"}
    borders = {1: "#7ab8f5", 2: "#83d7b1", 3: "#c9dff5"}
    return badge(f"T{tier} {label}", color, bgs.get(tier, "#f2f5f8"), borders.get(tier, "#c9dff5"))


def card(title, body, color="#0066cc"):
    return (f'<div class="stage-card"><div class="stage-title" style="color:{color};">{title}</div>'
            f'<div class="stage-body">{body}</div></div>')


def section_label(t):
    st.markdown(f'<div class="wiki-label">{t}</div>', unsafe_allow_html=True)


def item(t, color="#0b1f3a"):
    st.markdown(f'<div class="wiki-item" style="color:{color};margin-bottom:0.25rem;">{t}</div>',
                unsafe_allow_html=True)


def skeleton(lines=3):
    markup = '<div class="skeleton-card">' + ''.join(
        f'<div class="skeleton" style="width:{w}%;"></div>'
        for w in ([90, 70, 55, 40][:lines])
    ) + '</div>'
    st.markdown(markup, unsafe_allow_html=True)
