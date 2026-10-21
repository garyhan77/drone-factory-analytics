"""The clean views and metrics.

Part 1 checks every metric on a tiny factory whose answers can be worked out by hand.
Part 2 checks what the clean views do with each kind of bad row.
Part 3 compares the SQL, run on the data WITH errors, against an independent pandas calculation on the data
WITHOUT them, and checks the story shows up.

The tiny factory: stations AAA, BBB, CCC; drones D1-D4. Monday 2 March 2026 is the first day of work, so
launch_date is 2026-03-02. The newest snapshot is 2026-03-10, the newest timestamp 2026-03-09 11:00.
"""
import os
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from dotenv import load_dotenv

from factory import config as cfg
from factory.build import build
from factory.db import ROOT, apply_views, connect

TINY = """
INSERT INTO raw_stations VALUES (1, 'AAA', 'Alpha'), (2, 'BBB', 'Beta'), (3, 'CCC', 'Gamma');
INSERT INTO raw_suppliers VALUES ('SUP-01', 'Acme'), ('SUP-02', 'Bolt Co');
INSERT INTO raw_parts VALUES ('P1', 'Widget', 'SUP-01', 1, 5, 10), ('P2', 'Gadget', 'SUP-02', 1, 5, 5),
                             ('P3', 'Gizmo', 'SUP-02', 1, 5, 7), ('P4', 'Sprocket', 'SUP-01', 1, 5, 14),
                             ('P5', 'Cog', 'SUP-01', 1, 5, 13);
INSERT INTO raw_bom VALUES ('AAA', 'P1', 2), ('BBB', 'P2', 1), ('BBB', 'P3', 4), ('AAA', 'P4', 1), ('AAA', 'P5', 7);

INSERT INTO raw_work_orders VALUES
  ('WO1', 'D1', 'AAA', '2026-03-02 08:00', '2026-03-02 10:00', 'COMPLETE'),
  ('WO2', 'D1', 'BBB', '2026-03-02 12:00', '2026-03-02 16:00', 'COMPLETE'),
  ('WO3', 'D1', 'CCC', '2026-03-03 08:00', '2026-03-03 10:00', 'COMPLETE'),
  ('WO4', 'D2', 'AAA', '2026-03-02 09:00', '2026-03-02 12:00', 'COMPLETE'),
  ('WO5', 'D2', 'BBB', '2026-03-03 08:00', '2026-03-03 14:00', 'COMPLETE'),
  ('WO6', 'D2', 'CCC', '2026-03-04 08:00', '2026-03-04 09:00', 'COMPLETE'),
  ('WO7', 'D3', 'AAA', '2026-03-09 08:00', '2026-03-09 10:00', 'COMPLETE'),
  ('WO8', 'D3', 'BBB', '2026-03-09 10:00', NULL, 'IN_PROGRESS'),
  ('WO9', 'D4', 'AAA', '2026-03-09 09:00', '2026-03-09 11:00', 'COMPLETE');

INSERT INTO raw_inspections VALUES
  ('I1', 'D1', 'AAA', 1, '2026-03-02 10:00', 'PASS', NULL),
  ('I2', 'D1', 'BBB', 1, '2026-03-02 15:30', 'FAIL', 'BBB-X'),
  ('I3', 'D1', 'BBB', 2, '2026-03-02 16:00', 'PASS', NULL),
  ('I4', 'D1', 'CCC', 1, '2026-03-03 10:00', 'PASS', NULL),
  ('I5', 'D2', 'AAA', 1, '2026-03-02 12:00', 'PASS', NULL),
  ('I6', 'D2', 'BBB', 1, '2026-03-03 14:00', 'PASS', NULL),
  ('I7', 'D2', 'CCC', 1, '2026-03-04 09:00', 'PASS', NULL),
  ('I8', 'D3', 'AAA', 1, '2026-03-09 10:00', 'FAIL', 'AAA-X'),
  ('I9', 'D4', 'AAA', 1, '2026-03-09 11:00', 'PASS', NULL);

INSERT INTO raw_receiving VALUES
  ('S0', 'LOT-0', 'SUP-01', 'P1', '2026-02-10', '2026-02-20', '2026-02-20', 100, 100),
  ('S1', 'LOT-A', 'SUP-01', 'P1', '2026-02-20', '2026-03-04', '2026-03-04', 100, 100),
  ('S2', 'LOT-C', 'SUP-01', 'P1', '2026-02-20', '2026-03-05', '2026-03-08', 100, 80),
  ('S3', 'LOT-B', 'SUP-01', 'P1', '2026-02-25', '2026-03-06', '2026-03-06', 50, 50),
  ('S4', 'LOT-D', 'SUP-02', 'P2', '2026-02-25', '2026-03-04', '2026-03-04', 100, 100),
  ('S5', 'LOT-E', 'SUP-02', 'P2', '2026-02-28', '2026-03-04', NULL, 100, NULL);

INSERT INTO raw_inventory_snapshots VALUES
  ('2026-03-05', 'P1', 'WAREHOUSE', 1), ('2026-03-05', 'P1', 'LINE_SIDE', 0),
  ('2026-03-06', 'P1', 'WAREHOUSE', 8), ('2026-03-06', 'P1', 'LINE_SIDE', 1),
  ('2026-03-07', 'P1', 'WAREHOUSE', 8), ('2026-03-07', 'P1', 'LINE_SIDE', 0),
  ('2026-03-09', 'P1', 'WAREHOUSE', 8), ('2026-03-09', 'P1', 'LINE_SIDE', 2),
  ('2026-03-10', 'P1', 'WAREHOUSE', 8), ('2026-03-10', 'P1', 'LINE_SIDE', 2),
  ('2026-03-10', 'P2', 'WAREHOUSE', 3), ('2026-03-10', 'P2', 'LINE_SIDE', 0),
  ('2026-03-10', 'P3', 'WAREHOUSE', 0), ('2026-03-10', 'P3', 'LINE_SIDE', 0),
  ('2026-03-10', 'P4', 'WAREHOUSE', 4), ('2026-03-10', 'P4', 'LINE_SIDE', 0),
  ('2026-03-10', 'P5', 'WAREHOUSE', 31), ('2026-03-10', 'P5', 'LINE_SIDE', 0);

INSERT INTO raw_drone_part_lots VALUES
  ('D1', 'AAA', 'P1', 'LOT-A'), ('D2', 'AAA', 'P1', 'LOT-A'), ('D3', 'AAA', 'P1', 'LOT-B'), ('D4', 'AAA', 'P1', 'LOT-B'),
  ('D1', 'BBB', 'P2', 'LOT-D'), ('D2', 'BBB', 'P2', 'LOT-D'), ('D3', 'BBB', 'P2', 'LOT-D');

INSERT INTO raw_finished_goods VALUES
  ('D1', '2026-03-03 10:00', '2026-03-03 14:00', '2026-03-03 16:00'),
  ('D2', '2026-03-04 09:00', '2026-03-04 17:00', NULL);
"""
# lots LOT-A and LOT-B need receiving rows for the supplier lookup: S1 and S3 above carry them; LOT-D is on S4.


