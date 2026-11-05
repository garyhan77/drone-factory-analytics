"""Results of the statistical analysis layer (analysis/), read from the CSVs it commits.

The Analysis page needs no database and none of the analysis dependencies (scipy, statsmodels): the heavy work is done
by `make analysis`, and the page only reads what it wrote. The functions here are pure (no Streamlit), so they are
tested directly.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

RESULTS_DIR = Path(__file__).resolve().parents[2] / "analysis" / "results"
TRUE_EFFECT = 0.195  # the planted lot effect at Motor & Prop (analysis/sim.py)
ESTIMATOR_NAMES = {"naive": "Naive", "adjusted": "Adjusted for week", "ipw": "Inverse-probability weighting"}
LANE_ARMS = {"A": 2, "B": 3, "C": 4}


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(RESULTS_DIR / f"{name}.csv")


def causal_rows(summary: pd.DataFrame, station: str = "MTR") -> pd.DataFrame:
    """One row per estimator at one station, in display order, with readable names and percentage-point columns."""
    rows = summary[summary["station"] == station].set_index("estimator").loc[list(ESTIMATOR_NAMES)].reset_index()
    return pd.DataFrame({
        "Estimator": rows["estimator"].map(ESTIMATOR_NAMES),
        "Mean estimate (points)": (100 * rows["mean_estimate"]).round(1),
        "Bias (points)": (100 * rows["bias"]).round(1),
        "95% interval covers the truth": (100 * rows["coverage"]).round(0).astype(int).astype(str) + "%",
    })


def lane_gains(results: pd.DataFrame) -> pd.DataFrame:
    """Extra drones shipped by each added lane, with the simultaneous 95% interval."""
    shipped = results[results["metric"] == "shipped"].set_index("comparison")
    labels = {"B vs A": "Third lane (3 vs 2)", "C vs B": "Fourth lane (4 vs 3)"}
    out = shipped.loc[list(labels)].reset_index()
    return pd.DataFrame({"label": out["comparison"].map(labels), "gain": out["difference"],
                         "lo": out["adj_ci_lo"], "hi": out["adj_ci_hi"]})


def lane_outcomes(results: pd.DataFrame, secondary: pd.DataFrame) -> pd.DataFrame:
    """Mean outcomes under 2, 3 and 4 lanes."""
    shipped = results[results["metric"] == "shipped"]
    base = shipped[shipped["comparison"] == "B vs A"].iloc[0]
    top = shipped[shipped["comparison"] == "C vs B"].iloc[0]
    queue = secondary[secondary["metric"] == "avionics_queue_at_extract"]
    wait = secondary[secondary["metric"] == "avionics_wait_h"]
    q = [queue[queue["comparison"] == "B vs A"].iloc[0]["mean_base"], queue[queue["comparison"] == "B vs A"].iloc[0]["mean_arm"],
         queue[queue["comparison"] == "C vs B"].iloc[0]["mean_arm"]]
    w = [wait[wait["comparison"] == "B vs A"].iloc[0]["mean_base"], wait[wait["comparison"] == "B vs A"].iloc[0]["mean_arm"],
         wait[wait["comparison"] == "C vs B"].iloc[0]["mean_arm"]]
    return pd.DataFrame({
        "Avionics lanes": list(LANE_ARMS.values()),
        "Drones shipped": [base["mean_base"], base["mean_arm"], top["mean_arm"]],
        "Queued at Avionics at the end": q,
        "Average Avionics wait (h)": w,
    }).round(1)


def analysis_finding(causal: pd.DataFrame, results: pd.DataFrame, guardrail: pd.DataFrame, min_worthwhile: float = 25.0) -> list[str]:
    """The answer-first sentences, written from the result tables."""
    mtr = causal[causal["station"] == "MTR"].set_index("estimator")
    naive, adj = mtr.loc["naive", "mean_estimate"], mtr.loc["ipw", "mean_estimate"]
    first = (f"**A substitute fastener lot raises first-pass failure by about {100 * adj:.1f} points, and a naive comparison "
             f"overstates it at {100 * naive:.1f}.** The same inspectors were swamped in the weeks the lots arrived; "
             f"adjusting for the week removes that. Across 91 simulated datasets, the adjusted estimates land close to the planted "
             f"{100 * TRUE_EFFECT:.1f} points and the naive one does not.")
    gains = lane_gains(results)
    third, fourth = gains.iloc[0], gains.iloc[1]
    clears = lambda g: g["lo"] >= min_worthwhile  # noqa: E731
    verdict = {(True, False): "The third lane clears the {b:.0f}-drone bar and the fourth does not",
               (True, True): "Both lanes clear the {b:.0f}-drone bar", (False, False): "Neither lane clears the {b:.0f}-drone bar",
               (False, True): "The fourth lane clears the {b:.0f}-drone bar and the third does not"}[(clears(third), clears(fourth))]
    second = (f"**Adding a third Avionics lane ships about {third['gain']:.0f} more drones over 26 weeks; a fourth adds only "
              f"{fourth['gain']:.0f}.** " + verdict.format(b=min_worthwhile) + " (an assumed bar, not a cost model).")
    worst = guardrail["difference"].max()
    third_s = f"Final Test wait rises at most {worst:.1f} hours, against a 24-hour limit."
    return [first, second + " " + third_s]
