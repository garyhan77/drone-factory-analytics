"""The queries behind each page, in one place so the Overview and the page it summarises always agree.

Each function returns the DataFrames a page needs. They all go through factory.viz.data.query, which caches by query text,
so a page and the Overview that reuses it cost one database round trip, not two.
"""
from __future__ import annotations

import pandas as pd

from factory import config as cfg

from . import findings
from .data import query


def production() -> dict[str, pd.DataFrame]:
    return {
        "summary": query("SELECT * FROM v_station_summary ORDER BY station_seq"),
        "output": query("SELECT week_start, units_started, units_completed FROM v_weekly_output ORDER BY week_start"),
        "wip": query("SELECT stage, drones, avg_age_days, max_age_days FROM v_wip_by_stage ORDER BY drones DESC"),
        "waits": query("SELECT week_start, station_seq, station_name, avg_wait_hours FROM v_queue_wait_weekly ORDER BY station_seq, week_start"),
        "lead": query("SELECT week_start, drones_shipped, avg_lead_days, avg_dwell_days FROM v_lead_time_weekly ORDER BY week_start"),
    }


def quality() -> dict[str, pd.DataFrame]:
    weekly = query("SELECT week_start, station_seq, station_code, station_name, inspections, passes, fpy "
                   "FROM v_first_pass_yield_weekly ORDER BY station_seq, week_start")
    lots = query("SELECT lot_id, part_id, station_code, supplier_id, supplier_name, drones_inspected, fails, fail_rate, "
                 "station_fail_rate, lift FROM v_lot_quality ORDER BY lift DESC NULLS LAST")
    flagged = findings.flagged_lots(lots)
    recall = query(
        "WITH d AS (SELECT DISTINCT serial_number FROM clean_drone_part_lots WHERE lot_id = ANY(%s)) "
        "SELECT COUNT(*) AS drones, COUNT(*) FILTER (WHERE f.shipped_ts IS NOT NULL) AS shipped, "
        "COUNT(*) FILTER (WHERE f.serial_number IS NOT NULL AND f.shipped_ts IS NULL) AS packed, "
        "COUNT(*) FILTER (WHERE f.serial_number IS NULL) AS in_line "
        "FROM d LEFT JOIN clean_finished_goods f USING (serial_number)", (list(flagged["lot_id"]),))
    return {
        "weekly": weekly,
        "pareto": query("SELECT station_code, defect_code, fails, pct_of_fails, cum_pct FROM v_defect_pareto ORDER BY fails DESC, defect_code"),
        "lots": lots, "flagged": flagged, "recall": recall,
    }


def inventory() -> dict[str, pd.DataFrame]:
    perf = query("SELECT supplier_id, supplier_name, shipments_received, on_time_rate, in_full_rate, otif_rate, quantity_unverified, "
                 "avg_days_late, p90_days_late FROM v_supplier_performance ORDER BY otif_rate")
    return {
        "risk": query("SELECT * FROM v_inventory_risk ORDER BY cushion_days ASC NULLS LAST"),
        "perf": perf,
        "regular": perf[perf["supplier_id"] != cfg.SPOT_BUY],  # the emergency distributor is not a fair comparison
        "gap": query("SELECT g.part_id, g.part_name, g.station_code, s.station_name, g.days_short_at_line, g.first_day, g.last_day, "
                     "g.avg_warehouse_stock FROM v_line_side_gap g JOIN clean_stations s USING (station_code) ORDER BY g.days_short_at_line DESC"),
    }


def data_quality() -> dict[str, pd.DataFrame]:
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
    return {"results": results, "impact": impact}


def status() -> pd.Series:
    """Headline counts for the Overview: drones started and shipped, and the period covered."""
    return query(
        "SELECT (SELECT COUNT(DISTINCT serial_number) FROM clean_work_orders) AS started, "
        "(SELECT COUNT(*) FROM clean_finished_goods WHERE shipped_ts IS NOT NULL) AS shipped, "
        "(SELECT launch_date FROM v_calendar) AS launch, (SELECT as_of_date FROM v_calendar) AS as_of").iloc[0]