@pytest.fixture
def tiny(conn):
    apply_views(conn)
    conn.execute(TINY)
    conn.commit()
    return conn


def rows(conn, sql):
    """Query rows with numbers as floats, so they can be compared with pytest.approx."""
    return [tuple(float(v) if hasattr(v, "as_tuple") else v for v in row) for row in conn.execute(sql).fetchall()]


def day(s):
    from datetime import date
    return date.fromisoformat(s)


# ---------------------------------------------------------------------------- part 1: every metric, by hand

def test_reference_dates_are_found_from_the_data(tiny):
    launch, as_of, as_of_ts = rows(tiny, "SELECT launch_date, as_of_date, as_of_ts FROM v_calendar")[0]
    assert (launch, as_of) == (day("2026-03-02"), day("2026-03-10"))
    assert as_of_ts.isoformat() == "2026-03-09T11:00:00"


def test_first_pass_yield_counts_first_attempts_only(tiny):
    got = rows(tiny, "SELECT week_start, station_code, inspections, passes, fpy FROM v_first_pass_yield_weekly ORDER BY 1, 2")
    # Week of 2 March: AAA 2 of 2 pass; BBB 1 of 2 (D1 failed first time, its rework pass does not count); CCC 2 of 2.
    # Week of 9 March: AAA 1 of 2 (D3 failed).
    assert got == [(day("2026-03-02"), "AAA", 2, 2, 1.0), (day("2026-03-02"), "BBB", 2, 1, 0.5),
                   (day("2026-03-02"), "CCC", 2, 2, 1.0), (day("2026-03-09"), "AAA", 2, 1, 0.5)]


def test_the_defect_pareto_ranks_failures_and_accumulates(tiny):
    assert rows(tiny, "SELECT defect_code, fails, pct_of_fails, cum_pct FROM v_defect_pareto") == [
        ("AAA-X", 1, 0.5, 0.5), ("BBB-X", 1, 0.5, 1.0)]
    assert rows(tiny, "SELECT week_start, defect_code, fails FROM v_defects_weekly ORDER BY 1") == [
        (day("2026-03-02"), "BBB-X", 1), (day("2026-03-09"), "AAA-X", 1)]


