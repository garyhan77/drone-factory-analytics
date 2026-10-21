"""The thin layer that touches Streamlit: theme mode, page header, and charts with their table views."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .theme import Palette, palette

SYNTHETIC_NOTE = (
    "This is synthetic data from a simulated drone factory, not real production data. "
    "The story in it is planted by the generator; the analysis around it is real."
)


def current_palette() -> Palette:
    """The palette for the viewer's current Streamlit theme (light or dark)."""
    try:
        mode = st.context.theme.type
    except Exception:
        mode = None
    return palette(mode)


def page_header(title: str, role: str, question: str) -> None:
    st.caption(role.upper())
    st.title(title)
    st.markdown(f"#### {question}")
    st.caption(SYNTHETIC_NOTE)


def chart(fig: go.Figure, table: pd.DataFrame | None = None, *, key: str, caption: str | None = None) -> None:
    """Show a chart, with its table view underneath (every value is reachable without hovering)."""
    st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False}, key=key)
    if caption:
        st.caption(caption)
    if table is not None:
        with st.expander("Table view"):
            st.dataframe(table, hide_index=True, width="stretch")
