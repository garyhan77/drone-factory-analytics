"""Two regression models on the simulated factory, each checked against something the generator fixes.

1. Logistic regression of first-pass failure at Motor & Prop on "got a substitute fastener lot", controlling
   for time in three-week blocks. Reported as an odds ratio, and as the average effect on the drones that got a
   substitute lot (percentage points), which is compared with the planted +19.5 points. The odds ratio itself
   has no single true value here, because the generator plants a constant difference in failure rates, not a
   constant ratio, so the percentage-point effect is the quantity to compare.

   Time is controlled in three-week blocks because a dummy for every week is unstable: weeks with no failures
   separate perfectly and the odds ratio blows up in some runs. The naive model without a time control is
   reported next to it.

2. Linear regression of the wait at Avionics on the number of drones already queued when a drone arrives, with
   standard errors that allow for the waits being correlated over time. The slope is the extra wait, in hours,
   for each drone ahead in the queue, and it is checked against the line's measured weekly throughput.

Run `python -m analysis.regression` for the many-seed check.
"""
from __future__ import annotations

import argparse
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy.special import expit

from analysis.causal import RESULTS_DIR, observed_frame
from analysis.sim import TRUE_EFFECT, simulate_analysis
from factory import config as cfg
from factory.generate import Generated

BLOCK_WEEKS = 3  # time control for the logistic model
SATURATED_WEEKS = range(14, 26)  # weeks the Avionics queue never clears (DOMAIN.md), used for the throughput check
HOURS_PER_WEEK = 7 * 24  # waits are wall-clock hours, nights and weekends included


# --- 1. Logistic regression ---------------------------------------------------------------------------------


def _design(df: pd.DataFrame, control: bool) -> np.ndarray:
    """Intercept, treated, and (optionally) a dummy for each three-week block except the first."""
    cols = [np.ones(len(df)), df["treated"].to_numpy(float)]
    if control:
        block = (df["week"].to_numpy() - 1) // BLOCK_WEEKS
        cols += [(block == b).astype(float) for b in sorted(set(block))[1:]]
    return np.column_stack(cols)