def test_cycle_time_and_queue_wait_per_station(tiny):
    got = {r[0]: r[1:] for r in rows(tiny, """SELECT station_code, completed_orders, median_cycle_hours, p90_cycle_hours,
                                              avg_wait_hours, p90_wait_hours FROM v_station_summary""")}
    # AAA cycles 2, 3, 2, 2 h: median 2.0; p90 sits 70% of the way from 2 to 3 = 2.7. First station, so no wait.
    assert got["AAA"][:3] == (4, 2.0, 2.7) and got["AAA"][3] is None
    # BBB cycles 4 and 6 (D3 is still running): median 5, p90 = 4 + 0.9 x 2 = 5.8.
    # BBB waits 2 (D1: 10:00 to 12:00), 20 (D2: 12:00 Mon to 08:00 Tue) and 0 (D3): mean 7.33, p90 = 2 + 0.8 x 18 = 16.4.
    assert got["BBB"] == (2, 5.0, 5.8, pytest.approx(7.33, abs=0.005), 16.4)
    # CCC cycles 2 and 1: median 1.5, p90 1.9. Waits 16 (D1) and 18 (D2): mean 17, p90 = 16 + 0.9 x 2 = 17.8.
    assert got["CCC"] == (2, 1.5, 1.9, 17.0, 17.8)


def test_weekly_wait_and_weekly_output(tiny):
    assert rows(tiny, "SELECT week_start, station_code, avg_wait_hours FROM v_queue_wait_weekly ORDER BY 1, 2") == [
        (day("2026-03-02"), "BBB", 11.0), (day("2026-03-02"), "CCC", 17.0), (day("2026-03-09"), "BBB", 0.0)]
    # Started = jobs at the first station; completed = jobs finished at the last station.
    assert rows(tiny, "SELECT week_start, units_started, units_completed FROM v_weekly_output ORDER BY 1") == [
        (day("2026-03-02"), 2, 2), (day("2026-03-09"), 2, 0)]


def test_supplier_performance_ignores_pre_launch_and_in_transit_shipments(tiny):
    got = {r[0]: r[1:] for r in rows(tiny, """SELECT supplier_id, shipments_received, on_time_rate, in_full_rate, otif_rate,
                                              avg_days_late, p90_days_late FROM v_supplier_performance""")}
    # SUP-01: S0 is pre-launch (left out); S1 fine, S2 three days late and short, S3 fine. Lateness 0, 3, 0: p90 = 0.8 x 3 = 2.4.
    assert got["SUP-01"] == (3, pytest.approx(0.6667, abs=1e-4), pytest.approx(0.6667, abs=1e-4), pytest.approx(0.6667, abs=1e-4), 1.0, 2.4)
    # SUP-02: S4 fine; S5 is still in transit.
    assert got["SUP-02"] == (1, 1.0, 1.0, 1.0, 0.0, 0.0)


def test_inventory_risk_compares_days_of_stock_with_a_bad_delivery(tiny):
    got = {r[0]: r[1:] for r in rows(tiny, """SELECT part_id, on_hand, daily_demand, days_remaining, days_to_next,
                                              arrival_avg_days, arrival_bad_case_days, cushion_days, at_risk_average, risk_status
                                              FROM v_inventory_risk""")}
    # Demand: AAA started 4 drones and BBB 3 in the 14 days to 10 March.
    # P1 (qty 2, SUP-01 lateness avg 1, p90 2.4): 0.57 a day, 10 in stock = 17.5 days; no open shipment, lead time 10;
    #    average arrival 10 + 1 = 11, bad case 10 + ceil(2.4) = 13; cushion 4.5, under 5 so WATCH.
    assert got["P1"] == (10, 0.57, 17.5, 10, 11, 13, 4.5, False, "WATCH")
    # P2 (qty 1, SUP-02 never late): the open shipment is overdue, so it is due now; 3 in stock = 14 days. OK.
    assert got["P2"] == (3, 0.21, 14.0, 0, 0, 0, 14.0, False, "OK")
    # P3 (qty 4): nothing in stock, stock is needed: STOCKOUT.
    assert got["P3"][0] == 0 and got["P3"][-1] == "STOCKOUT" and got["P3"][6] == -7.0
    # P4 (qty 1, SUP-01): 4 in stock = 14 days against a 14-day lead time. Average arrival 15, bad case 17: AT RISK.
    assert got["P4"] == (4, 0.29, 14.0, 14, 15, 17, -3.0, True, "AT RISK")
    # P5 (qty 7, SUP-01): 2.0 a day, 31 in stock = 15.5 days; lead time 13. Average arrival 13 + 1 = 14, bad case 13 + 3 = 16.
    # It looks fine against an average delivery (15.5 days is more than 14) but is AT RISK against a bad one (less than 16):
    # the whole point of planning for the bad case.
    assert got["P5"] == (31, 2.0, 15.5, 13, 14, 16, -0.5, False, "AT RISK")


