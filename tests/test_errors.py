"""Planting functions on tiny hand-made tables, then the whole generated dataset."""
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from factory import config as cfg
from factory.errors import (
    Windows, plant_errors, plant_duplicate_work_orders, plant_end_before_start, plant_missing_defect_code,
    plant_negative_inventory, plant_orphan_inspections, plant_over_receipt,
)
from factory.generate import generate


def rng(seed=0):
    return np.random.default_rng(seed)


# ---------------------------------------------------------------------------- tiny hand-made tables

SNAPSHOTS = pd.DataFrame({  # every (date, part, location) is different, as in the real table
    "snapshot_date": [date(2026, 3, 12)] * 6 + [date(2026, 3, 13)] * 2,
    "part_id": ["MTR-003", "MTR-003", "MTR-005", "MTR-005", "MTR-006", "MTR-006", "MTR-003", "MTR-003"],
    "location": ["WAREHOUSE", "LINE_SIDE"] * 4,
    "on_hand": [10, 20, 30, 40, 50, 60, 70, 80],
})


def test_negative_inventory_flips_exactly_n_eligible_rows_and_names_them():
    eligible = pd.Index([0, 1, 2, 3, 4, 5])  # rows 6 and 7 are outside the window
    out, keys = plant_negative_inventory(SNAPSHOTS, eligible, 3, rng())
    changed = out.index[out["on_hand"] != SNAPSHOTS["on_hand"]]
    assert len(changed) == 3 and set(changed) <= set(eligible)
    assert (out.loc[changed, "on_hand"] == -SNAPSHOTS.loc[changed, "on_hand"]).all()
    assert out.loc[[6, 7], "on_hand"].tolist() == [70, 80]
    expected = sorted(f"{SNAPSHOTS.loc[i, 'snapshot_date']}|{SNAPSHOTS.loc[i, 'part_id']}|{SNAPSHOTS.loc[i, 'location']}" for i in changed)
    assert keys == expected and len(set(keys)) == 3
    assert SNAPSHOTS["on_hand"].min() > 0  # the input was not modified


def test_planting_takes_fewer_rows_when_the_window_is_small():
    out, keys = plant_negative_inventory(SNAPSHOTS, pd.Index([0, 1]), 5, rng())
    assert len(keys) == 2 and (out["on_hand"] < 0).sum() == 2
    _, none = plant_negative_inventory(SNAPSHOTS, pd.Index([]), 5, rng())
    assert none == []


def inspections(n=8):
    return pd.DataFrame({
        "inspection_id": [f"INS-{i:06d}" for i in range(1, n + 1)],
        "serial_number": [f"DF-{i:06d}" for i in range(1, n + 1)],
        "station_code": ["MTR"] * n, "attempt": [1] * n, "result": ["FAIL"] * n,
        "defect_code": ["MTR-LOOSE-FASTENER"] * n,
    })


def test_missing_defect_codes_are_a_mix_of_null_and_blank():
    df = inspections()
    out, keys = plant_missing_defect_code(df, df.index, 4, rng())
    assert len(keys) == 4
    bad = out[out["inspection_id"].isin(keys)]["defect_code"]
    assert bad.isna().sum() == 2 and (bad.fillna("x").str.strip() == "").sum() == 2  # two NULL, two blank/whitespace
    assert (out[~out["inspection_id"].isin(keys)]["defect_code"] == "MTR-LOOSE-FASTENER").all()


def test_orphan_inspections_point_at_drones_that_do_not_exist():
    df = inspections()
    out, keys = plant_orphan_inspections(df, pd.Index([2, 3, 4]), 2, rng())
    changed = out[out["serial_number"] != df["serial_number"]]
    assert sorted(changed["inspection_id"]) == keys and len(keys) == 2
    assert changed["serial_number"].str.startswith("DF-9").all()
    assert not set(changed["serial_number"]) & set(df["serial_number"])


def test_over_receipt_is_twenty_to_fifty_percent_over():
    df = pd.DataFrame({"shipment_id": [f"SHP-{i}" for i in range(6)], "qty_expected": [100] * 6, "qty_received": pd.array([100] * 6, dtype="Int64")})
    out, keys = plant_over_receipt(df, df.index, 4, rng())
    over = out[out["shipment_id"].isin(keys)]["qty_received"]
    assert len(keys) == 4 and over.between(120, 150).all()
    assert (out[~out["shipment_id"].isin(keys)]["qty_received"] == 100).all()


WORK_ORDERS = pd.DataFrame({
    "wo_id": [f"WO-{i:06d}" for i in range(1, 6)],
    "serial_number": [f"DF-{i:06d}" for i in range(1, 6)],
    "station_code": ["AVN"] * 5,
    "start_ts": pd.to_datetime([f"2026-04-0{i} 08:00" for i in range(1, 6)]),
    "end_ts": pd.to_datetime([f"2026-04-0{i} 13:00" for i in range(1, 6)]),
    "status": ["COMPLETE"] * 5,
})


