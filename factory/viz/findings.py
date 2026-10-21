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


def production_finding(summary: pd.DataFrame, output: pd.DataFrame, wip: pd.DataFrame, weeks: int = 8) -> list[str]:
    """Which station is the bottleneck, and what that does to output."""
    waits = summary.dropna(subset=["avg_wait_hours"]).sort_values("avg_wait_hours", ascending=False)
    if len(waits) < 3:
        return ["There is not enough station data to identify a bottleneck."]
    top, second, rest = waits.iloc[0], waits.iloc[1], waits.iloc[2:]
    first = (
        f"**{top['station_name']} is the bottleneck.** Drones wait {top['avg_wait_hours']:.0f} hours on average before "
        f"reaching it, against {second['avg_wait_hours']:.0f} hours before {second['station_name']} and "
        f"{rest['avg_wait_hours'].max():.0f} hours or less at the other stations."
    )
    recent = drop_partial_last_week(output).tail(weeks)
    started, finished = int(recent["units_started"].sum()), int(recent["units_completed"].sum())
    waiting = wip.loc[wip["stage"] == f"Waiting for {top['station_name']}", "drones"]
    second_sentence = (
        f"Over the last {len(recent)} full weeks the line started {started} drones and finished {finished}"
        + (f", and {int(waiting.iloc[0])} drones are now queued for {top['station_name']}." if len(waiting) else ".")
    )
    return [first, second_sentence]


# ---------------------------------------------------------------------------- Quality & Traceability

MIN_WEEKLY_INSPECTIONS = 10  # a week with fewer inspections is too small to call a dip
Z_THRESHOLD = 3.0  # a dip counts only if it is this many standard errors below the station's overall rate
LOT_MIN_DRONES = 10  # a lot is judged only once at least this many of its drones have been inspected
LOT_MIN_LIFT = 3.0  # ...and flagged when its failure rate is at least this many times its station's


def _day(d) -> str:
    return f"{d.day} {d:%B}"


def station_yield_summary(weekly: pd.DataFrame) -> pd.DataFrame:
    """Per station: overall yield and its most surprising weak week.

    A week is judged against how far a week of that size could wobble by chance (a z-score: the gap to the overall
    rate divided by sqrt(p(1-p)/n)). Ranking by raw gap would mostly surface small, noisy weeks.
    """
    rows = []
    for (code, name), grp in weekly.groupby(["station_code", "station_name"]):
        overall = grp["passes"].sum() / grp["inspections"].sum()
        big = grp[grp["inspections"] >= MIN_WEEKLY_INSPECTIONS].copy()
        if big.empty or not 0 < overall < 1:
            continue
        big["z"] = (big["fpy"].astype(float) - overall) / (overall * (1 - overall) / big["inspections"]) ** 0.5
        worst = big.loc[big["z"].idxmin()]
        rows.append({"station_code": code, "station_name": name, "overall": overall, "worst_week": worst["week_start"],
                     "worst_fpy": float(worst["fpy"]), "worst_n": int(worst["inspections"]), "z": float(worst["z"])})
    return pd.DataFrame(rows, columns=["station_code", "station_name", "overall", "worst_week", "worst_fpy", "worst_n", "z"])


def flagged_lots(lots: pd.DataFrame) -> pd.DataFrame:
    """Lots that stand out: enough drones inspected, and a failure rate well above their station's."""
    keep = lots[(lots["drones_inspected"] >= LOT_MIN_DRONES) & (lots["lift"] >= LOT_MIN_LIFT)]
    return keep.sort_values("lift", ascending=False)


def quality_finding(weekly: pd.DataFrame, lots: pd.DataFrame, recall: pd.DataFrame) -> list[str]:
    """Which station's yield dipped, which lots explain it, and where the affected drones are."""
    out = []
    summary = station_yield_summary(weekly)
    worst = summary.loc[summary["z"].idxmin()] if len(summary) else None
    if worst is None or worst["z"] > -Z_THRESHOLD:
        out.append("No station's weekly yield fell by more than normal week-to-week variation would explain.")
    else:
        out.append(f"**{worst['station_name']}'s first-pass yield dipped to {worst['worst_fpy']:.0%} in the week of "
                   f"{_day(worst['worst_week'])}**, against {worst['overall']:.0%} over the whole period.")
    flagged = flagged_lots(lots)
    if flagged.empty:
        out.append("No lot's failure rate stands out from its station's.")
    else:
        top = flagged.iloc[0]
        lo, hi = flagged["lift"].min(), flagged["lift"].max()
        spread = f"{lo:.0f} times" if round(lo) == round(hi) else f"{lo:.0f} to {hi:.0f} times"
        n = len(flagged)
        out.append(
            f"**{n} {'lot stands' if n == 1 else 'lots stand'} out.** Drones that received "
            f"{'it' if n == 1 else 'them'} failed first inspection {spread} as often as their station's average. "
            f"The worst is {top['lot_id']} ({top['supplier_name']}): {int(top['fails'])} of {int(top['drones_inspected'])} "
            f"drones failed ({top['fail_rate']:.0%} against {top['station_fail_rate']:.1%}).")
        if len(recall) and int(recall["drones"].iloc[0]):
            r = recall.iloc[0]
            d = int(r["drones"])
            out.append(f"{d} {'drone contains' if d == 1 else 'drones contain'} {'this lot' if n == 1 else 'one of these lots'}. "
                       f"Where {'it is' if d == 1 else 'they are'} now: {int(r['shipped'])} shipped, {int(r['packed'])} packed and waiting, "
                       f"{int(r['in_line'])} still in the line.")
    return out


