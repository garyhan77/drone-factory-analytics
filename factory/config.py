"""Every tunable number for the simulation, taken from DOMAIN.md.

Weeks are 1-based: week 1 starts on START. Change numbers here, not in the simulation code.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

SEED = 42

# --- Calendar ---------------------------------------------------------------
START = date(2026, 1, 5)  # a Monday
WEEKS = 26
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
    fail_rate: float  # baseline first-pass fail rate


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

# Weekly releases: 18 in week 1, 30 by week 12, 34 by week 26.
RELEASES_WEEK_1, RELEASES_MID, RELEASES_END = 18, 30, 34
RELEASES_MID_WEEK = 12

# --- Defects ----------------------------------------------------------------
DEFECT_NAMES = {
    "AFL": ["DELAMINATION", "RESIN-VOID", "FIBRE-WRINKLE"],
    "WNG": ["SERVO-BIND", "SKIN-GAP", "SPAR-MISALIGN"],
    "MTR": ["LOOSE-FASTENER", "PROP-IMBALANCE", "MOTOR-NOISE"],
    "AVN": ["SENSOR-CAL-FAIL", "CONNECTOR-SEAT", "FW-FLASH-FAIL"],
    "FNT": ["GPS-LOCK-TIMEOUT", "CONTROL-SURFACE-RANGE", "PAYLOAD-LATCH"],
}

# The defect spike: drones passing this station in these weeks may carry the substitute lot.
SPIKE_STATION = "MTR"
SPIKE_WEEKS = range(12, 16)  # weeks 12 to 15
SUBSTITUTE_LOT_SHARE = 0.70  # share of drones in the window that get the substitute lot
SUBSTITUTE_FAIL_RATE = 0.22
SUBSTITUTE_LOOSE_FASTENER_SHARE = 0.75  # of those failures
SPIKE_DEFECT = "MTR-LOOSE-FASTENER"
