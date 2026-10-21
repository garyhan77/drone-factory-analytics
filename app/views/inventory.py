import pandas as pd
import streamlit as st

from factory import config as cfg
from factory.viz import charts, findings, theme
from factory.viz import queries
from factory.viz.data import query
from factory.viz.render import chart, current_palette, page_header

pal = current_palette()
page_header("Inventory & Suppliers", "Material planner", "Which parts will run out first, and where is the stock?")

data = queries.inventory()
risk, perf, gap, regular = data["risk"], data["perf"], data["gap"], data["regular"]

for sentence in findings.inventory_finding(risk, regular, gap):
    st.markdown(sentence)

risk["label"] = risk["part_id"] + "  " + risk["part_name"] + " (" + risk["supplier_name"].str.split().str[0] + ")"
risk["Status"] = risk["risk_status"].map(theme.risk_label)

st.subheader("The most urgent parts")
urgent = risk.head(10)
chart(charts.cushion_chart(urgent, pal), risk[["Status", "part_id", "part_name", "supplier_name", "on_hand", "daily_demand", "days_remaining",
                                               "next_expected", "inbound_qty", "arrival_bad_case_days", "cushion_days"]].rename(columns={
    "part_id": "Part", "part_name": "Name", "supplier_name": "Supplier", "on_hand": "In stock", "daily_demand": "Used per day",
    "days_remaining": "Days of stock", "next_expected": "Next delivery due", "inbound_qty": "On order", "arrival_bad_case_days": "Days to a bad delivery",
    "cushion_days": "Cushion (days)"}), key="cushion",
    caption="Cushion = days of stock left, minus the days until the next delivery arrives if it is as late as that supplier's worst "
    "one in ten. Negative means the stock is expected to run out first. Usage is the last 14 days of drones started times the bill of "
    "materials. This is arithmetic on observed data, not a forecast. The table view lists all 40 parts.")

st.subheader("Supplier delivery performance")
chart(charts.horizontal_bar(perf["supplier_name"], perf["otif_rate"] * 100, pal, highlight=regular.sort_values("otif_rate")["supplier_name"].iloc[0], unit="%"),
      perf.rename(columns={"supplier_id": "ID", "supplier_name": "Supplier", "shipments_received": "Shipments", "on_time_rate": "On time",
                           "in_full_rate": "In full", "otif_rate": "On time and in full", "quantity_unverified": "Quantity unverified",
                           "avg_days_late": "Average days late", "p90_days_late": "90th percentile days late"}), key="suppliers",
      caption="Shipments received on or before the expected date with at least the expected quantity. Shipments whose recorded quantity "
      "was over the expected one are counted for on-time but not for in-full, because their true quantity is unknown. "
      "The spot-buy distributor is only used in emergencies and is left out of the comparison in the text above.")

st.subheader("Right part, wrong place")
top_gap = gap.head(8).copy()
top_gap["label"] = top_gap["part_id"] + "  " + top_gap["part_name"] + " (" + top_gap["station_name"] + ")"
worst_station = gap.groupby("station_name")["days_short_at_line"].sum().idxmax() if len(gap) else None
chart(charts.horizontal_bar(top_gap["label"], top_gap["days_short_at_line"], pal,
                            highlight=set(top_gap.loc[top_gap["station_name"] == worst_station, "label"]), unit=" days"),
      gap.rename(columns={"part_id": "Part", "part_name": "Name", "station_code": "Station code", "station_name": "Station",
                          "days_short_at_line": "Weekdays short at the line", "first_day": "First", "last_day": "Last",
                          "avg_warehouse_stock": "Average warehouse stock"}), key="gap",
      caption=f"Weekdays when the end-of-day warehouse count could cover at least one drone but the line-side shelf could not. "
      f"{worst_station} is in colour: it has the most parts affected." if worst_station else None)

st.subheader("Stock history")
choices = risk["part_id"] + "  " + risk["part_name"]
part_label = st.selectbox("Part", list(choices), index=0, help="Sorted by urgency, most urgent first.")
part_id = part_label.split()[0]
history = query("SELECT snapshot_date, location, on_hand FROM clean_inventory_snapshots WHERE part_id = %s ORDER BY snapshot_date", (part_id,))
reorder = int(query("SELECT reorder_point FROM clean_parts WHERE part_id = %s", (part_id,)).iloc[0, 0])
chart(charts.stock_history_chart(history, pal), history.pivot(index="snapshot_date", columns="location", values="on_hand").reset_index().rename(
    columns={"snapshot_date": "Date", "LINE_SIDE": "Line-side", "WAREHOUSE": "Warehouse"}), key="history",
    caption=f"The reorder point for this part is {reorder:,} units. A reorder is triggered when warehouse plus line-side plus on-order "
    "stock falls to that level, so it is not drawn against the warehouse alone.")
