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


def test_forty_parts_eight_per_station_with_unique_ids():
    parts = build_parts()
    assert len(parts) == 40 and parts["part_id"].is_unique
    assert part_ids()[:2] == ["AFL-001", "AFL-002"] and "MTR-003" in part_ids()
    per_station = parts["part_id"].str[:3].value_counts()
    assert set(per_station.index) == {s.code for s in cfg.STATIONS}
    assert (per_station == 8).all()


def test_every_part_has_a_regular_supplier_and_the_spot_buy_supplies_none():
    parts, suppliers = build_parts(), build_suppliers()
    assert set(parts["supplier_id"]) <= set(suppliers["supplier_id"])
    assert cfg.SPOT_BUY not in set(parts["supplier_id"])


def test_ridgeline_supplies_eight_parts_including_the_three_spike_fasteners():
    parts = build_parts()
    ridgeline = parts[parts["supplier_id"] == cfg.RIDGELINE]
    assert len(ridgeline) == 8
    assert set(cfg.SPIKE_FASTENERS) <= set(ridgeline["part_name"])
    assert set(ridgeline.loc[ridgeline["part_name"].isin(cfg.SPIKE_FASTENERS), "part_id"].str[:3]) == {cfg.SPIKE_STATION}


def test_bom_has_one_row_per_part_and_the_expected_pieces_per_drone():
    bom, parts = build_bom(), build_parts()
    assert len(bom) == 40 and set(bom["part_id"]) == set(parts["part_id"])
    pieces = bom.groupby("station_code")["qty_per_unit"].sum().to_dict()
    assert pieces == {"AFL": 15, "WNG": 22, "MTR": 17, "AVN": 9, "FNT": 9}
    assert (bom["part_id"].str[:3] == bom["station_code"]).all()


def test_reorder_points_scale_with_lead_time_and_pieces_per_drone():
    parts = build_parts().set_index("part_name")
    # Same quantity per drone (2), different quoted lead times: longer lead time, higher reorder point.
    assert parts.loc["Wing spar", "reorder_point"] > parts.loc["Motor mount", "reorder_point"]
    # Same supplier and lead time, different quantity per drone: more pieces, higher reorder point.
    assert parts.loc["Pushrod", "reorder_point"] > parts.loc["Hinge pin set", "reorder_point"]
    assert (parts["reorder_point"] > 0).all()


def test_reorder_point_follows_the_documented_formula():
    parts = build_parts().set_index("part_name")
    expected = launch_drones_per_day() * 2 * (10 + cfg.REORDER_SAFETY_DAYS)  # motor mount: 2 per drone, 10-day lead
    assert parts.loc["Motor mount", "reorder_point"] == pytest.approx(expected, abs=1)
    assert 2.5 < launch_drones_per_day() < 3.0  # about 19 drones a week at launch


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
    assert conn.execute("SELECT COUNT(*) FROM raw_parts").fetchone()[0] == 40
