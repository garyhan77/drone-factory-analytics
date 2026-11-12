"""The queries behind each page, in one place so the Overview and the page it summarises always agree.

Each function returns the DataFrames a page needs. They all go through factory.viz.data.query, which caches by query text,
so a page and the Overview that reuses it cost one database round trip, not two.
"""
from __future__ import annotations

import pandas as pd

from factory import config as cfg

from . import findings
from .data import query


def quality() -> dict[str, pd.DataFrame]:
    lots = query("SELECT q.lot_id, q.part_id, p.part_name, q.station_code, q.supplier_id, q.supplier_name, q.drones_inspected, q.fails, "
                 "q.fail_rate FROM v_lot_quality q JOIN raw_parts p USING (part_id) ORDER BY q.fail_rate DESC")
    flagged = findings.flagged_lots(lots)
    recall = query(
        "WITH d AS (SELECT DISTINCT serial_number FROM raw_drone_part_lots WHERE lot_id = ANY(%s)) "
        "SELECT COUNT(*) AS drones, COUNT(*) FILTER (WHERE f.shipped_ts IS NOT NULL) AS shipped, "
        "COUNT(*) FILTER (WHERE f.serial_number IS NOT NULL AND f.shipped_ts IS NULL) AS packed, "
        "COUNT(*) FILTER (WHERE f.serial_number IS NULL) AS in_line "
        "FROM d LEFT JOIN raw_finished_goods f USING (serial_number)", (list(flagged["lot_id"]),))
    return {
        "lots": lots, "flagged": flagged, "recall": recall,
    }


def inventory() -> dict[str, pd.DataFrame]:
    deliveries = query("SELECT shipment_id, lot_id, part_id, part_name, supplier_id, supplier_name, expected_date, received_date, days_late, "
                       "qty_expected, qty_received, short, emergency FROM v_deliveries ORDER BY expected_date, part_id")
    ridgeline = deliveries[(deliveries["supplier_id"] == cfg.RIDGELINE) & ~deliveries["emergency"]]
    return {"ridgeline": ridgeline, "emergency_lots": int(deliveries["emergency"].sum()),
            "parts": query("SELECT part_id, part_name FROM raw_parts ORDER BY part_id")}
