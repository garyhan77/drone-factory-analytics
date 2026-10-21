"""Warehouse and line-side stock for the parts used at one station.

The component is driven by calendar days. Each weekday goes in this order:

  1. Morning:     shipments due today arrive at the warehouse, then kitters top up line-side.
  2. During day:  jobs call try_start(); a job starts only if every part it needs is on the line-side
                  shelf, and takes the oldest lot first (FIFO).
  3. End of day:  reorder check (after the day's consumption), then the emergency-buy check,
                  then a snapshot. Weekends have no operations but still get a snapshot.

Time only moves forward: calling advance_to() or try_start() with an earlier day is an error.
"""
from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from factory import config as cfg

WAREHOUSE, LINE_SIDE = "WAREHOUSE", "LINE_SIDE"


def next_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def previous_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def week_of_date(d: date) -> int:
    """1-based simulation week."""
    return (d - cfg.START).days // 7 + 1


@dataclass(frozen=True)
class PartSpec:
    part_id: str
    name: str
    supplier_id: str
    qty_per_drone: int
    reorder_point: int
    lead_days: int
    launch_daily_units: float  # expected units used per calendar day at launch


@dataclass(frozen=True)
class Policy:
    kitting_cap: int  # pieces moved warehouse to line-side per day, for the whole station
    line_side_target_days: float
    order_cover_days: int
    demand_window_days: int
    spot_buy_after_blocked_days: int
    spot_buy_cover_days: int
    spot_buy_lead_days: int
    spot_buy_eligible_supplier: str  # only this supplier's parts can trigger an emergency buy
    spot_buy_supplier: str

    @classmethod
    def from_config(cls) -> Policy:
        return cls(
            kitting_cap=cfg.KITTING_CAP_PIECES_PER_DAY,
            line_side_target_days=cfg.LINE_SIDE_TARGET_DAYS,
            order_cover_days=cfg.ORDER_COVER_DAYS,
            demand_window_days=cfg.DEMAND_WINDOW_DAYS,
            spot_buy_after_blocked_days=cfg.SPOT_BUY_AFTER_BLOCKED_DAYS,
            spot_buy_cover_days=cfg.SPOT_BUY_COVER_DAYS,
            spot_buy_lead_days=next(s.lead_days for s in cfg.SUPPLIERS if s.supplier_id == cfg.SPOT_BUY),
            spot_buy_eligible_supplier=cfg.RIDGELINE,
            spot_buy_supplier=cfg.SPOT_BUY,
        )


# (supplier_id, expected_date, qty, rng) -> (arrival_date, quantity_that_arrives)
Delivery = Callable[[str, date, int, np.random.Generator], "tuple[date, int]"]


def config_delivery(supplier_id: str, expected: date, qty: int, rng: np.random.Generator) -> tuple[date, int]:
    """When a regular shipment really arrives and how much of it, from the supplier-behaviour config.

    Ridgeline's disruption is keyed to the week the shipment was EXPECTED, not when it was ordered.
    """
    if supplier_id == cfg.SPOT_BUY:
        return expected, qty
    disrupted = supplier_id == cfg.RIDGELINE and week_of_date(expected) in cfg.RIDGELINE_DISRUPTION_WEEKS
    late_p, late_days = (cfg.RIDGELINE_LATE_PROB, cfg.RIDGELINE_LATE_DAYS) if disrupted else (cfg.LATE_PROB, cfg.LATE_DAYS)
    short_p, short_frac = (
        (cfg.RIDGELINE_SHORT_PROB, cfg.RIDGELINE_SHORT_FRACTION) if disrupted else (cfg.SHORT_PROB, cfg.SHORT_FRACTION)
    )
    # Always draw the same four numbers so the random stream does not depend on the outcome.
    is_late, days, is_short, fraction = rng.random(), rng.integers(late_days[0], late_days[1] + 1), rng.random(), rng.uniform(*short_frac)
    arrival = next_weekday(expected + timedelta(days=int(days))) if is_late < late_p else expected
    received = max(1, int(qty * fraction)) if is_short < short_p else qty
    return arrival, received


@dataclass
class StartResult:
    ok: bool
    lots: dict[str, str]  # part_id -> lot of the first unit used (empty if the job could not start)
    blocked_parts: list[str]


@dataclass
class _Shipment:
    shipment_id: str
    lot_id: str
    supplier_id: str
    part_id: str
    order_date: date
    expected_date: date
    arrival_date: date  # when it will really arrive
    qty_expected: int
    qty_arriving: int
    received_date: date | None = None
    qty_received: int | None = None


