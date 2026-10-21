import streamlit as st

from factory.viz import findings, queries
from factory.viz.render import page_header

page_header("Overview", "Everyone", "What's going on in the factory, and can I trust the data?")

st.markdown(findings.status_line(queries.status()))

production, quality, inventory, dq = queries.production(), queries.quality(), queries.inventory(), queries.data_quality()

sections = [
    ("Production", "Production lead", "views/production.py", "Open the Production page",
     findings.production_finding(production["summary"], production["output"], production["wip"])),
    ("Quality & Traceability", "Quality engineer", "views/quality.py", "Open the Quality & Traceability page",
     findings.quality_finding(quality["weekly"], quality["lots"], quality["recall"])),
    ("Inventory & Suppliers", "Material planner", "views/inventory.py", "Open the Inventory & Suppliers page",
     findings.inventory_finding(inventory["risk"], inventory["regular"], inventory["gap"])),
    ("Data Quality", "Data analyst", "views/data_quality.py", "Open the Data Quality page",
     findings.data_quality_finding(dq["results"], dq["impact"])),
]
for title, role, path, label, sentences in sections:
    with st.container(border=True):
        st.caption(f"{title.upper()}  ·  {role.upper()}")
        for sentence in sentences:
            st.markdown(sentence)
        st.page_link(path, label=label, icon=":material/arrow_forward:")

with st.expander("About this project"):
    st.markdown(
        "- **The data is synthetic.** It comes from a simulation of a five-station drone assembly line and the inventory system that "
        "feeds it, with a planted story (a supplier crisis, a defect spike, a bottleneck) and planted data errors.\n"
        "- **The analysis is real.** Every figure on these pages is computed in SQL from cleaned views over a PostgreSQL database; "
        "the cleaning rules and the checks that justify them are on the Data Quality page.\n"
        "- **Built with** PostgreSQL, Python and Streamlit.")
