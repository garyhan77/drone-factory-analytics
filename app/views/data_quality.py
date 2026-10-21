import pandas as pd
import streamlit as st

from factory import config as cfg
from factory.viz import charts, findings
from factory.viz.data import query
from factory.viz.render import chart, current_palette, page_header

pal = current_palette()
page_header("Data Quality", "Data analyst", "Can we trust the data?")

results = query("SELECT check_name, category, severity, description, flagged_rows, planted_rows, caught, missed, false_positives FROM dq_results")
order = {c: i for i, c in enumerate(["planted", "reconciliation", "guard", "sanity", "operational"])}
results = results.assign(rank=results["category"].map(order)).sort_values(["rank", "check_name"]).drop(columns="rank").reset_index(drop=True)

impact = query("""
    SELECT 'Work orders' AS table_name, (SELECT COUNT(*) FROM raw_work_orders) AS raw_rows, (SELECT COUNT(*) FROM clean_work_orders) AS clean_rows,
           (SELECT COUNT(*) FROM clean_work_orders WHERE end_unknown) AS changed,
           'Re-keyed duplicates dropped. Jobs that end before they start are kept, with the end time left blank.' AS what
    UNION ALL SELECT 'Inspections', (SELECT COUNT(*) FROM raw_inspections), (SELECT COUNT(*) FROM clean_inspections),
           (SELECT COUNT(*) FROM clean_inspections WHERE code_was_missing),
           'Inspections for a drone with no work order at that station dropped. Failures with no usable defect code are kept and labelled UNCODED.'
    UNION ALL SELECT 'Inventory snapshots', (SELECT COUNT(*) FROM raw_inventory_snapshots), (SELECT COUNT(*) FROM clean_inventory_snapshots),
           (SELECT COUNT(*) FROM clean_inventory_snapshots WHERE repaired), 'Negative readings replaced by the last good reading for that part and location.'
    UNION ALL SELECT 'Receiving', (SELECT COUNT(*) FROM raw_receiving), (SELECT COUNT(*) FROM clean_receiving),
           (SELECT COUNT(*) FROM clean_receiving WHERE qty_capped), 'Over-received quantities capped at the expected quantity; they earn no in-full credit.'
""")

for sentence in findings.data_quality_finding(results, impact):
    st.markdown(sentence)

results["Type"] = results["category"].map(findings.CATEGORY_NAMES)

st.subheader("What the checks caught")
detectors = results[results["category"].isin(["planted", "reconciliation"]) & (results["planted_rows"].fillna(0) > 0)].copy()
detectors[["planted_rows", "caught", "missed", "false_positives"]] = detectors[["planted_rows", "caught", "missed", "false_positives"]].astype(int)
detectors["label"] = detectors["check_name"].str.replace("_", " ").str.capitalize()
detectors = detectors.sort_values("planted_rows", ascending=False)
chart(charts.detection_chart(detectors, pal), detectors[["label", "planted_rows", "caught", "missed", "false_positives"]].rename(columns={
    "label": "Check", "planted_rows": "Planted rows", "caught": "Caught", "missed": "Missed", "false_positives": "False positives"}), key="detected",
    caption="The generator plants a known set of errors and records exactly which rows it changed; each check is scored against that "
    "record. This tests the checks against the error types I thought to plant. It says nothing about error types nobody planted, "
    "which is the real risk with real data.")

st.subheader("All checks")
board = results[["check_name", "Type", "flagged_rows", "planted_rows", "caught", "missed", "false_positives"]].rename(columns={
    "check_name": "Check", "flagged_rows": "Flagged", "planted_rows": "Planted", "caught": "Caught",
    "missed": "Missed", "false_positives": "False positives"})
for column in ("Planted", "Caught", "Missed", "False positives"):  # whole numbers as text, with a dash where a check is not scored
    board[column] = board[column].map(lambda v: "-" if pd.isna(v) else str(int(v)))
st.dataframe(board, hide_index=True, width="stretch", height="content")
st.caption("Guard and sanity checks watch relationships and rules nothing was planted into, so they should flag nothing; any row they flag "
           "counts as a false positive. The operational warning is not a data error and is not scored. "
           "Pick a check below to see what it looks for and what it flagged.")