def test_right_part_wrong_place_needs_warehouse_stock_and_an_empty_shelf_on_a_weekday(tiny):
    got = rows(tiny, "SELECT part_id, station_code, days_short_at_line, first_day, last_day, avg_warehouse_stock FROM v_line_side_gap ORDER BY 1")
    # P1 (needs 2 a drone): 6 March has 8 in the warehouse and 1 on the shelf. 5 March (warehouse holds 1), Saturday 7 March
    # (weekend) and later days (shelf holds 2) do not count. P2 and P4 on 10 March: stock in the warehouse, none on the shelf.
    # P5 (needs 7) has 31 in the warehouse and none on the shelf. P3 has nothing anywhere.
    assert got == [("P1", "AAA", 1, day("2026-03-06"), day("2026-03-06"), 8.0),
                   ("P2", "BBB", 1, day("2026-03-10"), day("2026-03-10"), 3.0),
                   ("P4", "AAA", 1, day("2026-03-10"), day("2026-03-10"), 4.0),
                   ("P5", "AAA", 1, day("2026-03-10"), day("2026-03-10"), 31.0)]


def test_lot_quality_compares_each_lots_failure_rate_with_its_station(tiny):
    got = {r[0]: r[1:] for r in rows(tiny, """SELECT lot_id, station_code, supplier_name, drones_inspected, fails, fail_rate,
                                              station_fail_rate, lift FROM v_lot_quality""")}
    # AAA: D3 failed, 3 others passed, so the station rate is 0.25. LOT-A (D1, D2) had no failures; LOT-B (D3, D4) had one.
    assert got["LOT-A"] == ("AAA", "Acme", 2, 0, 0.0, 0.25, 0.0)
    assert got["LOT-B"] == ("AAA", "Acme", 2, 1, 0.5, 0.25, 2.0)
    # BBB: D1 failed, D2 passed (D3 has not been inspected yet): rate 0.5, and LOT-D is exactly average.
    assert got["LOT-D"] == ("BBB", "Bolt Co", 2, 1, 0.5, 0.5, 1.0)


def test_recall_scope_shows_where_every_drone_with_a_lot_is_now(tiny):
    got = {r[0]: r[1:] for r in rows(tiny, """SELECT lot_id, drones_containing_lot, already_shipped, packed_not_shipped,
                                              still_in_the_line, first_installed, last_installed FROM v_recall_scope""")}
    assert got["LOT-A"] == (2, 1, 1, 0, day("2026-03-02"), day("2026-03-02"))   # D1 shipped, D2 packed
    assert got["LOT-B"] == (2, 0, 0, 2, day("2026-03-09"), day("2026-03-09"))   # D3 and D4 still in the line
    assert got["LOT-D"] == (3, 1, 1, 1, day("2026-03-02"), day("2026-03-09"))   # D1 shipped, D2 packed, D3 in the line


def test_lead_time_and_dwell_for_shipped_drones_and_the_age_of_the_rest(tiny):
    # D1: started 2 March 08:00, passed test 3 March 10:00, shipped 3 March 16:00 = 32 hours, of which 6 were after the test.
    assert rows(tiny, "SELECT serial_number, lead_days, dwell_days FROM v_drone_delivery") == [("D1", pytest.approx(1.3333, abs=1e-4), 0.25)]
    assert rows(tiny, "SELECT week_start, drones_shipped, avg_lead_days, avg_dwell_days FROM v_lead_time_weekly") == [(day("2026-03-02"), 1, 1.3, 0.3)]
    # As of 9 March 11:00: D2 is packed and waiting (7 days 2 hours old); D3 is part-way through BBB (3 hours);
    # D4 finished AAA and is queued for BBB (2 hours).
    assert rows(tiny, "SELECT serial_number, stage, age_days FROM v_wip_age ORDER BY 1") == [
        ("D2", "AWAITING SHIPMENT", 7.1), ("D3", "In Beta", 0.1), ("D4", "Waiting for Beta", 0.1)]
    assert rows(tiny, "SELECT stage, drones, avg_age_days, max_age_days FROM v_wip_by_stage ORDER BY 1") == [
        ("AWAITING SHIPMENT", 1, 7.1, 7.1), ("In Beta", 1, 0.1, 0.1), ("Waiting for Beta", 1, 0.1, 0.1)]


# ---------------------------------------------------------------------------- part 2: what the clean views do

