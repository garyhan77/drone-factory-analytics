"""Packing and shipping after Final Test.

A drone is packed some working hours after it passes Final Test (packing happens during shifts, so a
drone that passes late on Friday is packed on Monday). Packed drones leave in one batch each weekday
at SHIP_BATCH_HOUR: anything packed by then ships that day, anything later waits for the next weekday.
The last batch of the data falls after the extract, so the final day's drones are packed but not shipped.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from factory import config as cfg
from factory.line import AS_OF, datetime_to_work_minute, work_minute_to_datetime


def packed_at(passed: datetime, pack_hours: float) -> datetime:
    """When a drone that passed Final Test at `passed` is packed, counting working hours only."""
    return work_minute_to_datetime(datetime_to_work_minute(passed) + round(pack_hours * 60))


def shipped_at(packed: datetime) -> datetime:
    """The first weekday 16:00 batch at or after the time the drone was packed."""
    batch = packed.replace(hour=cfg.SHIP_BATCH_HOUR, minute=0, second=0, microsecond=0)
    if packed > batch:
        batch += timedelta(days=1)
    while batch.weekday() >= 5:
        batch += timedelta(days=1)
    return batch


def build_finished_goods(work_orders: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """One row per drone that passed Final Test. Packed and shipped times are empty if still to come."""
    last_station = cfg.STATIONS[-1].code
    passed = work_orders[(work_orders["station_code"] == last_station) & work_orders["end_ts"].notna()]
    passed = passed.sort_values(["end_ts", "serial_number"], kind="stable")
    rows = []
    for serial, test_passed in zip(passed["serial_number"], passed["end_ts"]):
        test_passed = test_passed.to_pydatetime()
        packed = packed_at(test_passed, rng.uniform(*cfg.PACK_HOURS))
        shipped = shipped_at(packed)
        rows.append({
            "serial_number": serial,
            "test_passed_ts": test_passed,
            "packed_ts": packed if packed <= AS_OF else pd.NaT,
            "shipped_ts": shipped if shipped <= AS_OF else pd.NaT,
        })
    return pd.DataFrame(rows, columns=["serial_number", "test_passed_ts", "packed_ts", "shipped_ts"])
