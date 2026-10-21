"""Plant known data errors into the clean tables, and record exactly which rows were corrupted.

Each error is tied to an event in the simulated story, not to a fixed week:

  negative_inventory     Ridgeline fastener stock rows, during the fastener outage
  missing_defect_code    Motor & Prop first-attempt failures, while substitute-lot drones are inspected
  orphan_inspections     Motor & Prop rework re-inspections, in the same window
  over_receipt           Ridgeline catch-up shipments, after the first emergency lot
  duplicate_work_orders  Avionics jobs, once its queue is building (re-keyed copies with a new wo_id)
  end_before_start       Avionics completed jobs, in the same window

The plant_* functions are pure: they take a table and the rows that are eligible, and return a corrupted
copy plus the record keys. find_windows() works out the eligible rows from the data itself.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from factory import config as cfg
from factory.dimensions import part_ids


# ---------------------------------------------------------------------------- planting

def _pick(rng: np.random.Generator, eligible: pd.Index, n: int) -> pd.Index:
    n = min(n, len(eligible))
    return pd.Index(sorted(rng.choice(eligible.to_numpy(), size=n, replace=False)))


def plant_negative_inventory(snapshots, eligible, n, rng):
    """Flip the sign of the on-hand quantity. Key: date|part|location."""
    df, chosen = snapshots.copy(), _pick(rng, eligible, n)
    df.loc[chosen, "on_hand"] = -df.loc[chosen, "on_hand"]
    keys = [f"{d}|{p}|{loc}" for d, p, loc in zip(df.loc[chosen, "snapshot_date"], df.loc[chosen, "part_id"], df.loc[chosen, "location"])]
    return df, sorted(keys)


def plant_missing_defect_code(inspections, eligible, n, rng):
    """Blank out the defect code on failed inspections: a mix of NULL and empty or whitespace text."""
    df, chosen = inspections.copy(), _pick(rng, eligible, n)
    blanks = [None, "", None, " "]  # about half NULL, half blank, in a fixed rotation
    for i, idx in enumerate(rng.permutation(chosen.to_numpy())):
        df.loc[idx, "defect_code"] = blanks[i % len(blanks)]
    return df, sorted(df.loc[chosen, "inspection_id"])


def plant_orphan_inspections(inspections, eligible, n, rng):
    """Mistype the serial number so the inspection points at a drone that does not exist."""
    df, chosen = inspections.copy(), _pick(rng, eligible, n)
    df.loc[chosen, "serial_number"] = "DF-9" + df.loc[chosen, "serial_number"].str[4:]
    return df, sorted(df.loc[chosen, "inspection_id"])


def plant_over_receipt(receiving, eligible, n, rng):
    """Record 20 to 50% more received than expected."""
    df, chosen = receiving.copy(), _pick(rng, eligible, n)
    for idx in chosen:
        df.loc[idx, "qty_received"] = math.ceil(df.loc[idx, "qty_expected"] * float(rng.uniform(1.2, 1.5)))
    return df, sorted(df.loc[chosen, "shipment_id"])


def plant_duplicate_work_orders(work_orders, eligible, n, rng):
    """Add re-keyed copies: same drone, station and times, but a new wo_id. Key: the copy's wo_id."""
    chosen = _pick(rng, eligible, n)
    next_id = int(work_orders["wo_id"].str[3:].astype(int).max()) + 1
    copies = work_orders.loc[chosen].copy()
    copies["wo_id"] = [f"WO-{next_id + i:06d}" for i in range(len(copies))]
    return pd.concat([work_orders, copies], ignore_index=True), sorted(copies["wo_id"])


def plant_end_before_start(work_orders, eligible, n, rng):
    """Make a completed job finish 30 minutes to 4 hours before it started."""
    df, chosen = work_orders.copy(), _pick(rng, eligible, n)
    for idx in chosen:
        df.loc[idx, "end_ts"] = df.loc[idx, "start_ts"] - pd.Timedelta(minutes=int(rng.integers(30, 241)))
    return df, sorted(df.loc[chosen, "wo_id"])


