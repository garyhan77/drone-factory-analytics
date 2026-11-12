import streamlit as st

from factory import config as cfg
from factory.viz import charts, findings
from factory.viz import queries
from factory.viz.data import query
from factory.viz.render import chart, current_palette, page_header

pal = current_palette()
page_header("Inventory & Suppliers", "Material planner", "Which delivery was late, and what did it cause?")

data = queries.inventory()
ridgeline, parts = data["ridgeline"], data["parts"]

for sentence in findings.inventory_finding(ridgeline, data["emergency_lots"]):
    st.markdown(sentence)

st.subheader("Deliveries from Ridgeline Hardware")
labels = ridgeline["part_name"] + ", due " + ridgeline["expected_date"].map(lambda d: f"{d.day} {d:%b}")
late = set(labels[ridgeline["days_late"] > 0])
chart(charts.horizontal_bar(labels, ridgeline["days_late"], pal, highlight=late, unit=" days"),
      ridgeline[["lot_id", "part_name", "expected_date", "received_date", "days_late", "qty_expected", "qty_received"]].rename(columns={
          "lot_id": "Lot", "part_name": "Part", "expected_date": "Due", "received_date": "Arrived", "days_late": "Days late",
          "qty_expected": "Units expected", "qty_received": "Units received"}), key="deliveries",
      caption="Days after the due date that each delivery arrived. Late deliveries are in colour. The emergency lots bought from the "
      "spot-buy distributor are not included.")

st.subheader("Stock history")
choices = parts["part_id"] + "  " + parts["part_name"]
default = next((i for i, n in enumerate(parts["part_name"]) if n in cfg.SPIKE_FASTENERS), 0)
part_label = st.selectbox("Part", list(choices), index=default)
part_id = part_label.split()[0]
history = query("SELECT snapshot_date, location, on_hand FROM raw_inventory_snapshots WHERE part_id = %s ORDER BY snapshot_date", (part_id,))
reorder = int(query("SELECT reorder_point FROM raw_parts WHERE part_id = %s", (part_id,)).iloc[0, 0])
chart(charts.stock_history_chart(history, pal), history.pivot(index="snapshot_date", columns="location", values="on_hand").reset_index().rename(
    columns={"snapshot_date": "Date", "LINE_SIDE": "Line-side", "WAREHOUSE": "Warehouse"}), key="history",
    caption=f"The reorder point for this part is {reorder:,} units. A reorder is triggered when warehouse plus line-side plus on-order "
    "stock falls to that level, so it is not drawn against the warehouse alone.")
