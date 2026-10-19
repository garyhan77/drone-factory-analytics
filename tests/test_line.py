from datetime import time

import numpy as np
import pandas as pd
import pytest

from factory import config as cfg
from factory.line import AS_OF, simulate_line, weekly_releases

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


def test_substitute_lot_only_in_spike_weeks_and_causes_the_spike(line):
    mtr_start = line.work_orders[line.work_orders["station_code"] == cfg.SPIKE_STATION]
    mtr_start = mtr_start.assign(week=week(mtr_start["start_ts"])).merge(line.drones, on="serial_number")
    in_window = mtr_start["week"].isin(cfg.SPIKE_WEEKS)
    assert not mtr_start.loc[~in_window, "carries_substitute_lot"].any()
    share = mtr_start.loc[in_window, "carries_substitute_lot"].mean()
    assert 0.5 < share < 0.9

    first = line.inspections[(line.inspections["attempt"] == 1) & (line.inspections["station_code"] == cfg.SPIKE_STATION)]
    first = first.merge(line.drones, on="serial_number")
    first = first[week(first["inspected_ts"]).isin(cfg.SPIKE_WEEKS)]
    fail = first.groupby("carries_substitute_lot")["result"].apply(lambda s: (s == "FAIL").mean())
    assert fail[True] > 3 * fail[False]

    spike_fails = line.inspections[line.inspections["defect_code"] == cfg.SPIKE_DEFECT]
    assert len(spike_fails) > 10


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