# ---------------------------------------------------------------------------- finding the events

@dataclass(frozen=True)
class Windows:
    """Where in the data each error may be planted, as eligible row labels plus readable date ranges."""
    eligible: dict[str, pd.Index]
    ranges: dict[str, tuple[str, str]]


def _spike_fasteners() -> list[str]:
    return [pid for pid, part in zip(part_ids(), cfg.PARTS) if part.name in cfg.SPIKE_FASTENERS]


def find_windows(tables: dict[str, pd.DataFrame]) -> Windows:
    fasteners = _spike_fasteners()
    snap, ins, rec, wo, lots = (tables[k] for k in ("inventory_snapshots", "inspections", "receiving", "work_orders", "drone_part_lots"))
    snap_day = pd.to_datetime(snap["snapshot_date"])
    rec_day = pd.to_datetime(rec["received_date"])
    eligible: dict[str, pd.Index] = {}
    ranges: dict[str, tuple[str, str]] = {}

    # Fastener outage: from the first empty warehouse for a spike fastener to just after the last emergency lot lands.
    emergency = rec[(rec["supplier_id"] == cfg.SPOT_BUY) & rec["part_id"].isin(fasteners) & rec["received_date"].notna()]
    empty = snap[snap["part_id"].isin(fasteners) & (snap["location"] == "WAREHOUSE") & (snap["on_hand"] == 0) & (snap_day.dt.dayofweek < 5)]
    if len(emergency) and len(empty):
        lo = snap_day[empty.index].min()
        hi = rec_day[emergency.index].max() + pd.Timedelta(days=cfg.OUTAGE_PAD_DAYS)
        mask = snap["part_id"].isin(fasteners) & snap_day.between(lo, hi) & (snap["on_hand"] > 0)
        eligible["negative_inventory"], ranges["negative_inventory"] = snap.index[mask], (str(lo.date()), str(hi.date()))
    else:
        eligible["negative_inventory"] = snap.index[:0]

    # Defect spike: from the first to the last Motor & Prop inspection of a drone carrying an emergency fastener.
    sub = lots[lots["part_id"].isin(fasteners) & lots["lot_id"].str.startswith(cfg.SUBSTITUTE_LOT_PREFIX)]["serial_number"].unique()
    at_spike_station = ins["station_code"] == cfg.SPIKE_STATION
    when = pd.to_datetime(ins["inspected_ts"])
    sub_inspections = ins[at_spike_station & ins["serial_number"].isin(sub)]
    if len(sub_inspections):
        lo, hi = when[sub_inspections.index].min().normalize(), when[sub_inspections.index].max().normalize() + pd.Timedelta(days=1)
        in_window = at_spike_station & when.between(lo, hi)
        eligible["missing_defect_code"] = ins.index[in_window & (ins["attempt"] == 1) & (ins["result"] == "FAIL") & ins["defect_code"].notna()]
        eligible["orphan_inspections"] = ins.index[in_window & (ins["attempt"] == 2)]
        ranges["missing_defect_code"] = ranges["orphan_inspections"] = (str(lo.date()), str(hi.date()))
    else:
        eligible["missing_defect_code"] = eligible["orphan_inspections"] = ins.index[:0]

    # Catch-up: Ridgeline regular lots received within a few weeks of the first emergency lot.
    if len(emergency):
        lo = rec_day[emergency.index].min()
        hi = lo + pd.Timedelta(weeks=cfg.CATCH_UP_WEEKS)
        mask = (rec["supplier_id"] == cfg.RIDGELINE) & rec_day.between(lo, hi) & ~rec["lot_id"].str.startswith(cfg.SUBSTITUTE_LOT_PREFIX)
        eligible["over_receipt"], ranges["over_receipt"] = rec.index[mask], (str(lo.date()), str(hi.date()))
    else:
        eligible["over_receipt"] = rec.index[:0]

    # Avionics queue: from the first week its mean wait for the station exceeds the threshold.
    order = {s.code: i for i, s in enumerate(cfg.STATIONS)}
    flow = wo.assign(seq=wo["station_code"].map(order)).sort_values(["serial_number", "seq"])
    flow["wait_h"] = (flow["start_ts"] - flow.groupby("serial_number")["end_ts"].shift()).dt.total_seconds() / 3600
    flow["week"] = (flow["start_ts"] - pd.Timestamp(cfg.START)).dt.days // 7 + 1
    avionics_wait = flow[flow["station_code"] == "AVN"].groupby("week")["wait_h"].mean()
    building = avionics_wait[avionics_wait > cfg.QUEUE_WAIT_THRESHOLD_HOURS]
    avn = wo["station_code"] == "AVN"
    if len(building):
        first_week = int(building.index.min())
        in_queue = avn & ((wo["start_ts"] - pd.Timestamp(cfg.START)).dt.days // 7 + 1 >= first_week)
        eligible["duplicate_work_orders"] = wo.index[in_queue]
        eligible["end_before_start"] = wo.index[in_queue & (wo["status"] == "COMPLETE")]
        start = pd.Timestamp(cfg.START) + pd.Timedelta(weeks=first_week - 1)
        ranges["duplicate_work_orders"] = ranges["end_before_start"] = (str(start.date()), str(wo["start_ts"].max().date()))
    else:
        eligible["duplicate_work_orders"] = eligible["end_before_start"] = wo.index[:0]
    return Windows(eligible, ranges)


# ---------------------------------------------------------------------------- putting it together

def plant_errors(
    tables: dict[str, pd.DataFrame], rng: np.random.Generator, windows: Windows | None = None
) -> tuple[dict[str, pd.DataFrame], dict[str, list[str]], Windows]:
    """Return (corrupted tables, answer key, windows). The input tables are not changed.

    `windows` is worked out from the data unless given (tests pass small hand-made ones).
    """
    windows = windows or find_windows(tables)
    out = {name: df.copy() for name, df in tables.items()}
    key: dict[str, list[str]] = {}
    counts = cfg.PLANTED_COUNTS

    out["inventory_snapshots"], key["negative_inventory"] = plant_negative_inventory(
        out["inventory_snapshots"], windows.eligible["negative_inventory"], counts["negative_inventory"], rng)
    out["inspections"], key["missing_defect_code"] = plant_missing_defect_code(
        out["inspections"], windows.eligible["missing_defect_code"], counts["missing_defect_code"], rng)
    out["inspections"], key["orphan_inspections"] = plant_orphan_inspections(
        out["inspections"], windows.eligible["orphan_inspections"], counts["orphan_inspections"], rng)
    out["receiving"], key["over_receipt"] = plant_over_receipt(
        out["receiving"], windows.eligible["over_receipt"], counts["over_receipt"], rng)

    # End-before-start and duplicates both touch Avionics work orders, so they must not pick the same row:
    # choose the duplicates first, then exclude their originals from the end-before-start candidates.
    work_orders, key["duplicate_work_orders"] = plant_duplicate_work_orders(
        out["work_orders"], windows.eligible["duplicate_work_orders"], counts["duplicate_work_orders"], rng)
    copied = set(work_orders.loc[work_orders["wo_id"].isin(key["duplicate_work_orders"]), ["serial_number", "station_code", "start_ts"]]
                 .itertuples(index=False, name=None))
    originals = out["work_orders"].index[[(s, c, t) in copied for s, c, t in zip(
        out["work_orders"]["serial_number"], out["work_orders"]["station_code"], out["work_orders"]["start_ts"])]]
    still_eligible = windows.eligible["end_before_start"].difference(originals)
    out["work_orders"], key["end_before_start"] = plant_end_before_start(
        work_orders, still_eligible, counts["end_before_start"], rng)

    for guard in cfg.GUARD_CHECKS:
        key[guard] = []
    return out, key, windows
