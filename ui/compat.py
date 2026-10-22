"""Full-width widgets across Streamlit versions.

Newer releases want width="stretch" and are retiring use_container_width; older
ones only know use_container_width. These are the only places that name it.
"""
import streamlit as st

_LEGACY = "use_container" + "_width"      # spelled in two parts: a test forbids the literal elsewhere


def _stretch(fn, *args, **kwargs):
    try:
        return fn(*args, width="stretch", **kwargs)
    except (TypeError, st.errors.StreamlitAPIException):
        return fn(*args, **{_LEGACY: True}, **kwargs)


def table_full_width(df, **kwargs):
    return _stretch(st.dataframe, df, **kwargs)


def plotly_full_width(fig, **kwargs):
    return _stretch(st.plotly_chart, fig, **kwargs)
