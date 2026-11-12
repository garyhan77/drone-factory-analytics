import streamlit as st

from factory.viz import findings, queries
from factory.viz.render import page_header

page_header("Overview", "Everyone", "Drone Factory Analytics")

quality, inventory = queries.quality(), queries.inventory()

st.markdown("**The story in one line:** a supplier ships late, a part runs out, the line buys a substitute lot, "
            "that lot fails inspection far more often, and the lot number tells us exactly which drones are affected.")

sections = [
    ("Quality & Traceability", "Quality engineer", "views/quality.py", "Open the Quality & Traceability page",
     findings.quality_finding(quality["lots"], quality["recall"])),
    ("Inventory & Suppliers", "Material planner", "views/inventory.py", "Open the Inventory & Suppliers page",
     findings.inventory_finding(inventory["ridgeline"], inventory["emergency_lots"])),
]
for title, role, path, label, sentences in sections:
    with st.container(border=True):
        st.caption(f"{title.upper()}  ·  {role.upper()}")
        for sentence in sentences:
            st.markdown(sentence)
        st.page_link(path, label=label, icon=":material/arrow_forward:")
