"""The inventory component, driven through a tiny two-part station whose numbers can be checked by hand.

Part T-001 ("Ridge bolt") comes from SUP-R, the only supplier eligible for emergency buys.
  1 per drone, reorder point 4, lead time 2 days, launch use 1.0 a day.
Part T-002 ("Plate") comes from SUP-O.
  2 per drone, reorder point 6, lead time 3 days, launch use 2.0 a day.

Policy: line-side target 2 working days, orders go up to the reorder point + 3 days of demand,
emergency buy after 2 blocked working days (3 days of demand, 2-day lead time).
With no history, demand falls back to the launch figures: 1.0 and 2.0 a day, or 1.4 and 2.8 per
working day. So the line-side target is ceil(2 x 1.4) = 3 bolts and ceil(2 x 2.8) = 6 plates.

Day 0 is a Monday: d(0) Mon, d(1) Tue, d(2) Wed, d(3) Thu, d(4) Fri, d(5) Sat, d(6) Sun, d(7) Mon.
"""
from datetime import date, timedelta

import numpy as np
import pytest

from factory import config as cfg
from factory.dimensions import part_specs
from factory.inventory import (
    LINE_SIDE, WAREHOUSE, PartSpec, Policy, StationInventory, config_delivery, default_initial,
    next_weekday, previous_weekday,
)

MON = date(2026, 3, 2)


def d(n: int) -> date:
    return MON + timedelta(days=n)


PARTS = [
    PartSpec("T-001", "Ridge bolt", "SUP-R", qty_per_drone=1, reorder_point=4, lead_days=2, launch_daily_units=1.0),
    PartSpec("T-002", "Plate", "SUP-O", qty_per_drone=2, reorder_point=6, lead_days=3, launch_daily_units=2.0),
]
POLICY = Policy(
    kitting_cap=100, line_side_target_days=2, order_cover_days=3, demand_window_days=14,
    spot_buy_after_blocked_days=2, spot_buy_cover_days=3, spot_buy_lead_days=2,
    spot_buy_eligible_supplier="SUP-R", spot_buy_supplier="SUP-S",
)
STOCKED = {"T-001": (5, 2), "T-002": (10, 4)}  # (warehouse, line-side) at the start
EMPTY = {"T-001": (0, 0), "T-002": (0, 0)}


def on_time(supplier, expected, qty, rng):
    return expected, qty


def make(initial=STOCKED, start=MON, policy=POLICY, delivery=on_time, seed=0, parts=PARTS):
    return StationInventory("TST", parts, initial, start, policy=policy, delivery=delivery, seed=seed)


def shipments(inv, part_id):
    r = inv.receiving()
    return r[r["part_id"] == part_id].reset_index(drop=True)


# ---------------------------------------------------------------------------- opening state

def test_opening_morning_tops_line_side_up_to_the_target():
    inv = make()
    # T-001: target 3, had 2 on the shelf, so 1 moves. T-002: target 6, had 4, so 2 move.
    assert inv.line_side_lots("T-001") == [("LOT-T-001-001", 3)]
    assert inv.warehouse_lots("T-001") == [("LOT-T-001-001", 4)]
    assert inv.line_side_lots("T-002") == [("LOT-T-002-001", 6)]
    assert inv.warehouse_lots("T-002") == [("LOT-T-002-001", 8)]


def test_starting_stock_appears_as_a_pre_launch_shipment_with_its_own_lot():
    r = make().receiving().set_index("part_id")
    assert list(r.index) == ["T-001", "T-002"]
    assert r.loc["T-001", "lot_id"] == "LOT-T-001-001"
    assert r.loc["T-001", "received_date"] == date(2026, 2, 9)  # 21 days before launch, a weekday
    assert (r.loc["T-001", "qty_expected"], r.loc["T-001", "qty_received"]) == (7, 7)  # 5 + 2
    assert (r.loc["T-002", "qty_expected"], r.loc["T-002", "qty_received"]) == (14, 14)  # 10 + 4
    assert r["order_date"].map(lambda x: x.weekday() < 5).all()