def test_a_rekeyed_duplicate_work_order_is_dropped_and_the_original_kept(tiny):
    tiny.execute("INSERT INTO raw_work_orders VALUES ('WO90', 'D1', 'AAA', '2026-03-02 08:00', '2026-03-02 10:00', 'COMPLETE')")
    ids = {r[0] for r in rows(tiny, "SELECT wo_id FROM clean_work_orders")}
    assert "WO90" not in ids and "WO1" in ids and len(ids) == 9
    assert rows(tiny, "SELECT units_started FROM v_weekly_output WHERE week_start = '2026-03-02'") == [(2,)]  # not 3


def test_a_job_that_ends_before_it_starts_keeps_its_place_but_not_its_end_time(tiny):
    tiny.execute("""INSERT INTO raw_work_orders VALUES
        ('WO91', 'D5', 'AAA', '2026-03-02 08:00', '2026-03-02 09:00', 'COMPLETE'),
        ('WO92', 'D5', 'BBB', '2026-03-02 10:00', '2026-03-02 09:00', 'COMPLETE'),
        ('WO93', 'D5', 'CCC', '2026-03-03 08:00', '2026-03-03 09:00', 'COMPLETE')""")
    assert rows(tiny, "SELECT end_ts, end_unknown, status FROM clean_work_orders WHERE wo_id = 'WO92'") == [(None, True, "COMPLETE")]
    flow = {r[0]: r[1:] for r in rows(tiny, "SELECT wo_id, cycle_hours, queue_wait_hours FROM v_work_order_flow WHERE serial_number = 'D5'")}
    assert flow["WO92"] == (None, 1.0)   # no cycle time, but it did start an hour after AAA finished
    assert flow["WO93"][1] is None        # the wait is blank; excluding the row would have measured it from AAA (23 hours)
    assert rows(tiny, "SELECT completed_orders FROM v_station_summary WHERE station_code = 'BBB'") == [(2,)]  # D5's BBB is not counted


def test_inspections_for_unknown_drones_are_dropped_and_missing_codes_are_labelled_not_lost(tiny):
    tiny.execute("""INSERT INTO raw_inspections VALUES
        ('I90', 'D9', 'AAA', 1, '2026-03-09 12:00', 'PASS', NULL),
        ('I91', 'D2', 'AAA', 1, '2026-03-09 12:00', 'FAIL', NULL),
        ('I92', 'D2', 'AAA', 1, '2026-03-09 12:00', 'FAIL', ''),
        ('I93', 'D2', 'AAA', 1, '2026-03-09 12:00', 'FAIL', '   ')""")
    assert rows(tiny, "SELECT COUNT(*) FROM clean_inspections WHERE inspection_id = 'I90'") == [(0,)]
    assert rows(tiny, "SELECT inspection_id, defect_code, code_was_missing FROM clean_inspections WHERE inspection_id IN ('I91','I92','I93') ORDER BY 1") == [
        ("I91", "AAA-UNCODED", True), ("I92", "AAA-UNCODED", True), ("I93", "AAA-UNCODED", True)]
    assert rows(tiny, "SELECT fails FROM v_defect_pareto WHERE defect_code = 'AAA-UNCODED'") == [(3,)]


def test_a_negative_stock_reading_is_replaced_by_the_last_good_one(tiny):
    tiny.execute("""INSERT INTO raw_inventory_snapshots VALUES
        ('2026-03-05', 'P2', 'LINE_SIDE', 4), ('2026-03-06', 'P2', 'LINE_SIDE', -9), ('2026-03-09', 'P2', 'LINE_SIDE', 2),
        ('2026-03-05', 'P3', 'WAREHOUSE', -7)""")
    assert rows(tiny, "SELECT on_hand, repaired FROM clean_inventory_snapshots WHERE part_id = 'P2' AND location = 'LINE_SIDE' AND snapshot_date = '2026-03-06'") == [(4, True)]
    assert rows(tiny, "SELECT on_hand, repaired FROM clean_inventory_snapshots WHERE part_id = 'P2' AND location = 'LINE_SIDE' AND snapshot_date = '2026-03-09'") == [(2, False)]
    # A negative FIRST reading has no earlier good value to carry forward, so that row is dropped.
    assert rows(tiny, "SELECT COUNT(*) FROM clean_inventory_snapshots WHERE part_id = 'P3' AND snapshot_date = '2026-03-05'") == [(0,)]
    assert rows(tiny, "SELECT MIN(on_hand) FROM clean_inventory_snapshots") == [(0,)]