def test_duplicates_are_rekeyed_copies_with_new_sequential_ids():
    out, keys = plant_duplicate_work_orders(WORK_ORDERS, pd.Index([1, 2, 3]), 2, rng())
    assert len(out) == 7 and keys == ["WO-000006", "WO-000007"]
    copies = out[out["wo_id"].isin(keys)]
    natural = ["serial_number", "station_code", "start_ts", "end_ts", "status"]
    for _, copy in copies.iterrows():
        assert ((WORK_ORDERS[natural] == copy[natural]).all(axis=1)).sum() == 1  # exactly one original matches
    assert out.iloc[:5].equals(WORK_ORDERS)  # the originals are untouched


def test_end_before_start_moves_the_end_30_to_240_minutes_before_the_start():
    out, keys = plant_end_before_start(WORK_ORDERS, WORK_ORDERS.index, 3, rng())
    bad = out[out["wo_id"].isin(keys)]
    gap = (bad["start_ts"] - bad["end_ts"]).dt.total_seconds() / 60
    assert len(keys) == 3 and gap.between(30, 240).all()
    assert (out[~out["wo_id"].isin(keys)]["end_ts"] >= out[~out["wo_id"].isin(keys)]["start_ts"]).all()


def test_planting_is_reproducible_for_a_given_seed():
    a = plant_negative_inventory(SNAPSHOTS, SNAPSHOTS.index, 3, rng(5))[1]
    assert a == plant_negative_inventory(SNAPSHOTS, SNAPSHOTS.index, 3, rng(5))[1]
    assert a != plant_negative_inventory(SNAPSHOTS, SNAPSHOTS.index, 3, rng(6))[1]


# ---------------------------------------------------------------------------- the whole dataset

@pytest.fixture(scope="module")
def data():
    return generate()


PLANTED = list(cfg.PLANTED_COUNTS)


def test_the_answer_key_has_the_agreed_counts_and_empty_guards(data):
    for name, count in cfg.PLANTED_COUNTS.items():
        assert len(data.answer_key[name]) == count, name
        assert len(set(data.answer_key[name])) == count
    for guard in cfg.GUARD_CHECKS:
        assert data.answer_key[guard] == []
    assert set(data.answer_key) == set(PLANTED) | set(cfg.GUARD_CHECKS) | {"stock_does_not_reconcile"}


def test_only_the_planted_snapshot_rows_differ_and_only_by_sign(data):
    clean, dirty = data.clean["inventory_snapshots"], data.tables["inventory_snapshots"]
    diff = clean.index[clean["on_hand"] != dirty["on_hand"]]
    assert (dirty.loc[diff, "on_hand"] == -clean.loc[diff, "on_hand"]).all()
    assert sorted(f"{d}|{p}|{loc}" for d, p, loc in zip(clean.loc[diff, "snapshot_date"], clean.loc[diff, "part_id"], clean.loc[diff, "location"])) == data.answer_key["negative_inventory"]
    assert (clean["on_hand"] < 0).sum() == 0 and (dirty["on_hand"] < 0).sum() == 8


def test_only_the_planted_inspections_differ(data):
    clean, dirty = data.clean["inspections"], data.tables["inspections"]
    assert len(clean) == len(dirty)
    serial_diff = set(clean.loc[clean["serial_number"] != dirty["serial_number"], "inspection_id"])
    code_changed = clean["defect_code"].fillna("<null>") != dirty["defect_code"].fillna("<null>")
    code_diff = set(clean.loc[code_changed, "inspection_id"])
    assert serial_diff == set(data.answer_key["orphan_inspections"])
    assert code_diff == set(data.answer_key["missing_defect_code"])
    assert not serial_diff & code_diff
    other = [c for c in clean.columns if c not in ("serial_number", "defect_code")]
    assert clean[other].equals(dirty[other])


def test_only_the_planted_shipments_differ(data):
    clean, dirty = data.clean["receiving"], data.tables["receiving"]
    changed = clean["qty_received"].fillna(-1) != dirty["qty_received"].fillna(-1)
    assert sorted(clean.loc[changed, "shipment_id"]) == data.answer_key["over_receipt"]
    assert (dirty.loc[changed, "qty_received"] > dirty.loc[changed, "qty_expected"]).all()
    assert (clean["qty_received"].dropna() > clean.loc[clean["qty_received"].notna(), "qty_expected"]).sum() == 0


def test_work_orders_differ_only_by_the_copies_and_the_reversed_end_times(data):
    clean, dirty = data.clean["work_orders"], data.tables["work_orders"]
    copies = dirty[dirty["wo_id"].isin(data.answer_key["duplicate_work_orders"])]
    assert len(dirty) == len(clean) + 12 and len(copies) == 12
    originals = dirty[~dirty["wo_id"].isin(copies["wo_id"])]
    reversed_end = originals[originals["end_ts"] < originals["start_ts"]]
    assert sorted(reversed_end["wo_id"]) == data.answer_key["end_before_start"]
    unchanged = originals[~originals["wo_id"].isin(reversed_end["wo_id"])]
    pd.testing.assert_frame_equal(unchanged.reset_index(drop=True), clean[~clean["wo_id"].isin(reversed_end["wo_id"])].reset_index(drop=True))
    natural = ["serial_number", "station_code", "start_ts"]
    assert not clean.duplicated(natural).any()
    assert dirty.duplicated(natural, keep="first").sum() == 12  # the originals plus 12 copies, nothing else duplicated