def _logit(X: np.ndarray, y: np.ndarray) -> np.ndarray | None:
    """Maximum-likelihood logistic coefficients, or None if the fit fails or separates."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            fit = sm.Logit(y, X).fit(disp=0, maxiter=100)
        except Exception:  # singular matrix, perfect separation
            return None
    b = fit.params
    # A time block with no failures separates perfectly and its own coefficient runs off to minus infinity;
    # that is harmless (it holds no information about the treatment). Only the treatment coefficient has to be sound.
    return b if np.all(np.isfinite(b)) and abs(b[1]) < 20 else None


def _effect_on_treated(X: np.ndarray, b: np.ndarray) -> float:
    """Average of P(fail | substitute lot) - P(fail | no substitute lot) over the drones that got one."""
    t = X[:, 1] == 1
    X1, X0 = X[t].copy(), X[t].copy()
    X1[:, 1], X0[:, 1] = 1.0, 0.0
    return float((expit(X1 @ b) - expit(X0 @ b)).mean())


@dataclass(frozen=True)
class LogitResult:
    odds_ratio: float
    or_lo: float
    or_hi: float
    effect: float  # percentage-point effect on treated drones, as a fraction
    effect_lo: float
    effect_hi: float


def logistic_model(df: pd.DataFrame, control: bool = True, boot: int = 200, seed: int = 0) -> LogitResult | None:
    """Odds ratio (Wald interval) and effect on the treated (bootstrap interval); None if the model cannot be fit."""
    X, y = _design(df, control), df["failed"].to_numpy(float)
    b = _logit(X, y)
    if b is None:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ci = sm.Logit(y, X).fit(disp=0, maxiter=100).conf_int()[1]
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(boot):
        i = rng.integers(0, len(df), len(df))
        bb = _logit(X[i], y[i])
        if bb is not None and X[i][:, 1].sum() > 0:
            draws.append(_effect_on_treated(X[i], bb))
    lo, hi = np.percentile(draws, [2.5, 97.5]) if len(draws) > 20 else (np.nan, np.nan)
    return LogitResult(float(np.exp(b[1])), float(np.exp(ci[0])), float(np.exp(ci[1])),
                       _effect_on_treated(X, b), float(lo), float(hi))


# --- 2. Avionics wait regression ----------------------------------------------------------------------------


def avionics_frame(gen: Generated) -> pd.DataFrame:
    """Drones that arrived at Avionics: arrival time, drones already waiting, and the wait (hours) if they started."""
    orders = gen.clean["work_orders"]
    arrive = orders[orders["station_code"] == "MTR"][["serial_number", "end_ts"]].rename(columns={"end_ts": "arrive"})
    start = orders[orders["station_code"] == "AVN"][["serial_number", "start_ts"]].rename(columns={"start_ts": "start"})
    df = arrive.dropna().merge(start, on="serial_number", how="left").sort_values("arrive").reset_index(drop=True)
    arrive_t = df["arrive"].to_numpy()
    start_t = np.sort(df["start"].dropna().to_numpy())  # a drone that has not started by the extract is still waiting
    arrived = np.searchsorted(np.sort(arrive_t), arrive_t, side="right")  # drones that have arrived by then, incl. itself
    started = np.searchsorted(start_t, arrive_t, side="right")  # drones that have started by then
    own = (df["start"].isna() | (df["start"] > df["arrive"])).to_numpy()  # itself, if it is still waiting
    df["queue"] = arrived - started - own.astype(int)
    df["wait_h"] = (df["start"] - df["arrive"]).dt.total_seconds() / 3600
    return df


def implied_hours_per_queued_drone(gen: Generated) -> float:
    """Wall-clock hours one queued drone adds, from the weekly number of Avionics jobs completed while it is saturated."""
    orders = gen.clean["work_orders"]
    done = orders[(orders["station_code"] == "AVN") & orders["end_ts"].notna()]
    week = (done["end_ts"] - pd.Timestamp(cfg.START)).dt.days // 7 + 1
    per_week = done.groupby(week).size().reindex(SATURATED_WEEKS).dropna()
    return HOURS_PER_WEEK / float(per_week.mean())


@dataclass(frozen=True)
class WaitResult:
    slope: float
    lo: float
    hi: float
    intercept: float
    r_squared: float
    n: int
    implied: float


def wait_model(gen: Generated, lags: int = 20) -> WaitResult:
    df = avionics_frame(gen).dropna(subset=["wait_h"])  # drones still waiting at the extract have no wait yet
    fit = smf.ols("wait_h ~ queue", data=df).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    lo, hi = fit.conf_int().loc["queue"]
    return WaitResult(float(fit.params["queue"]), float(lo), float(hi), float(fit.params["Intercept"]),
                      float(fit.rsquared), int(len(df)), implied_hours_per_queued_drone(gen))


# --- Many-seed check ----------------------------------------------------------------------------------------


def evaluate_seed(seed: int, boot: int = 100) -> tuple[list[dict], dict] | None:
    gen = simulate_analysis(seed)
    df = observed_frame(gen)
    if df["treated"].sum() < 5:
        return None
    logit_rows = []
    for label, control in (("naive (no time control)", False), ("time-blocks (3 weeks)", True)):
        r = logistic_model(df, control=control, boot=boot, seed=seed)
        if r is not None:
            logit_rows.append({"seed": seed, "model": label, **r.__dict__})
    w = wait_model(gen)
    return logit_rows, {"seed": seed, **w.__dict__}


def run_study(seeds: range, boot: int = 100) -> tuple[pd.DataFrame, pd.DataFrame, list[int]]:
    logit, wait, skipped = [], [], []
    for seed in seeds:
        out = evaluate_seed(seed, boot=boot)
        if out is None:
            skipped.append(seed)
            continue
        logit += out[0]
        wait.append(out[1])
    return pd.DataFrame(logit), pd.DataFrame(wait), skipped


def summarize_logit(logit: pd.DataFrame) -> pd.DataFrame:
    logit = logit.assign(
        error=logit["effect"] - TRUE_EFFECT,
        covers=(logit["effect_lo"] <= TRUE_EFFECT) & (TRUE_EFFECT <= logit["effect_hi"]),
    )
    return logit.groupby("model", sort=False).agg(
        mean_effect=("effect", "mean"), bias=("error", "mean"),
        rmse=("error", lambda e: float(np.sqrt((e ** 2).mean()))), coverage=("covers", "mean"),
        median_odds_ratio=("odds_ratio", "median"), fits=("seed", "nunique"),
    ).reset_index()


def summarize_wait(wait: pd.DataFrame) -> pd.Series:
    ratio = wait["slope"] / wait["implied"]
    return pd.Series({
        "mean_slope_h": wait["slope"].mean(), "mean_implied_h": wait["implied"].mean(),
        "median_slope_over_implied": ratio.median(), "share_within_15pct": float(((ratio - 1).abs() <= 0.15).mean()),
        "mean_r_squared": wait["r_squared"].mean(), "seeds": len(wait),
    })


def headline(seed: int = cfg.SEED) -> str:
    gen = simulate_analysis(seed)
    df = observed_frame(gen)
    naive, blocked = logistic_model(df, control=False, seed=seed), logistic_model(df, control=True, seed=seed)
    w = wait_model(gen)
    pp = lambda x: f"{100 * x:5.1f}"  # noqa: E731
    lines = [f"Seed {seed}: {int(df['treated'].sum())} of {len(df)} drones got a substitute lot. True effect {100 * TRUE_EFFECT:.1f} points.", ""]
    for label, r in (("naive", naive), ("time-blocks", blocked)):
        lines.append(f"  logistic, {label:<11}  odds ratio {r.odds_ratio:5.1f} ({r.or_lo:.1f}-{r.or_hi:.1f})   "
                     f"effect on treated {pp(r.effect)} points ({pp(r.effect_lo)}-{pp(r.effect_hi)})")
    lines += ["", f"  Avionics wait: {w.slope:.2f} h per queued drone ({w.lo:.2f}-{w.hi:.2f}), R2 {w.r_squared:.2f}, n={w.n}; "
                  f"throughput implies {w.implied:.2f}"]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Regression models, checked against the generator.")
    parser.add_argument("--seeds", type=int, default=100)
    parser.add_argument("--boot", type=int, default=100)
    args = parser.parse_args()
    logit, wait, skipped = run_study(range(args.seeds), boot=args.boot)
    RESULTS_DIR.mkdir(exist_ok=True)
    logit.to_csv(RESULTS_DIR / "regression_logit_by_seed.csv", index=False)
    wait.to_csv(RESULTS_DIR / "regression_wait_by_seed.csv", index=False)
    pd.set_option("display.float_format", lambda v: f"{v:.3f}", "display.width", 140)
    print(f"Seeds used: {args.seeds - len(skipped)} of {args.seeds} (skipped, no substitute lots: {skipped})\n")
    print(f"Logistic regression, effect of a substitute lot on first-pass failure (true {TRUE_EFFECT:.3f}):")
    summary = summarize_logit(logit)
    summary.to_csv(RESULTS_DIR / "regression_logit_summary.csv", index=False)
    print(summary.to_string(index=False))
    print("\nAvionics wait regression against the throughput check:")
    wsum = summarize_wait(wait)
    wsum.to_frame("value").T.to_csv(RESULTS_DIR / "regression_wait_summary.csv", index=False)
    print(wsum.to_string())
    print("\n" + headline())


if __name__ == "__main__":
    main()
