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
