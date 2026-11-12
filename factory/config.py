"""Every tunable number for the simulation, taken from DOMAIN.md.

Weeks are 1-based: week 1 starts on START. Change numbers here, not in the simulation code.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

SEED = 42

# --- Calendar ---------------------------------------------------------------
START = date(2026, 1, 5)  # a Monday
WEEKS = 12
SHIFT_START_HOUR = 6  # two shifts, 06:00 to 22:00
SHIFT_MIN = 16 * 60
WORK_DAYS = 5
WEEK_MIN = WORK_DAYS * SHIFT_MIN  # working minutes per week
TOTAL_WORK_MIN = WEEKS * WEEK_MIN  # the simulation ends here
EXTRACT_HOURS_BEFORE_END = 8  # the data is pulled at 14:00 on the last Friday, so some jobs are still in progress
CUTOFF_MIN = TOTAL_WORK_MIN - EXTRACT_HOURS_BEFORE_END * 60

# --- Line -------------------------------------------------------------------


@dataclass(frozen=True)
class Station:
    code: str
    name: str
    lanes: int
    cycle_hours: float  # typical cycle time
    fail_rate: float  # baseline fail rate


STATIONS = [
    Station("AFL", "Airframe", 3, 3.0, 0.030),
    Station("WNG", "Wing Assembly", 3, 3.5, 0.035),
    Station("MTR", "Motor & Prop", 2, 2.0, 0.025),
    Station("AVN", "Avionics", 2, 4.4, 0.050),
    Station("FNT", "Final Test", 3, 3.0, 0.040),
]

CYCLE_SIGMA = 0.25  # lognormal spread of cycle times
CYCLE_MIN_FACTOR, CYCLE_MAX_FACTOR = 0.5, 2.5  # cap around the typical time
REWORK_HOURS = (1.0, 2.5)  # extra time when a first inspection fails

# A steady release rate: the same number of drones enter the line every week.
RELEASES_PER_WEEK = 20


def weekly_releases(week: int) -> int:
    """Drones released into the line in a given week (1-based)."""
    return RELEASES_PER_WEEK


# Optional confounder for the analysis layer (analysis/). With a slope above zero, every station's baseline
# first-pass fail rate rises by this much during the weeks when inspectors are swamped (see DOMAIN.md), which
# are also the weeks the substitute lots reach the line. The default of 0 leaves the generated data exactly
# as it was.
FAIL_RATE_PRESSURE_SLOPE = 0.0
PRESSURE_WEEKS = range(11, 16)


def line_pressure(week: int) -> float:
    """1 in the weeks when inspectors are swamped, 0 otherwise."""
    return 1.0 if week in PRESSURE_WEEKS else 0.0


# --- Packing and shipping ---------------------------------------------------
PACK_HOURS = (4, 24)  # working hours from passing Final Test to being packed (random in this range)
SHIP_BATCH_HOUR = 16  # one batch each weekday; everything packed by this time ships that day

# --- Defects ----------------------------------------------------------------
DEFECT_NAMES = {
    "AFL": ["DELAMINATION", "RESIN-VOID", "FIBRE-WRINKLE"],
    "WNG": ["SERVO-BIND", "SKIN-GAP", "SPAR-MISALIGN"],
    "MTR": ["LOOSE-FASTENER", "PROP-IMBALANCE", "MOTOR-NOISE"],
    "AVN": ["SENSOR-CAL-FAIL", "CONNECTOR-SEAT", "FW-FLASH-FAIL"],
    "FNT": ["GPS-LOCK-TIMEOUT", "CONTROL-SURFACE-RANGE", "PAYLOAD-LATCH"],
}

# The defect spike comes from the supply chain: a drone whose Motor & Prop fasteners came from an
# emergency (spot-buy) lot fails more often. See SPIKE_FASTENERS below and factory/inventory.py.
SPIKE_STATION = "MTR"
SUBSTITUTE_FAIL_RATE = 0.50
SUBSTITUTE_LOOSE_FASTENER_SHARE = 0.75  # of those failures
SPIKE_DEFECT = "MTR-LOOSE-FASTENER"


# --- Suppliers ----------------------------------------------------------------


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    name: str
    lead_days: int  # lead time quoted by the supplier


SUPPLIERS = [
    Supplier("SUP-01", "Ridgeline Hardware", 10),  # the unreliable one
    Supplier("SUP-02", "Northgate Composites", 21),
    Supplier("SUP-03", "Meridian Electronics", 21),
    Supplier("SUP-04", "Cobalt Motion", 18),
    Supplier("SUP-05", "Summit Polymers", 10),
    Supplier("SUP-06", "Vector Avionics", 28),
    Supplier("SUP-07", "Granite Packaging", 5),
    Supplier("SUP-08", "Spot-Buy Distributor", 2),  # emergency buys only
]
RIDGELINE, SPOT_BUY = "SUP-01", "SUP-08"

# --- Parts and bill of materials ------------------------------------------------


@dataclass(frozen=True)
class Part:
    station_code: str
    name: str
    supplier_id: str
    unit_cost: float
    qty_per_drone: int


def _p(station, name, supplier, cost, qty):
    return Part(station, name, supplier, float(cost), qty)


PARTS = [
    _p("AFL", "Carbon fibre sheet", "SUP-02", 85, 4),
    _p("AFL", "Epoxy resin kit", "SUP-05", 35, 1),
    _p("WNG", "Wing spar", "SUP-02", 95, 2),
    _p("WNG", "Servo", "SUP-04", 28, 4),
    _p("MTR", "Brushless motor", "SUP-04", 120, 2),
    _p("MTR", "Propeller", "SUP-04", 45, 2),
    _p("MTR", "Motor mount", "SUP-04", 14, 2),
    _p("MTR", "Prop nut", "SUP-01", 1.5, 2),
    _p("MTR", "Speed controller", "SUP-03", 55, 2),
    _p("AVN", "Flight controller", "SUP-06", 310, 1),
    _p("AVN", "Battery pack", "SUP-03", 480, 1),
    _p("FNT", "Shipping crate", "SUP-07", 85, 1),
]

# The Motor & Prop fastener whose substitute lot drives the defect spike. Ridgeline is its only supplier.
SPIKE_FASTENERS = ("Prop nut",)

# --- Supplier behaviour -------------------------------------------------------
LATE_PROB, LATE_DAYS = 0.08, (1, 3)  # normal suppliers: late by 1 to 3 days
SHORT_PROB, SHORT_FRACTION = 0.03, (0.6, 0.95)  # share of the order that arrives when short
# Ridgeline, on shipments expected to arrive in these weeks:
RIDGELINE_DISRUPTION_WEEKS = range(4, 7)
# A multi-week supplier crisis: severe enough that a healthy stock buffer cannot absorb it.
RIDGELINE_LATE_PROB, RIDGELINE_LATE_DAYS = 0.95, (8, 14)
RIDGELINE_SHORT_PROB, RIDGELINE_SHORT_FRACTION = 0.60, (0.4, 0.7)

# --- Inventory policy ---------------------------------------------------------
LAUNCH_DEMAND_WEEKS = range(1, 5)  # reorder points are sized from demand in weeks 1 to 4
REORDER_SAFETY_DAYS = 12  # reorder point covers (lead time + this many days) of launch demand
RIDGELINE_ORDER_COVER_DAYS = 7  # a cheap fastener is ordered little and often
RIDGELINE_SAFETY_DAYS = 4  # Ridgeline's parts are stocked thin, so a late delivery empties the shelf
ORDER_COVER_DAYS = 28  # orders go up to the reorder point plus this many days of demand
DEMAND_WINDOW_DAYS = 14  # "recent demand" is the trailing average over this many days
LINE_SIDE_TARGET_DAYS = 2  # kitters top line-side up to this many days of demand
SPOT_BUY_AFTER_BLOCKED_DAYS = 2  # working days a Ridgeline part blocks work before an emergency buy
SPOT_BUY_COVER_DAYS = 7  # an emergency buy covers this many days of demand
SUBSTITUTE_LOT_PREFIX = "SUB"
