import streamlit as st

from factory.viz import charts, findings
from factory.viz.data import query
from factory.viz.render import chart, current_palette, page_header

pal = current_palette()
page_header("Production", "Production lead", "Why is output flat while starts keep rising?")

summary = query("SELECT * FROM v_station_summary ORDER BY station_seq")
output = query("SELECT week_start, units_started, units_completed FROM v_weekly_output ORDER BY week_start")
wip = query("SELECT stage, drones, avg_age_days, max_age_days FROM v_wip_by_stage ORDER BY drones DESC")
waits = query("SELECT week_start, station_seq, station_name, avg_wait_hours FROM v_queue_wait_weekly ORDER BY station_seq, week_start")
lead = query("SELECT week_start, drones_shipped, avg_lead_days, avg_dwell_days FROM v_lead_time_weekly ORDER BY week_start")

for sentence in findings.production_finding(summary, output, wip):
    st.markdown(sentence)

bottleneck = summary.loc[summary["avg_wait_hours"].idxmax(), "station_name"]
full_weeks = findings.drop_partial_last_week(output)

st.subheader("Drones started and finished each week")
chart(charts.weekly_output_chart(full_weeks, pal), full_weeks.rename(columns={
    "week_start": "Week of", "units_started": "Started", "units_completed": "Finished"}), key="output",
    caption="The final week is left out: the data is extracted on a Friday afternoon, so that week is incomplete.")

st.subheader("Where drones wait")
chart(charts.wait_small_multiples(waits, pal, highlight=bottleneck), waits.rename(columns={
    "week_start": "Week of", "station_seq": "Seq", "station_name": "Station", "avg_wait_hours": "Average wait (hours)"}),
    key="waits", caption="Time from finishing the previous station to starting this one, so it includes nights and weekends. "
    "The first station has no wait. All panels share one scale.")

st.subheader("Where drones are now")
stage_order = wip.sort_values("drones", ascending=False)
chart(charts.horizontal_bar(stage_order["stage"], stage_order["drones"], pal, highlight=f"Waiting for {bottleneck}"),
      stage_order.rename(columns={"stage": "Stage", "drones": "Drones", "avg_age_days": "Average age (days)", "max_age_days": "Oldest (days)"}),
      key="wip", caption="Drones started but not yet shipped, by the stage they are in at the time of the extract.")

st.subheader("What it does to delivery")
shipped = findings.drop_partial_last_week(lead)
chart(charts.lead_dwell_chart(shipped, pal), shipped.rename(columns={
    "week_start": "Shipped week of", "drones_shipped": "Drones shipped", "avg_lead_days": "Lead time (days)",
    "avg_dwell_days": "Dwell after test (days)"}), key="lead",
    caption="Lead time grows because drones queue before Avionics; dwell after testing does not, so the delay is upstream. "
    "Only shipped drones can be measured, so the longest waits (drones still in the line) are missing from the recent weeks.")

st.subheader("Station summary")
summary_table = summary.astype(object).where(summary.notna(), "-")  # the first station has no wait: show a dash, not "None"
st.dataframe(summary_table.rename(columns={
    "station_seq": "Seq", "station_code": "Code", "station_name": "Station", "completed_orders": "Completed jobs",
    "median_cycle_hours": "Median cycle (h)", "p90_cycle_hours": "90th percentile cycle (h)",
    "avg_wait_hours": "Average wait (h)", "p90_wait_hours": "90th percentile wait (h)"}), hide_index=True, width="stretch")
