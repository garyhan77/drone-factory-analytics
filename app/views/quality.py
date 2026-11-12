import streamlit as st

from factory import config as cfg
from factory.viz import charts, findings
from factory.viz import queries
from factory.viz.data import query
from factory.viz.render import chart, current_palette, page_header

pal = current_palette()
page_header("Quality & Traceability", "Quality engineer", "Which lots are failing inspection, and which drones are affected?")

data = queries.quality()
lots, flagged, recall_all = data["lots"], data["flagged"], data["recall"]

for sentence in findings.quality_finding(lots, recall_all):
    st.markdown(sentence)

st.subheader("Which lots?")
eligible = lots[lots["drones_inspected"] >= findings.LOT_MIN_DRONES].head(12).copy()
eligible["is_emergency"] = eligible["supplier_id"] == cfg.SPOT_BUY
labelled = eligible.assign(lot_id=eligible["lot_id"] + "  (" + eligible["part_name"] + ")")   # the chart names the part next to the lot
chart(charts.lot_failure_chart(labelled, pal, flag_at=findings.LOT_MIN_FAIL_RATE),
      eligible.assign(part_id=eligible["part_id"] + " " + eligible["part_name"])[["lot_id", "part_id", "supplier_name", "drones_inspected", "fails",
                                                                                 "fail_rate"]].rename(columns={
    "lot_id": "Lot", "part_id": "Part", "supplier_name": "Supplier", "drones_inspected": "Drones inspected", "fails": "Failed",
    "fail_rate": "Failure rate"}), key="lots",
    caption=f"Each bar is the share of a lot's drones that failed inspection at the station where the lot was installed. A drone counts as "
    f"failed even if it passed after rework. Lots with fewer than {findings.LOT_MIN_DRONES} inspected drones are left out, and a lot is "
    f"flagged at {findings.LOT_MIN_FAIL_RATE:.0%} or more. A regular lot can look elevated if it went into the same drones as an emergency lot.")

st.subheader("Recall scope")
choices = list(flagged["lot_id"]) or list(eligible["lot_id"])
if choices:
    part_of = dict(zip(lots["lot_id"], lots["part_name"]))
    lot = st.selectbox("Lot", choices, index=0, format_func=lambda x: f"{x} ({part_of[x]})", help="The flagged lots, worst first.")
    scope = query("SELECT drones_containing_lot, already_shipped, packed_not_shipped, still_in_the_line, first_installed, last_installed "
                  "FROM v_recall_scope WHERE lot_id = %s", (lot,)).iloc[0]
    left, middle, right = st.columns(3)
    left.metric("Already shipped", int(scope["already_shipped"]))
    middle.metric("Packed, waiting to ship", int(scope["packed_not_shipped"]))
    right.metric("Still in the line", int(scope["still_in_the_line"]))
    st.caption(f"{int(scope['drones_containing_lot'])} drones contain {lot} ({part_of[lot]}), installed between {scope['first_installed']:%d %b} and "
               f"{scope['last_installed']:%d %b %Y}.")
    drones = query(
        "SELECT l.serial_number AS \"Drone\", w.start_ts::date AS \"Installed\", "
        "CASE WHEN f.shipped_ts IS NOT NULL THEN 'Shipped' WHEN f.serial_number IS NOT NULL THEN 'Packed, waiting' "
        "ELSE 'Still in the line' END AS \"Where it is\", f.shipped_ts::date AS \"Shipped on\" "
        "FROM raw_drone_part_lots l JOIN raw_work_orders w ON w.serial_number = l.serial_number AND w.station_code = l.station_code "
        "LEFT JOIN raw_finished_goods f ON f.serial_number = l.serial_number WHERE l.lot_id = %s ORDER BY 2, 1", (lot,))
    with st.expander("Table view: every drone containing this lot"):
        st.dataframe(drones, hide_index=True, width="stretch")
else:
    st.info("No lot has enough inspected drones to judge.")
