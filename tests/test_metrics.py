"""The metric views.

Part 1 checks every metric on a tiny factory whose answers can be worked out by hand.
Part 2 compares the SQL, run on the generated data, against an independent pandas calculation, and checks the story shows up.

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


def test_deliveries_ignore_pre_launch_and_in_transit_shipments(tiny):
    got = rows(tiny, "SELECT lot_id, supplier_id, days_late, short, emergency FROM v_deliveries ORDER BY lot_id")
    # S0 (LOT-0) is pre-launch and S5 (LOT-E) is still in transit, so both are left out.
    # LOT-C arrived three days late and short; the others were on time and in full.
    assert got == [("LOT-A", "SUP-01", 0, False, False), ("LOT-B", "SUP-01", 0, False, False), ("LOT-C", "SUP-01", 3, True, False),
                   ("LOT-D", "SUP-02", 0, False, False)]


def test_lot_quality_gives_each_lots_failure_rate(tiny):
    got = {r[0]: r[1:] for r in rows(tiny, """SELECT lot_id, station_code, supplier_name, drones_inspected, fails, fail_rate
                                              FROM v_lot_quality""")}
    # AAA: LOT-A (D1, D2) had no failures; LOT-B (D3, D4) had one (D3).
    assert got["LOT-A"] == ("AAA", "Acme", 2, 0, 0.0)
    assert got["LOT-B"] == ("AAA", "Acme", 2, 1, 0.5)
    # BBB: D1 failed, D2 passed (D3 has not been inspected yet).
    assert got["LOT-D"] == ("BBB", "Bolt Co", 2, 1, 0.5)


def test_recall_scope_shows_where_every_drone_with_a_lot_is_now(tiny):
    got = {r[0]: r[1:] for r in rows(tiny, """SELECT lot_id, drones_containing_lot, already_shipped, packed_not_shipped,
                                              still_in_the_line, first_installed, last_installed FROM v_recall_scope""")}
    assert got["LOT-A"] == (2, 1, 1, 0, day("2026-03-02"), day("2026-03-02"))   # D1 shipped, D2 packed
    assert got["LOT-B"] == (2, 0, 0, 2, day("2026-03-09"), day("2026-03-09"))   # D3 and D4 still in the line
    assert got["LOT-D"] == (3, 1, 1, 1, day("2026-03-02"), day("2026-03-09"))   # D1 shipped, D2 packed, D3 in the line


# ---------------------------------------------------------------------------- part 2: the generated data

@pytest.fixture(scope="module")
def built():
    load_dotenv(ROOT / ".env")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    if not url.rstrip("/").rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail(f"TEST_DATABASE_URL must point at a database ending in _test, got: {url}")
    data = build(url=url)
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


def test_deliveries_match_pandas_on_the_generated_data(built):
    data, conn = built
    r = data.tables["receiving"]
    launch = data.tables["work_orders"]["start_ts"].min().date()
    r = r[r["received_date"].notna() & (pd.to_datetime(r["received_date"]).dt.date >= launch)].copy()
    r["late"] = (pd.to_datetime(r["received_date"]) - pd.to_datetime(r["expected_date"])).dt.days.clip(lower=0)
    got = sql_frame(conn, "SELECT shipment_id, days_late, short, emergency FROM v_deliveries ORDER BY shipment_id").set_index("shipment_id")
    r = r.set_index("shipment_id").sort_index()
    assert list(got.index) == list(r.index)
    assert (got["days_late"].to_numpy() == r["late"].to_numpy()).all()
    assert (got["short"].to_numpy() == (r["qty_received"].astype(float) < r["qty_expected"]).to_numpy()).all()
    assert (got["emergency"].to_numpy() == r["lot_id"].str.startswith(cfg.SUBSTITUTE_LOT_PREFIX).to_numpy()).all()


def test_recall_scope_for_emergency_lots_matches_pandas_on_the_clean_data(built):
    data, conn = built
    lots, fg = data.tables["drone_part_lots"], data.tables["finished_goods"].set_index("serial_number")
    sub = lots[lots["lot_id"].str.startswith(cfg.SUBSTITUTE_LOT_PREFIX)]
    want = sub.groupby("lot_id").apply(lambda g: pd.Series({
        "drones": g["serial_number"].nunique(),
        "shipped": sum(1 for x in set(g["serial_number"]) if x in fg.index and pd.notna(fg.loc[x, "shipped_ts"])),
        "in_line": sum(1 for x in set(g["serial_number"]) if x not in fg.index)}), include_groups=False)
    got = sql_frame(conn, "SELECT lot_id, drones_containing_lot, already_shipped, still_in_the_line FROM v_recall_scope WHERE lot_id LIKE 'SUB-%'").set_index("lot_id").sort_index()
    assert list(got.index) == list(want.sort_index().index) and len(got) >= 2
    assert (got["drones_containing_lot"].to_numpy() == want.sort_index()["drones"].to_numpy()).all()
    assert (got["already_shipped"].to_numpy() == want.sort_index()["shipped"].to_numpy()).all()
    assert (got["still_in_the_line"].to_numpy() == want.sort_index()["in_line"].to_numpy()).all()


# ---------------------------------------------------------------------------- the story, from the metrics

def test_ridgeline_is_late_and_the_emergency_distributor_never_is(built):
    _, conn = built
    late = sql_frame(conn, "SELECT supplier_id, MAX(days_late) AS worst FROM v_deliveries WHERE NOT emergency GROUP BY 1").set_index("supplier_id")
    assert late.loc[cfg.RIDGELINE, "worst"] >= 5                       # at least one badly late Ridgeline delivery
    emergency = sql_frame(conn, "SELECT supplier_id, days_late, short FROM v_deliveries WHERE emergency")
    assert len(emergency) >= 2 and (emergency["supplier_id"] == cfg.SPOT_BUY).all()
    assert (emergency["days_late"] == 0).all() and not emergency["short"].any()


def test_the_emergency_lots_stand_out_in_lot_quality_and_all_have_shipped(built):
    _, conn = built
    lots = sql_frame(conn, "SELECT lot_id, fail_rate, drones_inspected FROM v_lot_quality WHERE drones_inspected >= 10 ORDER BY fail_rate DESC")
    assert lots["lot_id"].iloc[:2].str.startswith("SUB-").all() and lots["fail_rate"].iloc[0] > 0.2
    recall = sql_frame(conn, "SELECT already_shipped, drones_containing_lot FROM v_recall_scope WHERE lot_id LIKE 'SUB-%'")
    assert (recall["already_shipped"] == recall["drones_containing_lot"]).all()
