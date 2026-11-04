"""Causal effect of a substitute fastener lot on first-pass failure, checked against the planted truth.

Question: does a drone whose Motor & Prop fasteners came from an emergency (spot-buy) lot fail first
inspection more often because of that lot? The generator plants the answer (+19.5 points) and also plants a
confounder (inspectors are swamped in weeks 11-15, the same weeks substitute lots reach the line), so a naive
comparison overstates it.

Three estimators of the risk difference, each with a bootstrap interval:
  naive      difference in failure rates between drones with and without a substitute lot
  adjusted   the same, conditioning on the week the job started (OLS with a dummy for every week)
  ipw        inverse-probability weighting, with the chance of a substitute lot estimated within each week

They use only what an analyst could see: work orders, first inspections and lot traceability.
Run `python -m analysis.causal` for the many-seed check against the truth.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.sim import TRUE_EFFECT, simulate_analysis
from factory import config as cfg
from factory.dimensions import part_ids
from factory.generate import Generated
from factory.line import datetime_to_work_minute

RESULTS_DIR = Path(__file__).parent / "results"
ESTIMATORS = ("naive", "adjusted", "ipw")
PLACEBO_STATIONS = ("AFL", "WNG")  # upstream of Motor & Prop: a later substitute lot cannot affect them


# --- The data an analyst sees -----------------------------------------------------------------------------


def substitute_drones(gen: Generated) -> set[str]:
    """Drones that got a spot-buy lot for any Motor & Prop spike fastener (read from lot traceability)."""
    spike = {
        pid for pid, part in zip(part_ids(), cfg.PARTS)
        if part.station_code == cfg.SPIKE_STATION and part.name in cfg.SPIKE_FASTENERS
    }
    lots = gen.clean["drone_part_lots"]
    hit = lots[lots["part_id"].isin(spike) & lots["lot_id"].str.startswith(cfg.SUBSTITUTE_LOT_PREFIX)]
    return set(hit["serial_number"])


def observed_frame(gen: Generated, station: str = cfg.SPIKE_STATION) -> pd.DataFrame:
    """One row per drone with a first inspection at `station`: week the job started, treated, failed.

    `treated` is always about Motor & Prop's fasteners, whichever station's outcome is looked at; for the
    stations upstream of it that makes the true effect zero (the placebo).
    """
    orders = gen.clean["work_orders"]
    orders = orders[orders["station_code"] == station][["serial_number", "start_ts"]]
    first = gen.clean["inspections"]
    first = first[(first["station_code"] == station) & (first["attempt"] == 1)][["serial_number", "result"]]
    df = orders.merge(first, on="serial_number")
    df["week"] = [datetime_to_work_minute(ts) // cfg.WEEK_MIN + 1 for ts in df["start_ts"]]
    df["treated"] = df["serial_number"].isin(substitute_drones(gen))
    df["failed"] = df["result"] == "FAIL"
    return df[["serial_number", "week", "treated", "failed"]].reset_index(drop=True)


# --- Estimators -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Strata:
    """Counts per week: drones with / without a substitute lot, and how many of each failed."""
    n1: np.ndarray
    n0: np.ndarray
    f1: np.ndarray
    f0: np.ndarray


def strata(week: np.ndarray, treated: np.ndarray, failed: np.ndarray) -> Strata:
    size = cfg.WEEKS + 1
    t, f = treated.astype(bool), failed.astype(float)
    return Strata(
        n1=np.bincount(week[t], minlength=size).astype(float),
        n0=np.bincount(week[~t], minlength=size).astype(float),
        f1=np.bincount(week[t], weights=f[t], minlength=size),
        f0=np.bincount(week[~t], weights=f[~t], minlength=size),
    )


def naive(s: Strata) -> float:
    return s.f1.sum() / s.n1.sum() - s.f0.sum() / s.n0.sum()


def adjusted(s: Strata) -> float:
    """OLS with a dummy for every week: a weighted average of the within-week differences, weight n1*n0/(n1+n0)."""
    both = (s.n1 > 0) & (s.n0 > 0)
    n1, n0 = s.n1[both], s.n0[both]
    diff = s.f1[both] / n1 - s.f0[both] / n0
    weight = n1 * n0 / (n1 + n0)
    return float((weight * diff).sum() / weight.sum())


def ipw(s: Strata) -> float:
    """Hajek inverse-probability weighting, the chance of a substitute lot estimated within each week."""
    both = (s.n1 > 0) & (s.n0 > 0)  # weeks with only one group have no overlap and are dropped
    n1, n0 = s.n1[both], s.n0[both]
    e = n1 / (n1 + n0)
    treated_mean = (s.f1[both] / e).sum() / (n1 / e).sum()
    control_mean = (s.f0[both] / (1 - e)).sum() / (n0 / (1 - e)).sum()
    return float(treated_mean - control_mean)


FUNCS = {"naive": naive, "adjusted": adjusted, "ipw": ipw}


def estimate(df: pd.DataFrame, boot: int = 300, seed: int = 0) -> pd.DataFrame:
    """Point estimate and 95% percentile-bootstrap interval for each estimator (rows are resampled)."""
    week, treated, failed = df["week"].to_numpy(), df["treated"].to_numpy(), df["failed"].to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        point = {name: f(strata(week, treated, failed)) for name, f in FUNCS.items()}
    rng = np.random.default_rng(seed)
    draws = {name: [] for name in FUNCS}
    for _ in range(boot):
        i = rng.integers(0, len(df), len(df))
        s = strata(week[i], treated[i], failed[i])
        if s.n1.sum() == 0 or s.n0.sum() == 0:
            continue
        for name, f in FUNCS.items():
            with np.errstate(divide="ignore", invalid="ignore"):
                value = f(s)
            if np.isfinite(value):  # a resample with no week holding both groups has no estimate
                draws[name].append(value)
    rows = []
    for name in ESTIMATORS:
        lo, hi = np.percentile(draws[name], [2.5, 97.5]) if draws[name] else (np.nan, np.nan)
        rows.append({"estimator": name, "estimate": point[name], "lo": lo, "hi": hi})
    return pd.DataFrame(rows)


# --- Checking the estimators against the truth ------------------------------------------------------------


def evaluate_seed(seed: int, boot: int = 200) -> pd.DataFrame | None:
    """Estimates for one simulated dataset: the real question at Motor & Prop plus the placebo stations.

    Returns None when the seed produced no substitute lots (about one seed in ten), so there is nothing to compare.
    """
    gen = simulate_analysis(seed)
    rows = []
    for station in (cfg.SPIKE_STATION, *PLACEBO_STATIONS):
        df = observed_frame(gen, station)
        if df["treated"].sum() < 5:
            return None
        out = estimate(df, boot=boot, seed=seed)
        out["station"] = station
        out["truth"] = TRUE_EFFECT if station == cfg.SPIKE_STATION else 0.0
        out["seed"] = seed
        out["n_treated"] = int(df["treated"].sum())
        rows.append(out)
    return pd.concat(rows, ignore_index=True)


def run_study(seeds: range, boot: int = 200) -> tuple[pd.DataFrame, list[int]]:
    parts, skipped = [], []
    for seed in seeds:
        result = evaluate_seed(seed, boot=boot)
        (skipped.append(seed) if result is None else parts.append(result))
    return pd.concat(parts, ignore_index=True), skipped


def summarize(study: pd.DataFrame) -> pd.DataFrame:
    """Per station and estimator: average estimate, bias, RMSE, and how often the 95% interval holds the truth."""
    study = study.assign(
        error=study["estimate"] - study["truth"],
        covers=(study["lo"] <= study["truth"]) & (study["truth"] <= study["hi"]),
    )
    out = study.groupby(["station", "estimator"], sort=False).agg(
        truth=("truth", "first"), mean_estimate=("estimate", "mean"), bias=("error", "mean"),
        rmse=("error", lambda e: float(np.sqrt((e ** 2).mean()))), coverage=("covers", "mean"), seeds=("seed", "nunique"),
    ).reset_index()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the causal estimators against the planted truth.")
    parser.add_argument("--seeds", type=int, default=100)
    parser.add_argument("--boot", type=int, default=200)
    args = parser.parse_args()
    study, skipped = run_study(range(args.seeds), boot=args.boot)
    summary = summarize(study)
    RESULTS_DIR.mkdir(exist_ok=True)
    study.to_csv(RESULTS_DIR / "causal_by_seed.csv", index=False)
    summary.to_csv(RESULTS_DIR / "causal_summary.csv", index=False)
    pd.set_option("display.float_format", lambda v: f"{v:.3f}", "display.width", 120)
    print(f"True effect at Motor & Prop: {TRUE_EFFECT:.3f}. Seeds used: {args.seeds - len(skipped)} of {args.seeds} "
          f"(skipped, no substitute lots: {skipped})\n")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
