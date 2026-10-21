"""Simulate drones moving through the five stations, with the parts they use.

Each station has a number of lanes. A drone starts at a station when it has arrived, a lane is
free, AND every part it needs is on the line-side shelf, so queues form on their own when releases
outrun capacity and shortages show up as delays. Time is measured in working minutes (Mon-Fri, two
shifts); a job that would run past the end of a shift waits and starts at the beginning of the next.

Each station runs its own parts inventory (factory/inventory.py) alongside its jobs. This works
station by station because every part belongs to exactly one station. Jobs at a station start in
first-come, first-served order, so the inventory only ever moves forward in time.

The defect spike is not scripted. A drone whose Motor & Prop fasteners came from an emergency
(spot-buy) lot fails more often; whether that happens depends on how the supply chain behaves.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from factory import config as cfg
from factory.config import weekly_releases  # noqa: F401 (also imported from here by tests)
from factory.dimensions import part_ids, part_specs
from factory.inventory import Policy, StationInventory, config_delivery, default_initial


@dataclass
class LineResult:
    stations: pd.DataFrame
    work_orders: pd.DataFrame
    inspections: pd.DataFrame
    receiving: pd.DataFrame
    inventory_snapshots: pd.DataFrame
    drone_part_lots: pd.DataFrame
    drones: pd.DataFrame  # internal: serial, release time, whether it carries a substitute-lot fastener


def work_minute_to_datetime(minute: float) -> datetime:
    """Convert working minutes since the start into a wall-clock time."""
    day_index, within_day = divmod(int(minute), cfg.SHIFT_MIN)
    week_offset, weekday = divmod(day_index, cfg.WORK_DAYS)
    day = cfg.START + timedelta(days=7 * week_offset + weekday)
    return datetime(day.year, day.month, day.day, cfg.SHIFT_START_HOUR) + timedelta(minutes=within_day)


def week_of(minute: float) -> int:
    return int(minute // cfg.WEEK_MIN) + 1


def next_shift_start(minute: float) -> float:
    return minute + cfg.SHIFT_MIN - minute % cfg.SHIFT_MIN


AS_OF = work_minute_to_datetime(cfg.CUTOFF_MIN - 1) + timedelta(minutes=1)  # when the data was extracted
LAST_DAY = AS_OF.date()  # the last calendar day in the data (a Friday)


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
    policy = Policy.from_config()
    spike_part_ids = {
        pid for pid, part in zip(part_ids(), cfg.PARTS)
        if part.station_code == cfg.SPIKE_STATION and part.name in cfg.SPIKE_FASTENERS
    }

    work_orders, inspections, lots_used, receiving, snapshots = [], [], [], [], []
    ready = release.copy()  # when each drone is ready for the next station

    for station in cfg.STATIONS:
        specs = part_specs(station.code)
        inventory = StationInventory(
            station.code, specs, default_initial(specs, policy), cfg.START,
            policy=policy, delivery=config_delivery, seed=int(rng.integers(2**31)),
        )
        lane_free = np.zeros(station.lanes)
        finished_at = np.zeros(n)
        previous_start = 0.0  # jobs start in order, so the inventory only moves forward
        for i in np.argsort(ready, kind="stable"):  # first come, first served
            lane = int(np.argmin(lane_free))

            # Draw everything for this job once, so retrying a later day does not change the dice.
            fail_draw = rng.random()
            typical = station.cycle_hours
            cycle_h = float(np.clip(
                rng.lognormal(math.log(typical), cfg.CYCLE_SIGMA),
                cfg.CYCLE_MIN_FACTOR * typical, cfg.CYCLE_MAX_FACTOR * typical,
            ))
            rework_h = float(rng.uniform(*cfg.REWORK_HOURS))

            # Find the first moment this job can really start: lane free, parts on the shelf, and
            # enough of the shift left. The lot it gets decides whether it fails, and failing adds
            # rework time, so all of that is settled before any parts are taken.
            start = max(ready[i], lane_free[lane], previous_start)
            scheduled = False
            while start < cfg.CUTOFF_MIN:
                day = work_minute_to_datetime(start).date()
                look = inventory.check(day, serials[i])
                if not look.ok:  # a part is missing: wait for tomorrow morning's top-up
                    start = next_shift_start(start)
                    continue
                substitute = station.code == cfg.SPIKE_STATION and any(
                    inventory.is_spot_buy_lot(look.lots[pid]) for pid in spike_part_ids
                )
                failed = fail_draw < (cfg.SUBSTITUTE_FAIL_RATE if substitute else station.fail_rate)
                cycle_min = round(cycle_h * 60)
                total_min = round((cycle_h + (rework_h if failed else 0.0)) * 60)
                if start % cfg.SHIFT_MIN + total_min > cfg.SHIFT_MIN:  # would run past the end of the shift
                    start = next_shift_start(start)
                    continue
                scheduled = True
                break
            if not scheduled:  # never started before the data was extracted
                finished_at[i] = cfg.CUTOFF_MIN + 1
                previous_start = max(previous_start, start)  # a blocked job at the head holds up the queue
                continue

            taken = inventory.take(day, serials[i])
            previous_start = start
            lane_free[lane] = finished_at[i] = start + total_min
            if station.code == cfg.SPIKE_STATION:
                on_substitute_lot[i] = substitute
            lots_used.extend(
                {"serial_number": serials[i], "station_code": station.code, "part_id": pid, "lot_id": lot}
                for pid, lot in taken.lots.items()
            )

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
                    "defect_code": _pick_defect(rng, station, bool(substitute)) if failed else None,
                })
            if failed and done:  # rework always passes the second inspection
                inspections.append({
                    "serial_number": serials[i], "station_code": station.code, "attempt": 2,
                    "inspected_ts": end_ts, "result": "PASS", "defect_code": None,
                })
        ready = finished_at

        inventory.finish(LAST_DAY)
        receiving.append(inventory.receiving())
        snapshots.append(inventory.snapshots())

    return LineResult(
        stations=_stations_table(),
        work_orders=_with_ids(pd.DataFrame(work_orders), "wo_id", "WO", ["start_ts", "station_code"]),
        inspections=_with_ids(pd.DataFrame(inspections), "inspection_id", "INS", ["inspected_ts", "station_code", "attempt"]),
        receiving=pd.concat(receiving, ignore_index=True).sort_values(
            ["order_date", "part_id", "shipment_id"], kind="stable").reset_index(drop=True),
        inventory_snapshots=pd.concat(snapshots, ignore_index=True).sort_values(
            ["snapshot_date", "part_id", "location"], kind="stable").reset_index(drop=True),
        drone_part_lots=pd.DataFrame(lots_used),
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