def test_an_over_received_shipment_is_kept_with_the_quantity_capped(tiny):
    tiny.execute("INSERT INTO raw_receiving VALUES ('S6', 'LOT-F', 'SUP-02', 'P2', '2026-02-28', '2026-03-05', '2026-03-05', 100, 130)")
    assert rows(tiny, "SELECT qty_received, qty_capped FROM clean_receiving WHERE shipment_id = 'S6'") == [(100, True)]
    assert rows(tiny, "SELECT qty_capped FROM clean_receiving WHERE shipment_id = 'S4'") == [(False,)]
    # The shipment still counts toward on-time, and as in full (never as better than in full).
    # The shipment still counts toward on-time, but its quantity cannot be trusted, so it is left out of in-full and OTIF.
    assert rows(tiny, "SELECT shipments_received, on_time_rate, in_full_rate, otif_rate, quantity_unverified FROM v_supplier_performance WHERE supplier_id = 'SUP-02'") == [(2, 1.0, 1.0, 1.0, 1)]


def test_a_capped_shipment_cannot_flatter_a_supplier_that_was_really_short(tiny):
    """The shipment arrived late and its recorded quantity is over the expected one. Whatever the truth was, it earns no credit."""
    tiny.execute("INSERT INTO raw_receiving VALUES ('S6', 'LOT-F', 'SUP-02', 'P2', '2026-02-28', '2026-03-05', '2026-03-07', 100, 130)")
    got = rows(tiny, "SELECT shipments_received, on_time_rate, in_full_rate, otif_rate, quantity_unverified FROM v_supplier_performance WHERE supplier_id = 'SUP-02'")
    assert got == [(2, 0.5, 1.0, 1.0, 1)]   # late counts against it; only S4 speaks for quantity


def test_pre_launch_shipments_are_flagged(tiny):
    assert rows(tiny, "SELECT shipment_id FROM clean_receiving WHERE is_pre_launch") == [("S0",)]


# ---------------------------------------------------------------------------- part 3: the generated data

@pytest.fixture(scope="module")
def built():
    load_dotenv(ROOT / ".env")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    if not url.rstrip("/").rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail(f"TEST_DATABASE_URL must point at a database ending in _test, got: {url}")
    data = build(url=url, write_files=False)
    with connect(url) as conn:
        yield data, conn


def sql_frame(conn, sql):
    cur = conn.execute(sql)
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    for col in df.columns:
        if df[col].dtype == object and len(df) and hasattr(df[col].iloc[0], "as_tuple"):
            df[col] = df[col].astype(float)
    return df


def monday(ts):
    return (ts.dt.normalize() - pd.to_timedelta(ts.dt.dayofweek, unit="D")).dt.date


def test_first_pass_yield_matches_pandas_on_the_clean_data(built):
    data, conn = built
    ins, wo = data.clean["inspections"], data.clean["stations"]
    first = ins[ins["attempt"] == 1].assign(week_start=lambda d: monday(d["inspected_ts"]))
    want = (first.groupby(["week_start", "station_code"]).agg(inspections=("result", "size"), passes=("result", lambda s: (s == "PASS").sum()))
            .reset_index().sort_values(["week_start", "station_code"]).reset_index(drop=True))
    got = sql_frame(conn, "SELECT week_start, station_code, inspections, passes FROM v_first_pass_yield_weekly ORDER BY 1, 2")
    pd.testing.assert_frame_equal(got, want, check_dtype=False)


def test_weekly_output_matches_pandas_on_the_clean_data(built):
    data, conn = built
    wo = data.clean["work_orders"]
    started = wo[wo["station_code"] == "AFL"].assign(week_start=lambda d: monday(d["start_ts"])).groupby("week_start").size()
    done = wo[(wo["station_code"] == "FNT") & wo["end_ts"].notna()].assign(week_start=lambda d: monday(d["end_ts"])).groupby("week_start").size()
    want = pd.DataFrame({"units_started": started, "units_completed": done}).fillna(0).astype(int)
    got = sql_frame(conn, "SELECT week_start, units_started, units_completed FROM v_weekly_output").set_index("week_start").sort_index()
    pd.testing.assert_frame_equal(got, want.sort_index(), check_dtype=False)