# ---------------------------------------------------------------------------- Inventory & Suppliers

def _join(names: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def inventory_finding(risk: pd.DataFrame, perf: pd.DataFrame, gap: pd.DataFrame, urgent: int = 3) -> list[str]:
    """Which parts will run out first, which supplier is least reliable, and where stock is in the wrong place.

    `perf` should hold the regular suppliers only: an emergency distributor that is only used when a supplier fails is
    not a fair comparison.
    """
    out = []
    if len(risk):
        flagged = risk[risk["risk_status"].isin(["STOCKOUT", "AT RISK"])]
        worst = risk.sort_values("cushion_days", na_position="last").head(urgent)
        suppliers = list(dict.fromkeys(worst["supplier_name"]))
        origin = f", all from {suppliers[0]}" if len(suppliers) == 1 else f", from {_join(suppliers)}"
        out.append(
            f"**{len(flagged)} of {len(risk)} parts are at risk or out of stock**: their stock is expected to run out before "
            f"the next delivery arrives, even allowing for a bad delivery. The most urgent are {_join(list(worst['part_name']))}{origin}.")
    if len(perf) >= 2:
        ranked = perf.sort_values("otif_rate")
        low, others = ranked.iloc[0], ranked.iloc[1:]
        out.append(
            f"**{low['supplier_name']} is the least reliable supplier**: {low['otif_rate']:.0%} of its shipments arrived on "
            f"time and in full, against {others['otif_rate'].min():.0%} to {others['otif_rate'].max():.0%} for the other regular suppliers.")
    if len(gap):
        top = gap.sort_values("days_short_at_line", ascending=False).iloc[0]
        out.append(
            f"**Right part, wrong place.** {len(gap)} parts were short at the line on at least one weekday while the warehouse "
            f"held enough for a drone. The worst is {top['part_name']} at {top['station_name']}, short on {int(top['days_short_at_line'])} weekdays.")
    return out


# ---------------------------------------------------------------------------- Data Quality

SCORED_CATEGORIES = ("planted", "reconciliation", "guard", "sanity")
CATEGORY_NAMES = {"planted": "Planted error", "reconciliation": "Reconciliation", "guard": "Guard", "sanity": "Sanity",
                  "operational": "Operational warning"}


def data_quality_finding(results: pd.DataFrame, impact: pd.DataFrame) -> list[str]:
    """How well the checks did against the planted errors, and how much the cleaning touched."""
    out = []
    scored = results[results["category"].isin(SCORED_CATEGORIES)]
    planted = results[results["category"] == "planted"]
    if len(planted):
        out.append(
            f"**{int(planted['caught'].sum())} of {int(planted['planted_rows'].sum())} planted errors were caught**, with "
            f"{int(scored['missed'].sum())} missed and {int(scored['false_positives'].sum())} false positives across "
            f"{len(scored)} scored checks.")
    if len(impact):
        dropped = int((impact["raw_rows"] - impact["clean_rows"]).sum())
        kept = int(impact["changed"].sum())
        out.append(
            f"**{dropped + kept} rows were dropped, repaired or relabelled before any metric was computed**: {dropped} dropped "
            f"and {kept} kept with a fix, so the numbers on the other pages never see the raw errors.")
    return out


# ---------------------------------------------------------------------------- Overview

def status_line(status: pd.Series) -> str:
    """One sentence of context: how many drones started, over what period, and how many have not shipped yet.

    "Started" is what the data records: a drone released late in the period may not have reached its first station yet.
    """
    started, shipped = int(status["started"]), int(status["shipped"])
    launch, as_of = status["launch"], status["as_of"]
    return (f"{started} drones were started between {launch.day} {launch:%B} and {as_of.day} {as_of:%B %Y}: "
            f"{shipped} have shipped and {started - shipped} are still in the factory.")
