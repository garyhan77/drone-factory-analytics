import pandas as pd
import streamlit as st

from factory import config as cfg
from factory.viz import charts, findings
from factory.viz import queries
from factory.viz.data import query
from factory.viz.render import chart, current_palette, page_header

pal = current_palette()
page_header("Quality & Traceability", "Quality engineer", "Why did yield drop, and which drones are affected?")

data = queries.quality()
weekly, pareto, lots, flagged, recall_all = data["weekly"], data["pareto"], data["lots"], data["flagged"], data["recall"]

for sentence in findings.quality_finding(weekly, lots, recall_all):
    st.markdown(sentence)

summary = findings.station_yield_summary(weekly)
stations = list(weekly.sort_values("station_seq")["station_name"].unique())
default = summary.loc[summary["z"].idxmin(), "station_name"] if len(summary) else stations[0]
station = st.selectbox("Station", stations, index=stations.index(default),
                       help="Scopes the yield chart and which defect codes are highlighted.")
code = weekly.loc[weekly["station_name"] == station, "station_code"].iloc[0]

st.subheader(f"First-pass yield at {station}, by week")
mine = weekly[weekly["station_name"] == station]
overall = mine["passes"].sum() / mine["inspections"].sum()
chart(charts.yield_chart(mine, overall, pal), mine[["week_start", "inspections", "passes", "fpy"]].rename(columns={
    "week_start": "Week of", "inspections": "Inspections", "passes": "Passed first time", "fpy": "Yield"}), key="yield",
    caption="First attempts only: a drone that fails and passes after rework still counts as a first-pass failure. "
    "The vertical axis starts below 100% so the dips are visible.")

st.subheader("Which defects?")
top = pareto.head(10)
uncoded = int(pareto.loc[pareto["defect_code"].str.endswith("UNCODED"), "fails"].sum())
chart(charts.horizontal_bar(top["defect_code"], top["fails"], pal, highlight=set(top.loc[top["station_code"] == code, "defect_code"])),
      top.rename(columns={"station_code": "Station", "defect_code": "Defect code", "fails": "Failures", "pct_of_fails": "Share of all failures",
                          "cum_pct": "Cumulative share"}), key="pareto",
      caption=f"The ten most common first-attempt failures. Codes at {station} are in colour. "
      f"{uncoded} failures were recorded with no usable defect code; they are kept and labelled UNCODED, not dropped.")

st.subheader("Which lots?")
eligible = lots[lots["drones_inspected"] >= findings.LOT_MIN_DRONES].head(12).copy()
eligible["is_emergency"] = eligible["supplier_id"] == cfg.SPOT_BUY
chart(charts.lot_lift_chart(eligible, pal, flag_at=findings.LOT_MIN_LIFT), eligible[["lot_id", "part_id", "supplier_name", "drones_inspected", "fails", "fail_rate",
                                                       "station_fail_rate", "lift"]].rename(columns={
    "lot_id": "Lot", "part_id": "Part", "supplier_name": "Supplier", "drones_inspected": "Drones inspected", "fails": "Failed",
    "fail_rate": "Failure rate", "station_fail_rate": "Station rate", "lift": "Times the station rate"}), key="lots",
    caption=f"Each bar is a lot's first-attempt failure rate divided by its station's. Lots with fewer than "
    f"{findings.LOT_MIN_DRONES} inspected drones are left out, and a lot is flagged at {findings.LOT_MIN_LIFT:.0f} times or more. "
    "A regular lot can look elevated if it went into the same drones as an emergency lot.")

st.subheader("Recall scope")
choices = list(flagged["lot_id"]) or list(eligible["lot_id"])
if choices:
    lot = st.selectbox("Lot", choices, index=0, help="The flagged lots, worst first.")
    scope = query("SELECT drones_containing_lot, already_shipped, packed_not_shipped, still_in_the_line, first_installed, last_installed "
                  "FROM v_recall_scope WHERE lot_id = %s", (lot,)).iloc[0]
    left, middle, right = st.columns(3)
    left.metric("Already shipped", int(scope["already_shipped"]))
    middle.metric("Packed, waiting to ship", int(scope["packed_not_shipped"]))
    right.metric("Still in the line", int(scope["still_in_the_line"]))
    st.caption(f"{int(scope['drones_containing_lot'])} drones contain {lot}, installed between {scope['first_installed']:%d %b} and "
               f"{scope['last_installed']:%d %b %Y}.")
    drones = query(
        "SELECT l.serial_number AS \"Drone\", w.start_ts::date AS \"Installed\", "
        "CASE WHEN f.shipped_ts IS NOT NULL THEN 'Shipped' WHEN f.serial_number IS NOT NULL THEN 'Packed, waiting' "
        "ELSE 'Still in the line' END AS \"Where it is\", f.shipped_ts::date AS \"Shipped on\" "
        "FROM clean_drone_part_lots l JOIN clean_work_orders w ON w.serial_number = l.serial_number AND w.station_code = l.station_code "
        "LEFT JOIN clean_finished_goods f ON f.serial_number = l.serial_number WHERE l.lot_id = %s ORDER BY 2, 1", (lot,))
    with st.expander("Table view: every drone containing this lot"):
        st.dataframe(drones, hide_index=True, width="stretch")
else:
    st.info("No lot has enough inspected drones to judge.")
