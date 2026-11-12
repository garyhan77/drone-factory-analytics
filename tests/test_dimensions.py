import pandas as pd
import pytest

from factory import config as cfg
from factory.db import load_dataframe
from factory.dimensions import build_bom, build_parts, build_suppliers, launch_drones_per_day, part_ids


def test_eight_suppliers_with_ridgeline_first_and_the_spot_buy_distributor_last():
    suppliers = build_suppliers()
    assert len(suppliers) == 8
    assert suppliers["supplier_id"].is_unique
    assert suppliers.loc[suppliers["supplier_id"] == cfg.RIDGELINE, "supplier_name"].item() == "Ridgeline Hardware"
    assert suppliers.loc[suppliers["supplier_id"] == cfg.SPOT_BUY, "supplier_name"].item() == "Spot-Buy Distributor"


def test_twelve_parts_with_unique_ids_across_all_five_stations():
    parts = build_parts()
    assert len(parts) == 12 and parts["part_id"].is_unique
    assert part_ids()[:2] == ["AFL-001", "AFL-002"] and "MTR-004" in part_ids()
    per_station = parts["part_id"].str[:3].value_counts()
    assert set(per_station.index) == {s.code for s in cfg.STATIONS}
    assert per_station["MTR"] == 5 and per_station.drop("MTR").between(1, 2).all()


def test_every_part_has_a_regular_supplier_and_the_spot_buy_supplies_none():
    parts, suppliers = build_parts(), build_suppliers()
    assert set(parts["supplier_id"]) <= set(suppliers["supplier_id"])
    assert cfg.SPOT_BUY not in set(parts["supplier_id"])


def test_ridgeline_supplies_only_the_spike_fastener_at_motor_and_prop():
    parts = build_parts()
    ridgeline = parts[parts["supplier_id"] == cfg.RIDGELINE]
    assert list(ridgeline["part_name"]) == list(cfg.SPIKE_FASTENERS) == ["Prop nut"]
    assert set(ridgeline["part_id"].str[:3]) == {cfg.SPIKE_STATION}


def test_bom_has_one_row_per_part_and_the_expected_pieces_per_drone():
    bom, parts = build_bom(), build_parts()
    assert len(bom) == 12 and set(bom["part_id"]) == set(parts["part_id"])
    pieces = bom.groupby("station_code")["qty_per_unit"].sum().to_dict()
    assert pieces == {"AFL": 5, "WNG": 6, "MTR": 10, "AVN": 2, "FNT": 1}
    assert (bom["part_id"].str[:3] == bom["station_code"]).all()


def test_reorder_points_scale_with_lead_time_and_pieces_per_drone():
    parts = build_parts().set_index("part_name")
    # Same quantity per drone (2), different quoted lead times: longer lead time, higher reorder point.
    assert parts.loc["Wing spar", "reorder_point"] > parts.loc["Epoxy resin kit", "reorder_point"]
    # Same supplier and lead time, different quantity per drone: more pieces, higher reorder point.
    assert parts.loc["Servo", "reorder_point"] > parts.loc["Brushless motor", "reorder_point"]
    assert (parts["reorder_point"] > 0).all()


def test_reorder_point_follows_the_documented_formula():
    parts = build_parts().set_index("part_name")
    expected = launch_drones_per_day() * 2 * (18 + cfg.REORDER_SAFETY_DAYS)  # motor mount: 2 per drone, 18-day lead
    assert parts.loc["Motor mount", "reorder_point"] == pytest.approx(expected, abs=1)
    thin = launch_drones_per_day() * 2 * (10 + cfg.RIDGELINE_SAFETY_DAYS)  # prop nut: Ridgeline, 10-day lead, thin buffer
    assert parts.loc["Prop nut", "reorder_point"] == pytest.approx(thin, abs=1)
    assert launch_drones_per_day() == pytest.approx(20 / 7)  # a steady 20 drones a week


def test_dimension_tables_load_into_postgres_and_join_cleanly(conn):
    load_dataframe(conn, "suppliers", build_suppliers())
    load_dataframe(conn, "parts", build_parts())
    load_dataframe(conn, "bom", build_bom())
    orphans = conn.execute(
        "SELECT COUNT(*) FROM raw_bom b LEFT JOIN raw_parts p USING (part_id) WHERE p.part_id IS NULL"
    ).fetchone()[0]
    no_supplier = conn.execute(
        "SELECT COUNT(*) FROM raw_parts p LEFT JOIN raw_suppliers s USING (supplier_id) WHERE s.supplier_id IS NULL"
    ).fetchone()[0]
    assert (orphans, no_supplier) == (0, 0)
    assert conn.execute("SELECT COUNT(*) FROM raw_parts").fetchone()[0] == 12
