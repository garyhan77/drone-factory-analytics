from datetime import datetime

import pandas as pd
import pytest

from factory.db import TABLES, apply_schema, load_dataframe


def _existing_tables(conn):
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name LIKE 'raw\\_%'"
    ).fetchall()
    return {name for (name,) in rows}


def test_schema_creates_all_ten_tables(conn):
    assert _existing_tables(conn) == {f"raw_{t}" for t in TABLES}
    assert len(TABLES) == 10


def test_applying_schema_twice_is_safe_and_clears_data(conn):
    load_dataframe(conn, "suppliers", pd.DataFrame({"supplier_id": ["SUP-01"], "supplier_name": ["Ridgeline Hardware"]}))
    apply_schema(conn)
    assert conn.execute("SELECT COUNT(*) FROM raw_suppliers").fetchone()[0] == 0


def test_load_round_trips_values_and_nulls(conn):
    df = pd.DataFrame({
        "wo_id": ["WO-1", "WO-2"],
        "serial_number": ["DF-000001", "DF-000002"],
        "station_code": ["AVN", "AVN"],
        "start_ts": [datetime(2026, 3, 2, 8, 0), datetime(2026, 3, 2, 9, 30)],
        "end_ts": [datetime(2026, 3, 2, 13, 0), pd.NaT],
        "status": ["COMPLETE", "IN_PROGRESS"],
    })
    assert load_dataframe(conn, "work_orders", df) == 2
    rows = conn.execute("SELECT wo_id, start_ts, end_ts, status FROM raw_work_orders ORDER BY wo_id").fetchall()
    assert rows[0] == ("WO-1", datetime(2026, 3, 2, 8, 0), datetime(2026, 3, 2, 13, 0), "COMPLETE")
    assert rows[1] == ("WO-2", datetime(2026, 3, 2, 9, 30), None, "IN_PROGRESS")


def test_load_handles_nullable_integers_and_dates(conn):
    df = pd.DataFrame({
        "shipment_id": ["SHP-1", "SHP-2"],
        "lot_id": ["LOT-1", "LOT-2"],
        "part_id": ["MTR-003", "MTR-003"],
        "order_date": pd.to_datetime(["2026-02-01", "2026-02-10"]).date,
        "expected_date": pd.to_datetime(["2026-02-11", "2026-02-20"]).date,
        "received_date": [pd.to_datetime("2026-02-12").date(), None],
        "qty_expected": [100, 100],
        "qty_received": pd.array([90, pd.NA], dtype="Int64"),
    })
    load_dataframe(conn, "receiving", df)
    rows = conn.execute("SELECT qty_received, received_date FROM raw_receiving ORDER BY shipment_id").fetchall()
    assert rows[0][0] == 90 and rows[0][1] is not None
    assert rows[1] == (None, None)


def test_unknown_table_is_rejected(conn):
    with pytest.raises(ValueError):
        load_dataframe(conn, "not_a_table", pd.DataFrame({"x": [1]}))


SAMPLE_ROWS = {
    "stations": {"station_seq": 1, "station_code": "AFL", "station_name": "Airframe"},
    "suppliers": {"supplier_id": "SUP-01", "supplier_name": "Ridgeline Hardware"},
    "parts": {"part_id": "MTR-003", "part_name": "Prop nut", "supplier_id": "SUP-01",
              "unit_cost": 1.5, "reorder_point": 400, "lead_time_days": 10},
    "bom": {"station_code": "MTR", "part_id": "MTR-003", "qty_per_unit": 2},
    "inventory_snapshots": {"snapshot_date": datetime(2026, 1, 5).date(), "part_id": "MTR-003",
                            "location": "LINE_SIDE", "on_hand": 120},
    "receiving": {"shipment_id": "SHP-1", "lot_id": "LOT-1", "part_id": "MTR-003",
                  "order_date": datetime(2026, 1, 1).date(), "expected_date": datetime(2026, 1, 11).date(),
                  "received_date": None, "qty_expected": 500, "qty_received": None},
    "work_orders": {"wo_id": "WO-1", "serial_number": "DF-000001", "station_code": "AFL",
                    "start_ts": datetime(2026, 1, 5, 6), "end_ts": datetime(2026, 1, 5, 9), "status": "COMPLETE"},
    "inspections": {"inspection_id": "INS-1", "serial_number": "DF-000001", "station_code": "AFL", "attempt": 1,
                    "inspected_ts": datetime(2026, 1, 5, 9), "result": "FAIL", "defect_code": "AFL-RESIN-VOID"},
    "drone_part_lots": {"serial_number": "DF-000001", "station_code": "MTR", "part_id": "MTR-003", "lot_id": "LOT-1"},
    "finished_goods": {"serial_number": "DF-000001", "test_passed_ts": datetime(2026, 1, 9, 12),
                       "packed_ts": datetime(2026, 1, 9, 16), "shipped_ts": None},
}


def test_sample_rows_cover_every_table():
    assert set(SAMPLE_ROWS) == set(TABLES)


@pytest.mark.parametrize("table", TABLES)
def test_every_table_accepts_a_row_with_the_expected_columns(conn, table):
    df = pd.DataFrame([SAMPLE_ROWS[table]])
    assert load_dataframe(conn, table, df) == 1
    assert conn.execute(f"SELECT COUNT(*) FROM raw_{table}").fetchone()[0] == 1
