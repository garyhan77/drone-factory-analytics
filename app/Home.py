"""Drone Factory Analytics: entry point. Run with:  streamlit run app/Home.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Drone Factory Analytics", page_icon="🛩️", layout="wide")

pages = [
    st.Page("views/overview.py", title="Overview", default=True),
    st.Page("views/production.py", title="Production"),
    st.Page("views/quality.py", title="Quality & Traceability"),
    st.Page("views/inventory.py", title="Inventory & Suppliers"),
    st.Page("views/data_quality.py", title="Data Quality"),
]
st.navigation(pages).run()
