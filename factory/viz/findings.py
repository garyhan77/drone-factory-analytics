"""The answer-first sentences at the top of each page, written from the live numbers.

Nothing here is hard-coded: every figure comes from the DataFrames it is given, so the sentence stays true if the data
changes. These are pure functions (no Streamlit, no database), so they are tested directly.
"""
from __future__ import annotations

import pandas as pd


def drop_partial_last_week(df: pd.DataFrame, week_col: str = "week_start") -> pd.DataFrame:
    """The data is extracted part-way through the last week, so that week is incomplete and would look like a crash."""
    if df.empty:
        return df
    return df[df[week_col] < df[week_col].max()]


# ---------------------------------------------------------------------------- Quality & Traceability

LOT_MIN_DRONES = 10  # a lot is judged only once at least this many of its drones have been inspected
LOT_MIN_FAIL_RATE = 0.20  # ...and flagged when at least this share of its drones failed inspection


def flagged_lots(lots: pd.DataFrame) -> pd.DataFrame:
    """Lots that stand out: enough drones inspected, and at least one in five of them failed."""
    keep = lots[(lots["drones_inspected"] >= LOT_MIN_DRONES) & (lots["fail_rate"] >= LOT_MIN_FAIL_RATE)]
    return keep.sort_values("fail_rate", ascending=False)


def quality_finding(lots: pd.DataFrame, recall: pd.DataFrame) -> list[str]:
    """Which lots failed far more often than the rest, and where the affected drones are."""
    out = []
    judged = lots[lots["drones_inspected"] >= LOT_MIN_DRONES]
    flagged = flagged_lots(lots)
    if flagged.empty:
        out.append(f"No lot had {LOT_MIN_FAIL_RATE:.0%} or more of its drones fail inspection.")
        return out
    top = flagged.iloc[0]
    n = len(flagged)
    lo, hi = flagged["fail_rate"].min(), flagged["fail_rate"].max()
    spread = f"{lo:.0%}" if round(lo * 100) == round(hi * 100) else f"{lo:.0%} to {hi:.0%}"
    typical = judged["fail_rate"].median()
    out.append(
        f"**{n} {'lot stands' if n == 1 else 'lots stand'} out.** {spread} of the drones that received "
        f"{'it' if n == 1 else 'them'} failed inspection, against {typical:.0%} for a typical lot. "
        f"The worst is {top['lot_id']} ({top['supplier_name']}): {int(top['fails'])} of {int(top['drones_inspected'])} drones failed.")
    if len(recall) and int(recall["drones"].iloc[0]):
        r = recall.iloc[0]
        d = int(r["drones"])
        out.append(f"{d} {'drone contains' if d == 1 else 'drones contain'} {'this lot' if n == 1 else 'one of these lots'}. "
                   f"Where {'it is' if d == 1 else 'they are'} now: {int(r['shipped'])} shipped, {int(r['packed'])} packed and waiting, "
                   f"{int(r['in_line'])} still in the line.")
    return out


# ---------------------------------------------------------------------------- Inventory & Suppliers

def inventory_finding(ridgeline: pd.DataFrame, emergency_lots: int = 0) -> list[str]:
    """What the unreliable supplier did, and what the line did about it.

    `ridgeline` holds that supplier's regular (not emergency) deliveries that have arrived.
    """
    out = []
    late = ridgeline[ridgeline["days_late"] > 0]
    if late.empty:
        return out
    worst = late.sort_values("days_late", ascending=False).iloc[0]
    short = " and short" if worst["short"] else ""
    out.append(f"**{worst['supplier_name']}'s {worst['part_name'].lower()} delivery due {worst['expected_date'].day} "
               f"{worst['expected_date']:%B} arrived {int(worst['days_late'])} days late{short}.** It was late on {len(late)} "
               f"of its {len(ridgeline)} deliveries.")
    if emergency_lots:
        out.append(f"When the stock ran out, the line bought {emergency_lots} emergency substitute "
                   f"{'lot' if emergency_lots == 1 else 'lots'} of {worst['part_name'].lower()} from the spot-buy distributor.")
    return out
