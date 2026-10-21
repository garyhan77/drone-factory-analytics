from datetime import time

import numpy as np
import pandas as pd
import pytest

from factory import config as cfg
from factory.dimensions import part_ids
from factory.line import AS_OF, LAST_DAY, simulate_line, weekly_releases

START = pd.Timestamp(cfg.START)


def week(ts: pd.Series) -> pd.Series:
    return ((ts - START).dt.days // 7) + 1


@pytest.fixture(scope="module")
def line():
    return simulate_line(np.random.default_rng(cfg.SEED))


def test_same_seed_gives_same_line(line):
    again = simulate_line(np.random.default_rng(cfg.SEED))
    pd.testing.assert_frame_equal(line.work_orders, again.work_orders)
    pd.testing.assert_frame_equal(line.inspections, again.inspections)


def test_weekly_releases_follow_the_ramp(line):
    assert weekly_releases(1) == 18
    assert weekly_releases(12) == 30
    assert weekly_releases(26) == 34
    released = week(line.drones["release_ts"]).value_counts()
    assert released[1] == 18 and released[12] == 30 and released[26] == 34


def test_ids_are_unique_and_sequential(line):
    for df, col in ((line.work_orders, "wo_id"), (line.inspections, "inspection_id")):
        assert df[col].is_unique
        assert df[col].iloc[0].endswith("000001")


def test_jobs_stay_inside_a_shift_on_a_weekday(line):
    done = line.work_orders[line.work_orders["status"] == "COMPLETE"]
    assert (done["end_ts"] >= done["start_ts"]).all()
    assert (done["start_ts"].dt.date == done["end_ts"].dt.date).all()
    assert (done["start_ts"].dt.dayofweek < 5).all()
    assert (done["start_ts"].dt.time >= time(6)).all()
    assert (done["end_ts"].dt.time <= time(22)).all()


def test_in_progress_jobs_have_no_end_and_nothing_starts_after_the_extract(line):
    wo = line.work_orders
    in_progress = wo[wo["status"] == "IN_PROGRESS"]
    assert len(in_progress) > 0
    assert in_progress["end_ts"].isna().all()
    assert wo.loc[wo["status"] == "COMPLETE", "end_ts"].notna().all()
    assert (wo["start_ts"] < AS_OF).all()


def test_drones_move_through_stations_in_order(line):
    order = {s.code: i for i, s in enumerate(cfg.STATIONS)}
    wo = line.work_orders.assign(seq=lambda d: d["station_code"].map(order)).sort_values(["serial_number", "seq"])
    prev_end = wo.groupby("serial_number")["end_ts"].shift()
    gap = wo["start_ts"] - prev_end
    assert (gap.dropna() >= pd.Timedelta(0)).all()


def test_inspections_are_consistent(line):
    ins = line.inspections
    first, second = ins[ins["attempt"] == 1], ins[ins["attempt"] == 2]
    assert (ins.loc[ins["result"] == "FAIL", "defect_code"].notna()).all()
    assert ins.loc[ins["result"] == "PASS", "defect_code"].isna().all()
    assert (second["result"] == "PASS").all()
    failed = set(zip(first.loc[first["result"] == "FAIL", "serial_number"], first.loc[first["result"] == "FAIL", "station_code"]))
    assert set(zip(second["serial_number"], second["station_code"])) <= failed


def test_avionics_is_the_bottleneck_and_its_queue_grows(line):
    order = {s.code: i for i, s in enumerate(cfg.STATIONS)}
    wo = line.work_orders.assign(seq=lambda d: d["station_code"].map(order)).sort_values(["serial_number", "seq"])
    wo["wait_h"] = (wo["start_ts"] - wo.groupby("serial_number")["end_ts"].shift()).dt.total_seconds() / 3600
    wo["week"] = week(wo["start_ts"])
    wait = wo[wo["seq"] > 0]
    avn, others = wait[wait["station_code"] == "AVN"], wait[wait["station_code"] != "AVN"]
    early, late = avn[avn["week"] <= 8]["wait_h"].mean(), avn[avn["week"] >= 22]["wait_h"].mean()
    assert early < 24  # healthy at launch
    assert late > 5 * early  # grows as releases outrun capacity
    assert avn[avn["week"] >= 20]["wait_h"].mean() > 5 * others[others["week"] >= 20]["wait_h"].mean()


# ---------------------------------------------------------------------------- the coupled supply chain

FASTENERS = [pid for pid, part in zip(part_ids(), cfg.PARTS) if part.name in cfg.SPIKE_FASTENERS]


def sub_lot_drones(line):
    """Serials whose Motor & Prop fasteners include an emergency (spot-buy) lot, from the traceability table."""
    lots = line.drone_part_lots
    used = lots[lots["part_id"].isin(FASTENERS)]
    return set(used.loc[used["lot_id"].str.startswith(cfg.SUBSTITUTE_LOT_PREFIX), "serial_number"])


def test_substitute_flag_matches_the_traceability_table(line):
    flagged = set(line.drones.loc[line.drones["carries_substitute_lot"], "serial_number"])
    assert flagged == sub_lot_drones(line) and len(flagged) > 10


def test_the_spike_is_caused_by_the_substitute_lot(line):
    first = line.inspections[(line.inspections["attempt"] == 1) & (line.inspections["station_code"] == cfg.SPIKE_STATION)]
    on_sub = first["serial_number"].isin(sub_lot_drones(line))
    fail = first["result"].eq("FAIL")
    assert fail[on_sub].mean() > 3 * fail[~on_sub].mean()
    assert fail[on_sub].mean() == pytest.approx(cfg.SUBSTITUTE_FAIL_RATE, abs=0.08)
    spike_code = first[on_sub & fail]["defect_code"].eq(cfg.SPIKE_DEFECT)
    assert spike_code.mean() > 0.5


def test_the_spike_follows_the_shortage_not_a_calendar(line):
    """No drone gets a substitute fastener before the first emergency lot has actually been received."""
    rec = line.receiving
    spot = rec[(rec["supplier_id"] == cfg.SPOT_BUY) & rec["part_id"].isin(FASTENERS) & rec["received_date"].notna()]
    first_received = pd.Timestamp(spot["received_date"].min())
    mtr = line.work_orders[line.work_orders["station_code"] == cfg.SPIKE_STATION].set_index("serial_number")["start_ts"]
    starts = mtr.reindex(sorted(sub_lot_drones(line)))
    assert (starts >= first_received).all()
    # ...and the first emergency buy comes after Ridgeline's disruption began, not before.
    first_order_week = int(week(pd.Series(pd.to_datetime(spot["order_date"])).iloc[[spot["order_date"].argmin()]]).iloc[0])
    assert min(cfg.RIDGELINE_DISRUPTION_WEEKS) <= first_order_week <= max(cfg.RIDGELINE_DISRUPTION_WEEKS) + 4


def test_only_ridgeline_parts_are_ever_bought_from_the_spot_distributor(line):
    rec = line.receiving
    spot_parts = set(rec.loc[rec["supplier_id"] == cfg.SPOT_BUY, "part_id"])
    ridgeline_parts = {pid for pid, part in zip(part_ids(), cfg.PARTS) if part.supplier_id == cfg.RIDGELINE}
    assert spot_parts and spot_parts <= ridgeline_parts


def test_every_traced_lot_has_a_receiving_row_and_every_started_job_is_traced(line):
    lots = line.drone_part_lots
    assert set(lots["lot_id"]) <= set(line.receiving["lot_id"])
    per_job = lots.groupby(["serial_number", "station_code"]).size()
    started = line.work_orders.groupby(["serial_number", "station_code"]).size()
    assert set(per_job.index) == set(started.index)
    assert (per_job == 8).all()  # eight parts per station


def test_stock_is_conserved_for_every_part(line):
    """Everything received is either installed in a drone, in the warehouse, or on the shelf at the end."""
    bom = {pid: part.qty_per_drone for pid, part in zip(part_ids(), cfg.PARTS)}
    installed = line.drone_part_lots.groupby("part_id").size() * pd.Series(bom)
    received = line.receiving.dropna(subset=["received_date"]).groupby("part_id")["qty_received"].sum()
    snap = line.inventory_snapshots
    on_hand = snap[snap["snapshot_date"] == LAST_DAY].groupby("part_id")["on_hand"].sum()
    for pid in bom:
        assert received[pid] == installed.get(pid, 0) + on_hand[pid], pid


def test_snapshots_cover_every_part_location_and_day_with_no_negative_stock(line):
    snap = line.inventory_snapshots
    days = (LAST_DAY - cfg.START).days + 1
    assert len(snap) == 40 * 2 * days
    assert snap["on_hand"].min() >= 0
    assert set(snap["location"]) == {"WAREHOUSE", "LINE_SIDE"}


def test_the_line_stays_healthy_outside_the_story(line):
    released = len(line.drones)
    finished = int((line.work_orders["station_code"] == "FNT").sum())
    assert finished > 0.8 * released  # shortages delay work; they do not strangle the line


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_the_story_does_not_depend_on_one_lucky_seed(seed):
    other = simulate_line(np.random.default_rng(seed))
    drones = sub_lot_drones(other)
    rec = other.receiving
    spot = rec[(rec["supplier_id"] == cfg.SPOT_BUY) & rec["part_id"].isin(FASTENERS)]
    first_week = int(week(pd.to_datetime(spot["order_date"])).min())
    assert min(cfg.RIDGELINE_DISRUPTION_WEEKS) <= first_week <= max(cfg.RIDGELINE_DISRUPTION_WEEKS) + 4
    assert len(drones) >= 20
    first = other.inspections[(other.inspections["attempt"] == 1) & (other.inspections["station_code"] == cfg.SPIKE_STATION)]
    on_sub, fail = first["serial_number"].isin(drones), first["result"].eq("FAIL")
    assert fail[on_sub].mean() > 3 * fail[~on_sub].mean()