# ---------------------------------------------------------------------------- consuming

def test_a_job_takes_its_parts_and_reports_the_lot_of_the_first_unit():
    inv = make()
    result = inv.try_start(MON, "S1")
    assert result.ok and result.blocked_parts == []
    assert result.lots == {"T-001": "LOT-T-001-001", "T-002": "LOT-T-002-001"}
    assert inv.line_side_lots("T-001") == [("LOT-T-001-001", 2)]
    assert inv.line_side_lots("T-002") == [("LOT-T-002-001", 4)]


def test_a_job_that_is_missing_any_part_takes_nothing():
    inv = make({"T-001": (5, 2), "T-002": (0, 1)})  # one plate on the shelf, two needed
    result = inv.try_start(MON, "S1")
    assert not result.ok and result.blocked_parts == ["T-002"]
    assert inv.line_side_lots("T-001") == [("LOT-T-001-001", 3)]  # the bolt was not taken


def test_demand_counts_once_per_drone_however_often_it_retries():
    inv = make(EMPTY)
    for day in (MON, d(1), d(2)):
        assert not inv.try_start(day, "S1").ok
    assert inv.demand_log("T-001") == {MON: 1}
    assert inv.demand_log("T-002") == {MON: 2}


# ---------------------------------------------------------------------------- daily ordering

def test_reorder_is_checked_at_the_end_of_the_day_after_consumption():
    inv = make()
    for serial in ("S1", "S2", "S3"):  # uses all 3 bolts and 6 plates on the shelf
        assert inv.try_start(MON, serial).ok
    blocked = inv.try_start(MON, "S4")
    assert not blocked.ok and blocked.blocked_parts == ["T-001", "T-002"]
    assert len(inv.receiving()) == 2  # nothing ordered yet: it is still Monday

    inv.advance_to(d(1))  # closes Monday
    bolts = shipments(inv, "T-001")
    # Bolts: 4 in the warehouse + 0 on the shelf = 4, which is at the reorder point of 4.
    # Order up to 4 + ceil(3 x 1.0) = 7, so qty 4 + 3 - 4 = 3. Ordered Monday, due Monday + 2 = Wednesday.
    assert len(bolts) == 2
    assert (bolts.loc[1, "order_date"], bolts.loc[1, "expected_date"], bolts.loc[1, "qty_expected"]) == (MON, d(2), 3)
    assert bolts["received_date"].isna()[1]  # still in transit
    assert len(shipments(inv, "T-002")) == 1  # plates: 8 in the warehouse, above the reorder point of 6


def test_after_the_next_morning_top_up_the_blocked_job_can_start():
    inv = make()
    for serial in ("S1", "S2", "S3"):
        inv.try_start(MON, serial)
    assert not inv.try_start(MON, "S4").ok
    assert inv.try_start(d(1), "S4").ok  # Tuesday's top-up refilled the shelf from the warehouse
    assert inv.warehouse_lots("T-001") == [("LOT-T-001-001", 1)]  # 4 - 3 moved


def test_morning_order_is_arrival_then_kitting_then_jobs():
    quiet = Policy(**{**POLICY.__dict__, "spot_buy_after_blocked_days": 99})
    inv = make(EMPTY, policy=quiet)
    assert not inv.try_start(MON, "S1").ok
    # End of Monday: bolts (position 0 <= 4) order 4 + 3 - 0 = 7, due Wed; plates (0 <= 6) order 6 + 6 - 0 = 12, due Thu.
    assert not inv.try_start(d(1), "S1").ok  # Tuesday: an order placed Monday evening has not arrived
    assert len(inv.receiving()) == 2  # the open orders count toward position, so no second order Tuesday evening

    wed = inv.try_start(d(2), "S1")  # Wednesday morning: bolts arrive, then are kitted, before the job tries
    assert wed.blocked_parts == ["T-002"]  # the bolt shelf was filled in time; plates are not due until Thursday
    assert inv.line_side_lots("T-001") == [("LOT-T-001-001", 3)]  # 7 arrived, 3 kitted
    assert inv.warehouse_lots("T-001") == [("LOT-T-001-001", 4)]

    thu = inv.try_start(d(3), "S1")
    assert thu.ok  # plates arrived and were kitted this morning, then the job started
    assert thu.lots["T-002"] == "LOT-T-002-001"


