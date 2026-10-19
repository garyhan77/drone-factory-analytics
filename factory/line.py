"""Simulate drones moving through the five stations.

Each station has a number of lanes. A drone starts at a station when it has arrived
AND a lane is free, so queues form on their own when releases outrun capacity.
Time is measured in working minutes (Mon-Fri, two shifts); a job that would run past
the end of a shift waits and starts at the beginning of the next one.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from factory import config as cfg


@dataclass
class LineResult:
    stations: pd.DataFrame
    work_orders: pd.DataFrame
    inspections: pd.DataFrame
    drones: pd.DataFrame  # internal: serial, release time, whether it carries the substitute lot


def weekly_releases(week: int) -> int:
    """Drones released into the line in a given week (1-based)."""
    if week <= cfg.RELEASES_MID_WEEK:
        span = cfg.RELEASES_MID_WEEK - 1
        value = cfg.RELEASES_WEEK_1 + (cfg.RELEASES_MID - cfg.RELEASES_WEEK_1) * (week - 1) / span
    else:
        span = cfg.WEEKS - cfg.RELEASES_MID_WEEK
        value = cfg.RELEASES_MID + (cfg.RELEASES_END - cfg.RELEASES_MID) * (week - cfg.RELEASES_MID_WEEK) / span
    return round(value)


def work_minute_to_datetime(minute: float) -> datetime:
    """Convert working minutes since the start into a wall-clock time."""
    day_index, within_day = divmod(int(minute), cfg.SHIFT_MIN)
    week_offset, weekday = divmod(day_index, cfg.WORK_DAYS)
    day = cfg.START + timedelta(days=7 * week_offset + weekday)
    return datetime(day.year, day.month, day.day, cfg.SHIFT_START_HOUR) + timedelta(minutes=within_day)


def week_of(minute: float) -> int:
    return int(minute // cfg.WEEK_MIN) + 1


AS_OF = work_minute_to_datetime(cfg.CUTOFF_MIN - 1) + timedelta(minutes=1)  # when the data was extracted


def _release_times(rng: np.random.Generator) -> np.ndarray:
    times = []
    for week in range(1, cfg.WEEKS + 1):
        lo, hi = (week - 1) * cfg.WEEK_MIN, week * cfg.WEEK_MIN
        times.extend(np.sort(rng.integers(lo, hi, size=weekly_releases(week))))
    return np.array(times, dtype=float)


def _pick_defect(rng: np.random.Generator, station: cfg.Station, on_substitute_lot: bool) -> str:
    if station.code == cfg.SPIKE_STATION and on_substitute_lot and rng.random() < cfg.SUBSTITUTE_LOOSE_FASTENER_SHARE:
        return cfg.SPIKE_DEFECT
    names = cfg.DEFECT_NAMES[station.code]
    return f"{station.code}-{names[int(rng.integers(len(names)))]}"


def simulate_line(rng: np.random.Generator) -> LineResult:
    release = _release_times(rng)
    n = len(release)
    serials = [f"DF-{i + 1:06d}" for i in range(n)]
    on_substitute_lot = np.zeros(n, dtype=bool)

    work_orders, inspections = [], []
    ready = release.copy()  # when each drone is ready for the next station

    for station in cfg.STATIONS:
        lane_free = np.zeros(station.lanes)
        finished_at = np.zeros(n)
        for i in np.argsort(ready, kind="stable"):  # first come, first served
            lane = int(np.argmin(lane_free))
            start = max(ready[i], lane_free[lane])

            # Draw everything for this job once, so the outcome depends only on when it really starts.
            lot_draw, fail_draw = rng.random(2)
            typical = station.cycle_hours
            cycle_h = float(np.clip(
                rng.lognormal(math.log(typical), cfg.CYCLE_SIGMA),
                cfg.CYCLE_MIN_FACTOR * typical, cfg.CYCLE_MAX_FACTOR * typical,
            ))
            rework_h = float(rng.uniform(*cfg.REWORK_HOURS))

            # Whether the job fails depends on the week it starts, and rework changes how long it
            # takes, which can push it into the next shift (and week). Repeat until those agree.
            while True:
                week = week_of(start)
                substitute = (
                    station.code == cfg.SPIKE_STATION and week in cfg.SPIKE_WEEKS
                    and lot_draw < cfg.SUBSTITUTE_LOT_SHARE
                )
                failed = fail_draw < (cfg.SUBSTITUTE_FAIL_RATE if substitute else station.fail_rate)
                cycle_min = round(cycle_h * 60)
                total_min = round((cycle_h + (rework_h if failed else 0.0)) * 60)
                fits = start % cfg.SHIFT_MIN + total_min <= cfg.SHIFT_MIN
                pushed = start if fits else start + cfg.SHIFT_MIN - start % cfg.SHIFT_MIN
                if week_of(pushed) == week:
                    break
                start = pushed
            start = pushed
            if station.code == cfg.SPIKE_STATION:
                on_substitute_lot[i] = substitute

            lane_free[lane] = finished_at[i] = start + total_min
            if start >= cfg.CUTOFF_MIN:
                continue  # not started before the data was extracted

            start_ts = work_minute_to_datetime(start)
            end_ts = start_ts + timedelta(minutes=total_min)
            done = end_ts <= AS_OF
            work_orders.append({
                "serial_number": serials[i], "station_code": station.code, "start_ts": start_ts,
                "end_ts": end_ts if done else pd.NaT, "status": "COMPLETE" if done else "IN_PROGRESS",
            })

            first_ts = start_ts + timedelta(minutes=cycle_min)
            if first_ts <= AS_OF:
                inspections.append({
                    "serial_number": serials[i], "station_code": station.code, "attempt": 1,
                    "inspected_ts": first_ts, "result": "FAIL" if failed else "PASS",
                    "defect_code": _pick_defect(rng, station, bool(on_substitute_lot[i])) if failed else None,
                })
            if failed and done:  # rework always passes the second inspection
                inspections.append({
                    "serial_number": serials[i], "station_code": station.code, "attempt": 2,
                    "inspected_ts": end_ts, "result": "PASS", "defect_code": None,
                })
        ready = finished_at

    return LineResult(
        stations=_stations_table(),
        work_orders=_with_ids(pd.DataFrame(work_orders), "wo_id", "WO", ["start_ts", "station_code"]),
        inspections=_with_ids(pd.DataFrame(inspections), "inspection_id", "INS", ["inspected_ts", "station_code", "attempt"]),
        drones=pd.DataFrame({
            "serial_number": serials,
            "release_ts": [work_minute_to_datetime(m) for m in release],
            "carries_substitute_lot": on_substitute_lot,
        }),
    )


def _stations_table() -> pd.DataFrame:
    return pd.DataFrame(
        [(i + 1, s.code, s.name) for i, s in enumerate(cfg.STATIONS)],
        columns=["station_seq", "station_code", "station_name"],
    )


def _with_ids(df: pd.DataFrame, id_col: str, prefix: str, sort_by: list[str]) -> pd.DataFrame:
    """Sort chronologically and add sequential ids as the first column."""
    df = df.sort_values(sort_by + ["serial_number"], kind="stable").reset_index(drop=True)
    df.insert(0, id_col, [f"{prefix}-{i + 1:06d}" for i in range(len(df))])
    return df