st.subheader("Flagged records")
default = detectors["check_name"].iloc[0] if len(detectors) else results["check_name"].iloc[0]
names = list(results["check_name"])
check = st.selectbox("Check", names, index=names.index(default), help="Planted-error checks first.")
row = results[results["check_name"] == check].iloc[0]
st.caption(f"{row['Type']}: {row['description']}")
flagged = query("SELECT record_key FROM dq_flagged WHERE check_name = %s ORDER BY record_key", (check,))
key = set(query("SELECT record_key FROM dq_answer_key WHERE check_name = %s", (check,))["record_key"])
if flagged.empty:
    st.success("No records flagged.")
else:
    scored = row["category"] != "operational"
    flagged["Planted?"] = flagged["record_key"].map(lambda k: "Not scored" if not scored else ("Yes, it was planted" if k in key else "No: a false positive"))
    st.dataframe(flagged.rename(columns={"record_key": "Record"}), hide_index=True, width="stretch",
                 height="content" if len(flagged) <= 20 else 420)

st.subheader("What cleaning changed")
changes = impact.assign(dropped=impact["raw_rows"] - impact["clean_rows"]).rename(columns={
    "table_name": "Table", "raw_rows": "Raw rows", "clean_rows": "Clean rows", "dropped": "Dropped", "changed": "Kept, with a fix", "what": "What was done"})
st.table(changes[["Table", "Raw rows", "Clean rows", "Dropped", "Kept, with a fix", "What was done"]].set_index("Table"))

st.subheader("What the bad data would have hidden")
left, right = st.columns(2)
spike = query(
    "SELECT COUNT(*) AS failures, COUNT(*) FILTER (WHERE COALESCE(TRIM(i.defect_code), '') <> '') AS with_code FROM raw_inspections i "
    "WHERE i.station_code = %s AND i.attempt = 1 AND i.result = 'FAIL' AND i.serial_number IN "
    "(SELECT serial_number FROM clean_drone_part_lots WHERE lot_id LIKE %s)", (cfg.SPIKE_STATION, cfg.SUBSTITUTE_LOT_PREFIX + "-%")).iloc[0]
with left:
    st.markdown("**The defect spike would look smaller.**")
    a, b = st.columns(2)
    a.metric("In the raw data", f"{int(spike['with_code'])} of {int(spike['failures'])}")
    b.metric("After cleaning", f"{int(spike['failures'])} of {int(spike['failures'])}")
    st.caption(f"First-attempt failures at {cfg.SPIKE_STATION} on drones that received an emergency lot, counted if they have a usable defect "
               "code. A defect chart built from the raw data would drop the ones with no code. Cleaning keeps them, labelled UNCODED.")
fasteners = list(query("SELECT part_id FROM clean_parts WHERE part_name = ANY(%s)", (list(cfg.SPIKE_FASTENERS),))["part_id"])
shortage = query(
    "SELECT r.snapshot_date, SUM(r.on_hand) AS reported, SUM(c.on_hand) AS cleaned FROM raw_inventory_snapshots r "
    "JOIN clean_inventory_snapshots c USING (snapshot_date, part_id, location) WHERE r.part_id = ANY(%s) "
    "GROUP BY r.snapshot_date HAVING SUM(r.on_hand) <> SUM(c.on_hand) ORDER BY ABS(SUM(r.on_hand) - SUM(c.on_hand)) DESC LIMIT 1", (fasteners,))
with right:
    st.markdown("**The fastener shortage would look worse.**")
    if shortage.empty:
        st.caption("No day's fastener stock was distorted.")
    else:
        day = shortage.iloc[0]
        a, b = st.columns(2)
        a.metric("In the raw data", f"{int(day['reported']):,}")
        b.metric("After cleaning", f"{int(day['cleaned']):,}")
        st.caption(f"Units of the three Motor & Prop fastener parts, warehouse and line-side together, on {day['snapshot_date']:%d %B}, the day with "
                   "the largest gap between raw and cleaned. Negative readings are replaced by the last good reading.")