def test_weekends_have_no_operations_but_still_get_snapshots():
    inv = make(EMPTY, start=d(4))  # starts on a Friday
    assert not inv.try_start(d(4), "S1").ok
    with pytest.raises(ValueError):
        inv.try_start(d(5), "S1")  # Saturday
    inv.finish(d(7))
    bolts = shipments(inv, "T-001")
    # Ordered Friday, lead 2 days is Sunday, which moves to Monday.
    assert bolts.loc[0, "expected_date"] == d(7)
    assert bolts.loc[0, "received_date"] == d(7)
    snap = inv.snapshots()
    for day in (d(4), d(5), d(6)):
        rows = snap[(snap["snapshot_date"] == day) & (snap["part_id"] == "T-001")]
        assert set(rows["on_hand"]) == {0}
    assert len(snap[snap["snapshot_date"] == d(5)]) == 4  # a Saturday snapshot exists: 2 parts x 2 locations


def test_time_cannot_go_backwards():
    inv = make()
    inv.advance_to(d(3))
    with pytest.raises(ValueError):
        inv.try_start(d(1), "S1")
    with pytest.raises(ValueError):
        inv.advance_to(d(2))


def test_a_delivery_function_that_moves_the_arrival_is_honoured_and_lands_on_a_weekday():
    def three_days_late(supplier, expected, qty, rng):
        return next_weekday(expected + timedelta(days=3)), qty

    inv = make(EMPTY, delivery=three_days_late, policy=Policy(**{**POLICY.__dict__, "spot_buy_after_blocked_days": 99}))
    inv.try_start(MON, "S1")
    inv.finish(d(8))
    bolts = shipments(inv, "T-001")
    assert bolts.loc[0, "expected_date"] == d(2)  # Wednesday
    assert bolts.loc[0, "received_date"] == d(7)  # Wednesday + 3 days is Saturday, so Monday


def test_a_short_shipment_is_recorded_and_the_shortfall_triggers_a_new_order():
    def half(supplier, expected, qty, rng):
        return expected, qty // 2

    inv = make(EMPTY, delivery=half, policy=Policy(**{**POLICY.__dict__, "spot_buy_after_blocked_days": 99}))
    inv.try_start(MON, "S1")
    inv.finish(d(2))  # through Wednesday, when the first bolt order lands
    bolts = shipments(inv, "T-001")
    assert (bolts.loc[0, "qty_expected"], bolts.loc[0, "qty_received"]) == (7, 3)
    # 3 bolts arrived, which is under the reorder point of 4: another order goes out Wednesday evening.
    assert len(bolts) == 2 and bolts.loc[1, "order_date"] == d(2) and bolts.loc[1, "qty_expected"] == 4


# ---------------------------------------------------------------------------- emergency buys

def late_for_sup_r(supplier, expected, qty, rng):
    if supplier == "SUP-R":
        return next_weekday(expected + timedelta(days=21)), qty
    return expected, qty