def test_supplier_performance_matches_pandas_on_the_clean_data(built):
    data, conn = built
    r = data.clean["receiving"]
    launch = data.clean["work_orders"]["start_ts"].min().date()
    r = r[r["received_date"].notna() & (pd.to_datetime(r["received_date"]).dt.date >= launch)].copy()
    late = (pd.to_datetime(r["received_date"]) - pd.to_datetime(r["expected_date"])).dt.days.clip(lower=0)
    r["on_time"], r["in_full"] = late == 0, r["qty_received"].astype(float) >= r["qty_expected"]
    r["late"] = late
    # The over-received shipments are the ones whose quantity cannot be trusted, so they are left out of in-full and OTIF.
    trusted = ~r["shipment_id"].isin(data.answer_key["over_receipt"])
    r["otif_ok"] = r["on_time"] & r["in_full"]
    want = r.groupby("supplier_id").agg(n=("shipment_id", "size"), on_time=("on_time", "mean"), avg_late=("late", "mean"),
                                        p90=("late", lambda s: np.percentile(s, 90)))
    want["in_full"] = r[trusted].groupby("supplier_id")["in_full"].mean()
    want["otif"] = r[trusted].groupby("supplier_id")["otif_ok"].mean()
    got = sql_frame(conn, "SELECT supplier_id, shipments_received, on_time_rate, in_full_rate, otif_rate, avg_days_late, p90_days_late FROM v_supplier_performance").set_index("supplier_id")
    assert list(got.index) and set(got.index) == set(want.index)
    for sup in want.index:
        w, g = want.loc[sup], got.loc[sup]
        assert g["shipments_received"] == w["n"]
        assert g["on_time_rate"] == pytest.approx(w["on_time"], abs=1e-4) and g["in_full_rate"] == pytest.approx(w["in_full"], abs=1e-4)
        assert g["otif_rate"] == pytest.approx(w["otif"], abs=1e-4)
        assert g["avg_days_late"] == pytest.approx(w["avg_late"], abs=0.006) and g["p90_days_late"] == pytest.approx(w["p90"], abs=0.006)  # SQL rounds to 2 places


def test_lead_time_and_dwell_match_pandas_on_the_clean_data(built):
    data, conn = built
    fg, wo = data.clean["finished_goods"], data.clean["work_orders"]
    first = wo[wo["station_code"] == "AFL"].groupby("serial_number")["start_ts"].min()
    s = fg[fg["shipped_ts"].notna()].copy()
    s["lead"] = (s["shipped_ts"] - s["serial_number"].map(first)).dt.total_seconds() / 86400
    s["dwell"] = (s["shipped_ts"] - s["test_passed_ts"]).dt.total_seconds() / 86400
    s["week_start"] = monday(s["shipped_ts"])
    want = s.groupby("week_start").agg(n=("serial_number", "size"), lead=("lead", "mean"), dwell=("dwell", "mean"))
    got = sql_frame(conn, "SELECT week_start, drones_shipped, avg_lead_days, avg_dwell_days FROM v_lead_time_weekly").set_index("week_start").sort_index()
    assert (got["drones_shipped"].to_numpy() == want["n"].to_numpy()).all()
    assert np.allclose(got["avg_lead_days"].astype(float), want["lead"], atol=0.051)
    assert np.allclose(got["avg_dwell_days"].astype(float), want["dwell"], atol=0.051)


def test_recall_scope_for_emergency_lots_matches_pandas_on_the_clean_data(built):
    data, conn = built
    lots, fg = data.clean["drone_part_lots"], data.clean["finished_goods"].set_index("serial_number")
    sub = lots[lots["lot_id"].str.startswith(cfg.SUBSTITUTE_LOT_PREFIX)]
    want = sub.groupby("lot_id").apply(lambda g: pd.Series({
        "drones": g["serial_number"].nunique(),
        "shipped": sum(1 for x in set(g["serial_number"]) if x in fg.index and pd.notna(fg.loc[x, "shipped_ts"])),
        "in_line": sum(1 for x in set(g["serial_number"]) if x not in fg.index)}), include_groups=False)
    got = sql_frame(conn, "SELECT lot_id, drones_containing_lot, already_shipped, still_in_the_line FROM v_recall_scope WHERE lot_id LIKE 'SUB-%'").set_index("lot_id").sort_index()
    assert list(got.index) == list(want.sort_index().index) and len(got) >= 3
    assert (got["drones_containing_lot"].to_numpy() == want.sort_index()["drones"].to_numpy()).all()
    assert (got["already_shipped"].to_numpy() == want.sort_index()["shipped"].to_numpy()).all()
    assert (got["still_in_the_line"].to_numpy() == want.sort_index()["in_line"].to_numpy()).all()


def test_station_cycle_times_match_pandas_except_where_end_times_were_lost(built):
    data, conn = built
    wo = data.clean["work_orders"]
    done = wo[wo["end_ts"].notna()].assign(cycle=lambda d: (d["end_ts"] - d["start_ts"]).dt.total_seconds() / 3600)
    got = sql_frame(conn, "SELECT station_code, completed_orders, median_cycle_hours FROM v_station_summary").set_index("station_code")
    for code, grp in done.groupby("station_code"):
        lost = len(data.answer_key["end_before_start"]) if code == "AVN" else 0
        assert got.loc[code, "completed_orders"] == len(grp) - lost
        if code != "AVN":
            assert got.loc[code, "median_cycle_hours"] == pytest.approx(grp["cycle"].median(), abs=0.005)