def test_no_error_touches_the_same_work_order_twice(data):
    key = data.answer_key
    dirty = data.tables["work_orders"]
    copied = dirty[dirty["wo_id"].isin(key["duplicate_work_orders"])]
    origin_ids = set(dirty.merge(copied[["serial_number", "station_code", "start_ts"]], on=["serial_number", "station_code", "start_ts"])["wo_id"]) - set(key["duplicate_work_orders"])
    assert not origin_ids & set(key["end_before_start"])


def test_the_planted_rows_sit_in_the_story_windows(data):
    w = data.windows
    for name in PLANTED:
        assert w.eligible[name].size >= cfg.PLANTED_COUNTS[name], name
    snap = data.clean["inventory_snapshots"]
    lo, hi = w.ranges["negative_inventory"]
    planted = [k.split("|")[0] for k in data.answer_key["negative_inventory"]]
    assert all(lo <= d <= hi for d in planted)
    assert set(snap.loc[w.eligible["negative_inventory"], "part_id"]) <= {"MTR-003", "MTR-005", "MTR-006"}
    ins = data.clean["inspections"].set_index("inspection_id")
    assert (ins.loc[data.answer_key["missing_defect_code"], "station_code"] == "MTR").all()
    assert (ins.loc[data.answer_key["missing_defect_code"], "result"] == "FAIL").all()
    assert (ins.loc[data.answer_key["orphan_inspections"], "attempt"] == 2).all()
    rec = data.clean["receiving"].set_index("shipment_id")
    assert (rec.loc[data.answer_key["over_receipt"], "supplier_id"] == cfg.RIDGELINE).all()
    wo = data.clean["work_orders"].set_index("wo_id")
    assert (wo.loc[data.answer_key["end_before_start"], "station_code"] == "AVN").all()


def test_the_guarded_relationships_still_hold_with_the_errors_planted(data):
    t = data.tables
    wo = t["work_orders"]
    assert wo.loc[wo["status"] == "COMPLETE", "end_ts"].notna().all() and wo.loc[wo["status"] == "IN_PROGRESS", "end_ts"].isna().all()
    assert set(t["drone_part_lots"]["lot_id"]) <= set(t["receiving"]["lot_id"])
    assert set(t["drone_part_lots"]["serial_number"]) <= set(wo["serial_number"])
    fg = t["finished_goods"]
    passed = t["inspections"]
    fnt_pass = passed[(passed["station_code"] == "FNT") & (passed["result"] == "PASS")]["serial_number"]
    assert set(fg["serial_number"]) <= set(fnt_pass)
    assert (fg["test_passed_ts"] < fg["packed_ts"].fillna(pd.Timestamp.max)).all()
    assert (fg["packed_ts"].dropna() <= fg["shipped_ts"].reindex(fg["packed_ts"].dropna().index).fillna(pd.Timestamp.max)).all()


def test_generation_is_reproducible_and_depends_on_the_seed(data):
    again = generate()
    assert again.answer_key == data.answer_key
    for name in data.tables:
        pd.testing.assert_frame_equal(again.tables[name], data.tables[name])
    other = generate(seed=7)
    assert other.answer_key != data.answer_key


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_every_error_is_planted_in_other_seeds_too(seed):
    other = generate(seed)
    for name in PLANTED:
        assert len(other.answer_key[name]) >= 1, (seed, name)


def test_a_work_order_chosen_for_duplication_is_never_also_made_end_before_start(monkeypatch):
    """Tiny case where an overlap would be certain: three eligible jobs, two duplicated, three asked to be reversed."""
    monkeypatch.setattr(cfg, "PLANTED_COUNTS", {**cfg.PLANTED_COUNTS, "duplicate_work_orders": 2, "end_before_start": 3})
    nothing = pd.Index([], dtype="int64")
    eligible = {name: nothing for name in cfg.PLANTED_COUNTS}
    eligible["duplicate_work_orders"] = eligible["end_before_start"] = pd.Index([0, 1, 2])
    tables = {
        "inventory_snapshots": SNAPSHOTS, "inspections": inspections(), "work_orders": WORK_ORDERS.copy(),
        "receiving": pd.DataFrame({"shipment_id": [], "part_id": [], "qty_expected": [], "qty_received": pd.array([], dtype="Int64")}),
    }
    _, key, _ = plant_errors(tables, rng(), Windows(eligible, {}))
    assert len(key["duplicate_work_orders"]) == 2
    assert len(key["end_before_start"]) == 1  # only the one job that was not copied is left to reverse
    copied_serials = set(WORK_ORDERS.loc[[0, 1, 2], "serial_number"])
    reversed_serial = WORK_ORDERS.set_index("wo_id").loc[key["end_before_start"][0], "serial_number"]
    duplicated = {WORK_ORDERS.loc[i, "serial_number"] for i in (0, 1, 2)} - {reversed_serial}
    assert reversed_serial in copied_serials and len(duplicated) == 2