def test_an_emergency_buy_follows_two_blocked_days_in_a_row_and_only_one_is_open_at_a_time():
    inv = make(EMPTY, delivery=late_for_sup_r)
    inv.try_start(MON, "S1")
    inv.advance_to(d(1))  # closes Monday: one blocked day is not enough
    assert (shipments(inv, "T-001")["supplier_id"] != "SUP-S").all()

    inv.try_start(d(1), "S1")
    inv.advance_to(d(2))  # closes Tuesday: two blocked days in a row
    spot = shipments(inv, "T-001").query("supplier_id == 'SUP-S'")
    assert len(spot) == 1
    row = spot.iloc[0]
    assert row["lot_id"] == "SUB-T-001-002" and row["order_date"] == d(1)
    assert row["expected_date"] == d(3) and row["qty_expected"] == 3  # 3 days of demand at 1.0 a day

    inv.try_start(d(2), "S1")
    inv.advance_to(d(3))  # closes Wednesday: still blocked, but one emergency buy is already open
    assert len(shipments(inv, "T-001").query("supplier_id == 'SUP-S'")) == 1


def test_the_substitute_lot_reaches_the_job_and_is_flagged():
    inv = make(EMPTY, delivery=late_for_sup_r)
    for day in (MON, d(1), d(2)):
        assert not inv.try_start(day, "S1").ok
    thu = inv.try_start(d(3), "S1")  # the emergency lot and the plates both landed this morning
    assert thu.ok
    assert thu.lots["T-001"] == "SUB-T-001-002"
    assert inv.is_spot_buy_lot(thu.lots["T-001"])
    assert not inv.is_spot_buy_lot(thu.lots["T-002"])


def test_parts_from_other_suppliers_never_trigger_an_emergency_buy():
    inv = make(EMPTY, delivery=late_for_sup_r)
    for day in (MON, d(1), d(2)):
        inv.try_start(day, "S1")
    inv.advance_to(d(3))
    assert (shipments(inv, "T-002")["supplier_id"] != "SUP-S").all()


# ---------------------------------------------------------------------------- lots and kitting

def test_lots_are_used_oldest_first_and_a_job_spanning_two_lots_records_the_first():
    inv = make({"T-001": (6, 3), "T-002": (0, 1)})  # only one plate on the shelf; a job needs two
    assert not inv.try_start(MON, "S1").ok
    inv.advance_to(d(3))  # the plate order (11, due Thursday) arrives and is kitted
    assert inv.line_side_lots("T-002") == [("LOT-T-002-001", 1), ("LOT-T-002-002", 5)]
    result = inv.try_start(d(3), "S1")
    assert result.ok and result.lots["T-002"] == "LOT-T-002-001"  # first unit came from the older lot
    assert inv.line_side_lots("T-002") == [("LOT-T-002-002", 4)]


def test_when_the_kitting_cap_binds_the_kit_list_order_decides_which_part_starves():
    capped = Policy(**{**POLICY.__dict__, "kitting_cap": 3})
    inv = make({"T-001": (10, 0), "T-002": (10, 0)}, policy=capped)
    # Cap of 3 is spent on the first part on the list (target 3), leaving nothing for the second.
    assert inv.line_side_lots("T-001") == [("LOT-T-001-001", 3)]
    assert inv.line_side_lots("T-002") == []
    assert inv.warehouse_lots("T-002") == [("LOT-T-002-001", 10)]  # stock is in the warehouse, not at the line
    inv.advance_to(d(1))  # the next morning the first part is full, so the cap reaches the second
    assert inv.line_side_lots("T-002") == [("LOT-T-002-001", 3)]


# ---------------------------------------------------------------------------- invariants

