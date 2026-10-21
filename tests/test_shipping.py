"""Packing and shipping, checked by hand first and then on the full simulated line.

2026-03-03 is a Tuesday, 2026-03-06 a Friday, 2026-03-09 a Monday. Shifts run 06:00 to 22:00.
"""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from factory import config as cfg
from factory.line import datetime_to_work_minute, simulate_line, work_minute_to_datetime
from factory.shipping import build_finished_goods, packed_at, shipped_at

TUE_10 = datetime(2026, 3, 3, 10, 0)


def test_work_minute_conversion_round_trips_and_rejects_weekends():
    for ts in (datetime(2026, 1, 5, 6, 0), TUE_10, datetime(2026, 3, 6, 21, 59), datetime(2026, 7, 3, 13, 0)):
        assert work_minute_to_datetime(datetime_to_work_minute(ts)) == ts
    assert datetime_to_work_minute(datetime(2026, 3, 9, 6, 0)) == datetime_to_work_minute(datetime(2026, 3, 6, 22, 0))
    with pytest.raises(ValueError):
        datetime_to_work_minute(datetime(2026, 3, 7, 10, 0))  # a Saturday


@pytest.mark.parametrize("passed, hours, expected", [
    (TUE_10, 4, datetime(2026, 3, 3, 14, 0)),  # same shift
    (TUE_10, 24, datetime(2026, 3, 4, 18, 0)),  # 12 hours left Tuesday, 12 more on Wednesday morning: 06:00 + 12 = 18:00
    (datetime(2026, 3, 6, 20, 0), 4, datetime(2026, 3, 9, 8, 0)),  # Friday 20:00: 2 hours left, 2 more on Monday
    (datetime(2026, 3, 3, 22, 0), 4, datetime(2026, 3, 4, 10, 0)),  # passes right at the end of the shift
])
def test_packing_counts_working_hours_only(passed, hours, expected):
    assert packed_at(passed, hours) == expected


@pytest.mark.parametrize("packed, expected", [
    (datetime(2026, 3, 3, 14, 0), datetime(2026, 3, 3, 16, 0)),  # before the batch: ships that day
    (datetime(2026, 3, 3, 16, 0), datetime(2026, 3, 3, 16, 0)),  # exactly at the batch: still ships
    (datetime(2026, 3, 3, 16, 1), datetime(2026, 3, 4, 16, 0)),  # a minute late: next day
    (datetime(2026, 3, 6, 15, 59), datetime(2026, 3, 6, 16, 0)),  # Friday before the batch
    (datetime(2026, 3, 6, 16, 1), datetime(2026, 3, 9, 16, 0)),  # Friday after the batch: Monday
    (datetime(2026, 3, 9, 6, 0), datetime(2026, 3, 9, 16, 0)),  # Monday morning
])
def test_shipping_is_one_weekday_batch_at_four(packed, expected):
    assert shipped_at(packed) == expected


def make_orders(*end_times):
    """Final Test work orders: a completed one for each time, plus an in-progress one and one at another station."""
    rows = [{"serial_number": f"S{i}", "station_code": "FNT", "start_ts": t - pd.Timedelta(hours=3), "end_ts": t, "status": "COMPLETE"}
            for i, t in enumerate(end_times)]
    rows.append({"serial_number": "WIP", "station_code": "FNT", "start_ts": datetime(2026, 3, 3, 9), "end_ts": pd.NaT, "status": "IN_PROGRESS"})
    rows.append({"serial_number": "OTHER", "station_code": "AVN", "start_ts": datetime(2026, 3, 3, 9), "end_ts": datetime(2026, 3, 3, 12), "status": "COMPLETE"})
    return pd.DataFrame(rows)


def test_only_drones_that_passed_final_test_appear():
    fg = build_finished_goods(make_orders(TUE_10, datetime(2026, 3, 4, 11)), np.random.default_rng(0))
    assert list(fg["serial_number"]) == ["S0", "S1"]


def test_the_row_for_a_drone_is_ordered_in_time_and_packing_is_within_range():
    fg = build_finished_goods(make_orders(*[datetime(2026, 3, 3, 8 + i) for i in range(10)]), np.random.default_rng(1))
    assert (fg["test_passed_ts"] < fg["packed_ts"]).all() and (fg["packed_ts"] <= fg["shipped_ts"]).all()
    minutes = fg["packed_ts"].map(datetime_to_work_minute) - fg["test_passed_ts"].map(datetime_to_work_minute)
    assert minutes.between(cfg.PACK_HOURS[0] * 60, cfg.PACK_HOURS[1] * 60).all()
    assert (fg["shipped_ts"].dt.hour == cfg.SHIP_BATCH_HOUR).all() and (fg["shipped_ts"].dt.dayofweek < 5).all()


def test_drones_packed_or_shipped_after_the_extract_have_empty_times():
    from factory.line import AS_OF  # Friday 2026-07-03 14:00
    early = datetime(2026, 7, 3, 7, 0)  # packed Friday morning, but the 16:00 batch is after the extract
    late = datetime(2026, 7, 3, 12, 0)  # packing (4+ working hours) runs past 14:00
    fg = build_finished_goods(make_orders(early, late), np.random.default_rng(0)).set_index("serial_number")
    assert pd.isna(fg.loc["S1", "packed_ts"]) and pd.isna(fg.loc["S1", "shipped_ts"])  # not yet packed
    for serial in ("S0", "S1"):
        assert pd.isna(fg.loc[serial, "shipped_ts"])  # the Friday 16:00 batch has not happened yet
    assert AS_OF.hour == 14


# ---------------------------------------------------------------------------- on the full simulated line

@pytest.fixture(scope="module")
def line_and_goods():
    line = simulate_line(np.random.default_rng(cfg.SEED))
    return line, build_finished_goods(line.work_orders, np.random.default_rng(cfg.SEED + 1))


def test_every_finished_drone_passed_final_test(line_and_goods):
    line, fg = line_and_goods
    done = line.work_orders[(line.work_orders["station_code"] == "FNT") & line.work_orders["end_ts"].notna()]
    assert set(fg["serial_number"]) == set(done["serial_number"]) and fg["serial_number"].is_unique
    inspections = line.inspections[(line.inspections["station_code"] == "FNT") & (line.inspections["result"] == "PASS")]
    assert set(fg["serial_number"]) <= set(inspections["serial_number"])


def test_the_delay_is_upstream_lead_time_grows_while_dwell_after_test_stays_flat(line_and_goods):
    line, fg = line_and_goods
    start = line.work_orders[line.work_orders["station_code"] == cfg.STATIONS[0].code].set_index("serial_number")["start_ts"]
    shipped = fg.dropna(subset=["shipped_ts"]).copy()
    shipped["lead_days"] = (shipped["shipped_ts"] - shipped["serial_number"].map(start)).dt.total_seconds() / 86400
    shipped["dwell_days"] = (shipped["shipped_ts"] - shipped["test_passed_ts"]).dt.total_seconds() / 86400
    shipped["week"] = ((shipped["shipped_ts"] - pd.Timestamp(cfg.START)).dt.days // 7) + 1
    early, late = shipped[shipped["week"].between(4, 9)], shipped[shipped["week"].between(20, 25)]
    assert late["lead_days"].mean() > 1.5 * early["lead_days"].mean()  # lead time grows with the Avionics queue
    assert late["dwell_days"].mean() == pytest.approx(early["dwell_days"].mean(), rel=0.25)  # dwell after test does not
