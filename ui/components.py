"""Small HTML/Streamlit building blocks shared by the screens (moved out of app.py unchanged)."""
import streamlit as st

from pipeline.paper_manager import TIER_LABELS


def badge(text, color="#0066cc", bg="#e5f2ff", border="#7ab8f5"):
    return (f'<span style="display:inline-block;padding:0.15rem 0.5rem;'
            f'border-radius:10px;font-family:\'DM Mono\',monospace;font-size:0.65rem;'
            f'font-weight:500;color:{color};background:{bg};border:1px solid {border};'
            f'margin-right:0.3rem;">{text}</span>')


def tier_badge(tier: int) -> str:
    label, color, _ = TIER_LABELS.get(tier, ("Unknown", "#55708f", ""))
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