def test_snapshots_have_one_row_per_part_location_and_calendar_day():
    inv = make()
    inv.finish(d(6))
    snap = inv.snapshots()
    assert len(snap) == 7 * 2 * 2
    assert set(snap["location"]) == {WAREHOUSE, LINE_SIDE}
    fri = snap[snap["snapshot_date"] == d(4)].set_index(["part_id", "location"])["on_hand"]
    sun = snap[snap["snapshot_date"] == d(6)].set_index(["part_id", "location"])["on_hand"]
    assert fri.equals(sun)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_stock_is_conserved_over_a_random_run(seed):
    """Everything received is either used, in the warehouse, or on the shelf."""
    rng = np.random.default_rng(seed)

    def random_delivery(supplier, expected, qty, r):
        late = int(r.integers(0, 4))
        return next_weekday(expected + timedelta(days=late)), max(1, int(qty * r.uniform(0.6, 1.0)))

    inv = make(delivery=random_delivery, seed=seed)
    waiting, used, serial = [], {"T-001": 0, "T-002": 0}, 0
    for n in range(60):
        day = d(n)
        if day.weekday() >= 5:
            continue
        for _ in range(int(rng.integers(0, 5))):
            serial += 1
            waiting.append(f"S{serial}")
        for s in list(waiting):
            result = inv.try_start(day, s)
            if result.ok:
                waiting.remove(s)
                for p in PARTS:
                    used[p.part_id] += p.qty_per_drone
    inv.finish(d(59))

    received = inv.receiving().dropna(subset=["received_date"]).groupby("part_id")["qty_received"].sum()
    for p in PARTS:
        on_hand = sum(q for _, q in inv.warehouse_lots(p.part_id)) + sum(q for _, q in inv.line_side_lots(p.part_id))
        assert received[p.part_id] == used[p.part_id] + on_hand
    assert sum(used.values()) > 0


def test_same_seed_gives_identical_tables_and_a_different_seed_does_not():
    def run(seed):
        inv = StationInventory("TST", PARTS, STOCKED, MON, policy=POLICY, delivery=config_delivery, seed=seed)
        for n in range(60):
            if d(n).weekday() < 5:
                inv.try_start(d(n), f"S{n}a")
                inv.try_start(d(n), f"S{n}b")
        inv.finish(d(59))
        return inv.receiving(), inv.snapshots()

    (r1, s1), (r1b, s1b), (r2, _) = run(1), run(1), run(2)
    assert r1.equals(r1b) and s1.equals(s1b)
    assert not r1.equals(r2)


# ---------------------------------------------------------------------------- supplier behaviour

def draws(supplier, expected, n=4000, qty=100, seed=0):
    rng = np.random.default_rng(seed)
    return [config_delivery(supplier, expected, qty, rng) for _ in range(n)]


WEEK_10 = cfg.START + timedelta(days=9 * 7)  # a Monday inside Ridgeline's disruption
WEEK_3 = cfg.START + timedelta(days=2 * 7)


def test_ridgeline_is_late_and_short_far_more_often_when_the_shipment_is_due_in_the_disruption_weeks():
    bad, normal = draws(cfg.RIDGELINE, WEEK_10), draws(cfg.RIDGELINE, WEEK_3)
    late = lambda res, due: np.mean([a > due for a, _ in res])
    short = lambda res: np.mean([q < 100 for _, q in res])
    assert late(bad, WEEK_10) == pytest.approx(cfg.RIDGELINE_LATE_PROB, abs=0.03)
    assert short(bad) == pytest.approx(cfg.RIDGELINE_SHORT_PROB, abs=0.04)
    assert late(normal, WEEK_3) == pytest.approx(cfg.LATE_PROB, abs=0.03)
    assert short(normal) == pytest.approx(cfg.SHORT_PROB, abs=0.02)
    assert late(bad, WEEK_10) > 5 * late(normal, WEEK_3)


def test_other_suppliers_are_normal_even_in_the_disruption_weeks():
    res = draws("SUP-02", WEEK_10)
    assert np.mean([a > WEEK_10 for a, _ in res]) == pytest.approx(cfg.LATE_PROB, abs=0.03)


def test_arrivals_land_on_weekdays_and_disrupted_delays_stay_in_range():
    res = draws(cfg.RIDGELINE, WEEK_10)
    assert all(a.weekday() < 5 for a, _ in res)
    lo, hi = cfg.RIDGELINE_LATE_DAYS
    delays = [(a - WEEK_10).days for a, _ in res if a > WEEK_10]
    assert min(delays) >= lo and max(delays) <= hi + 2  # plus up to 2 more over a weekend
    low, high = cfg.RIDGELINE_SHORT_FRACTION
    shorts = [q for _, q in res if q < 100]
    assert min(shorts) >= low * 100 and max(shorts) <= high * 100