# ---------------------------------------------------------------------------- the story, from the metrics

def test_avionics_is_the_bottleneck_and_its_queue_grows(built):
    _, conn = built
    summary = sql_frame(conn, "SELECT station_code, avg_wait_hours, median_cycle_hours FROM v_station_summary").set_index("station_code")
    assert summary["avg_wait_hours"].drop("AFL").idxmax() == "AVN" and summary["median_cycle_hours"].idxmax() == "AVN"
    weekly = sql_frame(conn, "SELECT week_start, avg_wait_hours FROM v_queue_wait_weekly WHERE station_code = 'AVN' ORDER BY 1")
    assert weekly["avg_wait_hours"].iloc[-3:].mean() > 5 * weekly["avg_wait_hours"].iloc[:8].mean()
    stage = sql_frame(conn, "SELECT stage, drones FROM v_wip_by_stage ORDER BY drones DESC")
    assert stage["stage"].iloc[0] == "Waiting for Avionics"


def test_ridgeline_has_the_worst_delivery_record_and_the_spot_distributor_the_best(built):
    _, conn = built
    perf = sql_frame(conn, "SELECT supplier_name, otif_rate FROM v_supplier_performance ORDER BY otif_rate")
    assert perf["supplier_name"].iloc[0] == "Ridgeline Hardware" and perf["supplier_name"].iloc[-1] == "Spot-Buy Distributor"


def test_the_emergency_lots_stand_out_in_lot_quality_and_all_have_shipped(built):
    _, conn = built
    lots = sql_frame(conn, "SELECT lot_id, lift, drones_inspected FROM v_lot_quality WHERE drones_inspected >= 10 ORDER BY lift DESC")
    assert lots["lot_id"].iloc[:3].str.startswith("SUB-").all() and lots["lift"].iloc[0] > 3
    recall = sql_frame(conn, "SELECT already_shipped, drones_containing_lot FROM v_recall_scope WHERE lot_id LIKE 'SUB-%'")
    assert (recall["already_shipped"] == recall["drones_containing_lot"]).all()


def test_lead_time_grows_while_dwell_stays_flat(built):
    _, conn = built
    w = sql_frame(conn, "SELECT week_start, avg_lead_days, avg_dwell_days FROM v_lead_time_weekly ORDER BY 1")
    early, late = w.iloc[3:9], w.iloc[-7:-1]
    assert late["avg_lead_days"].mean() > 3 * early["avg_lead_days"].mean()
    assert late["avg_dwell_days"].mean() == pytest.approx(early["avg_dwell_days"].mean(), rel=0.3)


def test_the_stock_risk_list_ranks_ridgeline_parts_most_urgent_and_wing_assembly_starves_at_the_line(built):
    _, conn = built
    risk = sql_frame(conn, "SELECT supplier_name, cushion_days, risk_status FROM v_inventory_risk ORDER BY cushion_days")
    assert (risk["supplier_name"].iloc[:3] == "Ridgeline Hardware").all()
    assert (risk["risk_status"].isin(["AT RISK", "STOCKOUT"])).sum() >= 5
    gap = sql_frame(conn, "SELECT station_code, SUM(days_short_at_line) AS days FROM v_line_side_gap GROUP BY 1 ORDER BY 2 DESC")
    assert gap["station_code"].iloc[0] == "WNG"


def test_the_clean_layer_changes_exactly_what_the_policy_says(built):
    data, conn = built
    count = lambda sql: conn.execute(sql).fetchone()[0]
    assert count("SELECT COUNT(*) FROM clean_work_orders") == len(data.tables["work_orders"]) - len(data.answer_key["duplicate_work_orders"])
    assert count("SELECT COUNT(*) FROM clean_work_orders WHERE end_unknown") == len(data.answer_key["end_before_start"])
    assert count("SELECT COUNT(*) FROM clean_inspections") == len(data.tables["inspections"]) - len(data.answer_key["orphan_inspections"])
    assert count("SELECT COUNT(*) FROM clean_inspections WHERE code_was_missing") == len(data.answer_key["missing_defect_code"])
    assert count("SELECT COUNT(*) FROM clean_inventory_snapshots WHERE repaired") == len(data.answer_key["negative_inventory"])
    assert count("SELECT MIN(on_hand) FROM clean_inventory_snapshots") == 0
    assert count("SELECT COUNT(*) FROM clean_receiving WHERE qty_capped") == len(data.answer_key["over_receipt"])
    assert count("SELECT COUNT(*) FROM clean_receiving WHERE qty_received > qty_expected") == 0