def default_initial(parts: list[PartSpec], policy: Policy) -> dict[str, tuple[int, int]]:
    """Starting (warehouse, line-side) stock: the order-up-to level, with line-side at its target."""
    initial = {}
    for p in parts:
        line_side = max(p.qty_per_drone, math.ceil(policy.line_side_target_days * p.launch_daily_units * 7 / 5))
        total = p.reorder_point + math.ceil(policy.order_cover_days * p.launch_daily_units)
        initial[p.part_id] = (max(0, total - line_side), line_side)
    return initial


class StationInventory:
    def __init__(
        self,
        station_code: str,
        parts: list[PartSpec],
        initial: dict[str, tuple[int, int]],
        start_day: date,
        *,
        policy: Policy | None = None,
        delivery: Delivery = config_delivery,
        seed: int = 0,
    ):
        if start_day.weekday() >= 5:
            raise ValueError("start_day must be a weekday")
        self.station_code = station_code
        self.parts = list(parts)  # kit list order
        self.policy = policy or Policy.from_config()
        self._delivery = delivery
        self._day = start_day
        self._last_day_closed: date | None = None

        self._warehouse: dict[str, deque[list]] = {p.part_id: deque() for p in parts}  # [lot_id, qty]
        self._line_side: dict[str, deque[list]] = {p.part_id: deque() for p in parts}
        self._open: dict[str, list[_Shipment]] = {p.part_id: [] for p in parts}
        self._shipments: list[_Shipment] = []
        self._rngs = {p.part_id: np.random.default_rng([seed, i]) for i, p in enumerate(parts)}
        self._lot_counter = {p.part_id: 0 for p in parts}
        self._lot_supplier: dict[str, str] = {}
        self._demand: dict[str, dict[date, int]] = {p.part_id: {} for p in parts}
        self._seen_serials: set[str] = set()
        self._blocked_today: set[str] = set()
        self._stocked_out_streak = {p.part_id: 0 for p in parts}  # working days in a row truly out of stock
        self._snapshots: list[tuple] = []

        for p in parts:
            warehouse_qty, line_side_qty = initial[p.part_id]
            if warehouse_qty + line_side_qty > 0:
                self._add_pre_launch_stock(p, warehouse_qty, line_side_qty, start_day)
        self._start_of_day(start_day)

    # ------------------------------------------------------------------ public API

    def advance_to(self, day: date) -> None:
        """Run the end of the current day and the morning of each following day, up to `day`."""
        if day < self._day:
            raise ValueError(f"time cannot go backwards: at {self._day}, asked for {day}")
        while self._day < day:
            self._end_of_day(self._day)
            self._day += timedelta(days=1)
            self._start_of_day(self._day)

    def try_start(self, day: date, serial: str) -> StartResult:
        """Try to start a drone at this station. Takes the parts only if every one is available."""
        result = self.check(day, serial)
        return self.take(day, serial) if result.ok else result

    def check(self, day: date, serial: str) -> StartResult:
        """Look at whether a drone could start now, and which lots it would get, without taking anything.

        Advances time to `day`, counts the drone's demand (once), and records which parts blocked it.
        """
        if day.weekday() >= 5:
            raise ValueError("no production on weekends")
        self.advance_to(day)
        if serial not in self._seen_serials:  # demand counts once per drone, however often it is retried
            self._seen_serials.add(serial)
            for p in self.parts:
                self._demand[p.part_id][day] = self._demand[p.part_id].get(day, 0) + p.qty_per_drone
        blocked = [p.part_id for p in self.parts if self._total(self._line_side, p.part_id) < p.qty_per_drone]
        if blocked:
            self._blocked_today.update(blocked)
            return StartResult(False, {}, blocked)
        return StartResult(True, {p.part_id: self._line_side[p.part_id][0][0] for p in self.parts}, [])

    def take(self, day: date, serial: str) -> StartResult:
        """Take the parts for a drone that check() said could start. Returns the lots used."""
        if day != self._day:
            raise ValueError(f"take() must be called on the day of check(): at {self._day}, got {day}")
        short = [p.part_id for p in self.parts if self._total(self._line_side, p.part_id) < p.qty_per_drone]
        if short:
            raise ValueError(f"cannot take parts, short of: {short}")
        return StartResult(True, {p.part_id: self._take(p) for p in self.parts}, [])

    def finish(self, last_day: date) -> None:
        """Run through the end of `last_day` so its snapshot is recorded."""
        self.advance_to(last_day)
        if self._last_day_closed != last_day:
            self._end_of_day(last_day)

    def is_spot_buy_lot(self, lot_id: str) -> bool:
        return self._lot_supplier.get(lot_id) == self.policy.spot_buy_supplier

    def warehouse_lots(self, part_id: str) -> list[tuple[str, int]]:
        return [(lot, qty) for lot, qty in self._warehouse[part_id]]

    def line_side_lots(self, part_id: str) -> list[tuple[str, int]]:
        return [(lot, qty) for lot, qty in self._line_side[part_id]]

    def demand_log(self, part_id: str) -> dict[date, int]:
        return dict(self._demand[part_id])

    def snapshots(self) -> pd.DataFrame:
        return pd.DataFrame(self._snapshots, columns=["snapshot_date", "part_id", "location", "on_hand"])

    def receiving(self) -> pd.DataFrame:
        columns = ["shipment_id", "lot_id", "supplier_id", "part_id", "order_date", "expected_date",
                   "received_date", "qty_expected", "qty_received"]
        rows = [(s.shipment_id, s.lot_id, s.supplier_id, s.part_id, s.order_date, s.expected_date,
                 s.received_date, s.qty_expected, s.qty_received) for s in self._shipments]
        df = pd.DataFrame(rows, columns=columns)
        df["qty_received"] = df["qty_received"].astype("Int64")
        return df.sort_values(["order_date", "part_id", "shipment_id"], kind="stable").reset_index(drop=True)

    # ------------------------------------------------------------------ the day

    def _start_of_day(self, day: date) -> None:
        if day.weekday() >= 5:
            return
        for p in self.parts:  # 1. arrivals, before kitting
            for s in sorted((s for s in self._open[p.part_id] if s.arrival_date <= day), key=lambda s: s.shipment_id):
                self._open[p.part_id].remove(s)
                s.received_date, s.qty_received = day, s.qty_arriving
                self._warehouse[p.part_id].append([s.lot_id, s.qty_arriving])
        self._kit(day)  # 2. kitting, before any job starts

    def _end_of_day(self, day: date) -> None:
        if day.weekday() < 5:
            for p in self.parts:
                self._maybe_reorder(p, day)
                self._maybe_spot_buy(p, day)
            for p in self.parts:
                self._stocked_out_streak[p.part_id] = self._stocked_out_streak[p.part_id] + 1 if self._stocked_out(p) else 0
            self._blocked_today.clear()
        for p in self.parts:
            self._snapshots.append((day, p.part_id, WAREHOUSE, self._total(self._warehouse, p.part_id)))
            self._snapshots.append((day, p.part_id, LINE_SIDE, self._total(self._line_side, p.part_id)))
        self._last_day_closed = day

    # ------------------------------------------------------------------ rules

    def _rates(self, p: PartSpec, upto: date) -> tuple[float, float]:
        """Recent demand per calendar day and per working day, over the trailing window ending `upto`."""
        window = self.policy.demand_window_days
        days = [upto - timedelta(days=i) for i in range(window)]
        total = sum(self._demand[p.part_id].get(d, 0) for d in days)
        weekdays = sum(1 for d in days if d.weekday() < 5)
        return max(total / window, p.launch_daily_units), max(total / weekdays, p.launch_daily_units * 7 / 5)

    def _kit(self, day: date) -> None:
        """Move parts from the warehouse to line-side, in kit-list order, until the daily cap runs out."""
        cap_left = self.policy.kitting_cap
        for p in self.parts:
            if cap_left <= 0:
                break
            _, per_working_day = self._rates(p, day - timedelta(days=1))
            target = max(p.qty_per_drone, math.ceil(self.policy.line_side_target_days * per_working_day))
            need = target - self._total(self._line_side, p.part_id)
            move = min(need, self._total(self._warehouse, p.part_id), cap_left)
            if move > 0:
                self._transfer(p.part_id, move)
                cap_left -= move

    def _position(self, p: PartSpec) -> int:
        on_order = sum(s.qty_expected for s in self._open[p.part_id])
        return self._total(self._warehouse, p.part_id) + self._total(self._line_side, p.part_id) + on_order

    def _maybe_reorder(self, p: PartSpec, day: date) -> None:
        position = self._position(p)
        if position > p.reorder_point:
            return
        per_calendar_day, _ = self._rates(p, day)
        qty = max(1, p.reorder_point + math.ceil(self.policy.order_cover_days * per_calendar_day) - position)
        expected = next_weekday(day + timedelta(days=p.lead_days))
        arrival, arriving = self._delivery(p.supplier_id, expected, qty, self._rngs[p.part_id])
        self._place(p, "LOT", p.supplier_id, day, expected, arrival, qty, arriving)

    def _stocked_out(self, p: PartSpec) -> bool:
        """Work was blocked on this part today AND the warehouse has nothing left to kit.

        A part that is blocked only because kitters ran out of time is not a supply problem,
        so it does not trigger an emergency buy.
        """
        return p.part_id in self._blocked_today and self._total(self._warehouse, p.part_id) == 0

    def _maybe_spot_buy(self, p: PartSpec, day: date) -> None:
        if p.supplier_id != self.policy.spot_buy_eligible_supplier:
            return
        stocked_out_days = self._stocked_out_streak[p.part_id] + (1 if self._stocked_out(p) else 0)
        if stocked_out_days < self.policy.spot_buy_after_blocked_days:
            return
        if any(s.supplier_id == self.policy.spot_buy_supplier for s in self._open[p.part_id]):
            return
        per_calendar_day, _ = self._rates(p, day)
        qty = max(1, math.ceil(self.policy.spot_buy_cover_days * per_calendar_day))
        expected = next_weekday(day + timedelta(days=self.policy.spot_buy_lead_days))
        self._place(p, "SUB", self.policy.spot_buy_supplier, day, expected, expected, qty, qty)

    # ------------------------------------------------------------------ bookkeeping

    def _place(self, p, prefix, supplier, order_day, expected, arrival, qty, arriving) -> None:
        self._lot_counter[p.part_id] += 1
        n = self._lot_counter[p.part_id]
        shipment = _Shipment(f"SHP-{p.part_id}-{n:03d}", f"{prefix}-{p.part_id}-{n:03d}", supplier, p.part_id,
                             order_day, expected, arrival, qty, arriving)
        self._lot_supplier[shipment.lot_id] = supplier
        self._open[p.part_id].append(shipment)
        self._shipments.append(shipment)

    def _add_pre_launch_stock(self, p: PartSpec, warehouse_qty: int, line_side_qty: int, start_day: date) -> None:
        """Starting stock arrives as one pre-launch shipment, so its lot has a matching receiving row."""
        received = previous_weekday(start_day - timedelta(days=21))
        self._lot_counter[p.part_id] += 1
        n = self._lot_counter[p.part_id]
        total = warehouse_qty + line_side_qty
        shipment = _Shipment(f"SHP-{p.part_id}-{n:03d}", f"LOT-{p.part_id}-{n:03d}", p.supplier_id, p.part_id,
                             previous_weekday(received - timedelta(days=p.lead_days)), received, received,
                             total, total, received, total)
        self._lot_supplier[shipment.lot_id] = p.supplier_id
        self._shipments.append(shipment)
        if warehouse_qty:
            self._warehouse[p.part_id].append([shipment.lot_id, warehouse_qty])
        if line_side_qty:
            self._line_side[p.part_id].append([shipment.lot_id, line_side_qty])

    @staticmethod
    def _total(stock: dict[str, deque[list]], part_id: str) -> int:
        return sum(qty for _, qty in stock[part_id])

    def _transfer(self, part_id: str, qty: int) -> None:
        """Move qty from the warehouse to line-side, oldest lot first."""
        warehouse, line_side = self._warehouse[part_id], self._line_side[part_id]
        while qty > 0:
            lot = warehouse[0]
            moved = min(qty, lot[1])
            lot[1] -= moved
            qty -= moved
            if line_side and line_side[-1][0] == lot[0]:
                line_side[-1][1] += moved
            else:
                line_side.append([lot[0], moved])
            if lot[1] == 0:
                warehouse.popleft()

    def _take(self, p: PartSpec) -> str:
        """Use qty_per_drone units from line-side, oldest lot first. Returns the lot of the first unit."""
        shelf, need, first_lot = self._line_side[p.part_id], p.qty_per_drone, None
        while need > 0:
            lot = shelf[0]
            used = min(need, lot[1])
            first_lot = first_lot or lot[0]
            lot[1] -= used
            need -= used
            if lot[1] == 0:
                shelf.popleft()
        return first_lot