def test_the_disruption_is_keyed_to_the_expected_week_not_the_order_week():
    just_before = cfg.START + timedelta(days=7 * 8)  # first day of week 9 is the first disrupted one
    last_good = just_before - timedelta(days=3)  # the Friday of week 8
    first_after = cfg.START + timedelta(days=7 * 11)  # first day of week 12
    rate = lambda due: np.mean([a > due for a, _ in draws(cfg.RIDGELINE, due, n=1500)])
    assert rate(last_good) < 0.15 and rate(just_before) > 0.85 and rate(first_after) < 0.15


def test_the_spot_buy_distributor_is_always_on_time_and_full():
    assert all(r == (WEEK_10, 100) for r in draws(cfg.SPOT_BUY, WEEK_10, n=50))


# ---------------------------------------------------------------------------- with the real parts

def test_default_starting_stock_covers_the_line_side_target_for_every_real_part():
    specs = part_specs()
    initial = default_initial(specs, Policy.from_config())
    assert len(specs) == 40 and set(initial) == {s.part_id for s in specs}
    for s in specs:
        warehouse, line_side = initial[s.part_id]
        assert line_side >= s.qty_per_drone and warehouse >= 0
        assert warehouse + line_side >= s.reorder_point  # starts above the reorder point
    assert initial["MTR-003"][1] == 16  # motor mount: 2 per drone x 2.79 drones a day x 1.4 x 2 days, rounded up


def test_real_station_parts_are_in_kit_list_order():
    mtr = part_specs("MTR")
    assert [s.part_id for s in mtr] == [f"MTR-{i:03d}" for i in range(1, 9)]
    assert previous_weekday(date(2026, 3, 8)) == date(2026, 3, 6)  # Sunday goes back to Friday


def test_kitters_do_not_work_weekends_so_an_empty_shelf_stays_empty_until_monday():
    inv = make(STOCKED, start=d(4))  # Friday morning top-up: 3 bolts and 6 plates on the shelf
    for serial in ("S1", "S2", "S3"):
        assert inv.try_start(d(4), serial).ok  # the shelf is now empty
    inv.finish(d(6))
    snap = inv.snapshots().set_index(["snapshot_date", "part_id", "location"])["on_hand"]
    for day in (d(4), d(5), d(6)):
        assert snap[(day, "T-001", LINE_SIDE)] == 0  # warehouse still has stock, but nobody moved it
    assert snap[(d(5), "T-001", WAREHOUSE)] == 4
    inv.advance_to(d(7))  # Monday 06:00: kitters are back
    assert sum(q for _, q in inv.line_side_lots("T-001")) == 3


def test_a_part_blocked_only_by_kitting_does_not_trigger_an_emergency_buy():
    """Stock sitting in the warehouse is a kitting problem, not a supply problem."""
    # Plates are first on the kit list and the cap is 2 a day, so the bolt (the part that CAN trigger an
    # emergency buy) is last in line and stays off the shelf for days while 50 sit in the warehouse.
    plates_first = [PARTS[1], PARTS[0]]
    capped = Policy(**{**POLICY.__dict__, "kitting_cap": 2})
    inv = make({"T-001": (50, 0), "T-002": (50, 0)}, policy=capped, parts=plates_first)
    blocked_days = 0
    for day in (MON, d(1), d(2)):
        result = inv.try_start(day, "S1")
        blocked_days += "T-001" in result.blocked_parts
    assert blocked_days == 3  # the bolt really was missing from the shelf on three working days in a row
    inv.advance_to(d(3))
    assert (shipments(inv, "T-001")["supplier_id"] != "SUP-S").all()  # but no emergency buy: the warehouse had stock
    assert sum(q for _, q in inv.warehouse_lots("T-001")) > 40
