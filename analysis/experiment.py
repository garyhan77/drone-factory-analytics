"""Experiment design: how many drones does each extra Avionics lane ship, and where do the returns run out?

Avionics is the bottleneck: about 31 drones a week arrive and it can start about 26, so the queue grows every
week. The question for a planner is whether adding a lane is worth it, and whether a fourth one still is.

Design, fixed before the experiment runs
  Unit            one simulated 26-week run (a seed), a separate "world" with its own random events
  Arms            A: 2 Avionics lanes (today)   B: 3 lanes   C: 4 lanes; every seed is run under all three arms
  Primary outcome drones shipped by the extract (a count; unlike waiting time it is not cut off by the extract)
  Secondary       drones still queued at Avionics at the extract; average Avionics wait of drones that started
  Guardrail       Final Test wait, because a faster Avionics could just move the queue downstream; a rise of more
                  than 24 hours on average (against A) counts as a breach
  Comparisons     B vs A (the third lane), C vs B (what the fourth lane adds), C vs A; Holm-adjusted p-values and
                  simultaneous 95% intervals (Bonferroni, three comparisons)
  Decision rule   a lane is worth building only if the lower end of its adjusted interval is at least
                  MIN_WORTHWHILE drones shipped
  Diminishing     the curvature A - 2B + C per seed, which is the gain from lane 4 minus the gain from lane 3, so
  returns         a negative value means diminishing returns; tested with a paired t-test
  Sample size     from a power analysis on pilot seeds (PILOT_SEEDS), never the experiment seeds, for 80% power
                  on the third lane and on the curvature, but never fewer than MIN_SEEDS: the noisier secondary
                  outcomes and the guardrail need more runs, and a permutation test needs more than a handful
  Analysis        paired t-tests on per-seed differences, cross-checked with sign-flip permutation tests; a Welch
                  test on randomly assigned arms for the unpaired design
  Sanity check    A/A test: split runs of the same arm at random and confirm a 5% false-positive rate

History: a first version compared only A and B on seeds 1000-1019 (+53 drones). The fourth lane was added after
seeing that, so this version uses fresh seeds (EXPERIMENT_SEEDS_START) and so also replicates the A vs B result.

Run `python -m analysis.experiment pilot`, then `python -m analysis.experiment run`.
"""
from __future__ import annotations

import argparse
import dataclasses
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.power import TTestIndPower, TTestPower

from analysis.causal import RESULTS_DIR
from analysis.sim import simulate_analysis
from factory import config as cfg
from factory.generate import Generated

LANES = {"A": 2, "B": 3, "C": 4}
COMPARISONS = (("B", "A"), ("C", "B"), ("C", "A"))  # (arm, the arm it is compared with)
PRIMARY = "shipped"
GUARDRAIL = "final_test_wait_h"
GUARDRAIL_LIMIT_H = 24.0
MIN_WORTHWHILE = 25  # drones shipped over 26 weeks (about 4%) an added lane must ship to pay for itself
ALPHA, POWER = 0.05, 0.80
MIN_SEEDS = 20
PILOT_SEEDS = range(0, 30)
EXPERIMENT_SEEDS_START = 2000  # never overlaps the pilot or the first two-arm version (1000-1019)
AA_SEEDS_START = 5000
STATION_ORDER = [s.code for s in cfg.STATIONS]


# --- Running an arm -----------------------------------------------------------------------------------------


def avionics_lanes(lanes: int) -> list[cfg.Station]:
    return [dataclasses.replace(s, lanes=lanes) if s.code == "AVN" else s for s in cfg.STATIONS]


def _wait_hours(gen: Generated, station: str) -> float:
    """Average hours between finishing the previous station and starting this one, for drones that started."""
    orders = gen.clean["work_orders"]
    previous = orders[orders["station_code"] == STATION_ORDER[STATION_ORDER.index(station) - 1]][["serial_number", "end_ts"]]
    here = orders[orders["station_code"] == station][["serial_number", "start_ts"]]
    both = here.merge(previous, on="serial_number")
    return float((both["start_ts"] - both["end_ts"]).dt.total_seconds().mean() / 3600)


def outcomes(gen: Generated) -> dict[str, float]:
    orders = gen.clean["work_orders"]
    arrived = orders[(orders["station_code"] == "MTR") & orders["end_ts"].notna()]["serial_number"].nunique()
    started = orders[orders["station_code"] == "AVN"]["serial_number"].nunique()
    return {
        PRIMARY: float(gen.clean["finished_goods"]["shipped_ts"].notna().sum()),
        "avionics_queue_at_extract": float(arrived - started),
        "avionics_wait_h": _wait_hours(gen, "AVN"),
        GUARDRAIL: _wait_hours(gen, "FNT"),
    }


def run_arm(seed: int, arm: str) -> dict[str, float]:
    return {"seed": seed, "arm": arm, **outcomes(simulate_analysis(seed, STATIONS=avionics_lanes(LANES[arm])))}


def collect(seeds: range) -> pd.DataFrame:
    """Every seed run under every arm (a paired design)."""
    return pd.DataFrame([run_arm(seed, arm) for seed in seeds for arm in LANES])


def wide(runs: pd.DataFrame, metric: str) -> pd.DataFrame:
    return runs.pivot(index="seed", columns="arm", values=metric)


# --- Power analysis -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Pilot:
    sd_a: float
    sd_b: float
    sd_diff: float
    correlation: float
    mean_diff: float


def pilot_summary(runs: pd.DataFrame, metric: str = PRIMARY, arm: str = "B", base: str = "A") -> Pilot:
    w = wide(runs, metric)
    return Pilot(float(w[base].std()), float(w[arm].std()), float((w[arm] - w[base]).std()),
                 float(w[base].corr(w[arm])), float((w[arm] - w[base]).mean()))


def curvature(runs: pd.DataFrame, metric: str = PRIMARY) -> np.ndarray:
    """Per seed, A - 2B + C = (gain from lane 4) - (gain from lane 3); negative means diminishing returns."""
    w = wide(runs, metric)
    return (w["A"] - 2 * w["B"] + w["C"]).to_numpy()


def seeds_needed(sd: float, effect: float, paired: bool, alpha: float = ALPHA, power: float = POWER) -> int:
    """Seeds (paired) or seeds per arm (unpaired) for the given power to detect `effect`, standard deviation `sd`."""
    solver = TTestPower() if paired else TTestIndPower()
    n = solver.solve_power(effect_size=effect / sd, alpha=alpha, power=power, alternative="two-sided")
    return int(np.ceil(n))


def minimum_detectable_effect(sd: float, n: int, paired: bool, alpha: float = ALPHA, power: float = POWER) -> float:
    """The smallest effect detectable with `n` seeds (paired) or `n` seeds per arm (unpaired)."""
    if paired:
        return float(TTestPower().solve_power(nobs=n, alpha=alpha, power=power, alternative="two-sided") * sd)
    return float(TTestIndPower().solve_power(nobs1=n, alpha=alpha, power=power, alternative="two-sided") * sd)


def sample_size_plan(pilot: Pilot) -> pd.DataFrame:
    """Seeds needed for a range of smallest effects of interest, paired and unpaired."""
    sd_unpaired = float(np.sqrt((pilot.sd_a ** 2 + pilot.sd_b ** 2) / 2))
    rows = []
    for effect in (5, 10, 15, MIN_WORTHWHILE, 50):
        rows.append({"smallest_effect": effect, "paired_seeds": seeds_needed(pilot.sd_diff, effect, paired=True),
                     "unpaired_seeds_per_arm": seeds_needed(sd_unpaired, effect, paired=False)})
    return pd.DataFrame(rows)


def required_seeds(pilot_runs: pd.DataFrame) -> int:
    """Seeds for 80% power on the third lane (B vs A) and on the diminishing-returns test, at MIN_WORTHWHILE."""
    sd_third = pilot_summary(pilot_runs).sd_diff
    sd_curve = float(curvature(pilot_runs).std(ddof=1))
    return max(seeds_needed(sd_third, MIN_WORTHWHILE, paired=True), seeds_needed(sd_curve, MIN_WORTHWHILE, paired=True))


# --- Analysis -----------------------------------------------------------------------------------------------


def sign_flip_p(diffs: np.ndarray, draws: int = 20_000, seed: int = 0) -> float:
    """Permutation test for paired data: under no effect the sign of each seed's difference is arbitrary."""
    rng = np.random.default_rng(seed)
    observed = abs(diffs.mean())
    flips = rng.choice([-1.0, 1.0], size=(draws, len(diffs)))
    return float(((np.abs((flips * diffs).mean(axis=1)) >= observed).sum() + 1) / (draws + 1))


def _summary(d: np.ndarray, level: float = 0.95) -> dict[str, float]:
    lo, hi = stats.t.interval(level, len(d) - 1, loc=d.mean(), scale=stats.sem(d))
    return {"difference": d.mean(), "ci_lo": lo, "ci_hi": hi, "p_t": stats.ttest_1samp(d, 0.0).pvalue,
            "p_permutation": sign_flip_p(d), "seeds": len(d)}


def paired_test(runs: pd.DataFrame, metric: str, arm: str = "B", base: str = "A") -> dict[str, float]:
    """One planned comparison, arm minus base, as a paired test on the per-seed differences."""
    w = wide(runs, metric)
    return {"metric": metric, "comparison": f"{arm} vs {base}", "mean_base": w[base].mean(), "mean_arm": w[arm].mean(),
            **_summary((w[arm] - w[base]).to_numpy())}


def pairwise_table(runs: pd.DataFrame, metric: str = PRIMARY) -> pd.DataFrame:
    """The three planned comparisons with Holm-adjusted p-values and simultaneous (Bonferroni) 95% intervals."""
    w = wide(runs, metric)
    rows = []
    for arm, base in COMPARISONS:
        d = (w[arm] - w[base]).to_numpy()
        row = paired_test(runs, metric, arm, base)
        lo, hi = stats.t.interval(1 - ALPHA / len(COMPARISONS), len(d) - 1, loc=d.mean(), scale=stats.sem(d))
        rows.append({**row, "adj_ci_lo": lo, "adj_ci_hi": hi})
    table = pd.DataFrame(rows)
    table["p_holm"] = multipletests(table["p_t"], method="holm")[1]
    return table


def curvature_test(runs: pd.DataFrame, metric: str = PRIMARY) -> dict[str, float]:
    return {"metric": metric, **_summary(curvature(runs, metric))}


def unpaired_test(runs: pd.DataFrame, metric: str, seed: int = 0) -> dict[str, float]:
    """The classic A/B design: each seed is randomly given ONE arm (A or B), and only that arm's result is used."""
    w = wide(runs, metric)
    rng = np.random.default_rng(seed)
    assigned_b = rng.permutation(len(w)) < len(w) // 2
    a, b = w["A"].to_numpy()[~assigned_b], w["B"].to_numpy()[assigned_b]
    t = stats.ttest_ind(b, a, equal_var=False)
    return {"metric": metric, "difference": b.mean() - a.mean(), "p_welch": t.pvalue, "n_A": len(a), "n_B": len(b)}


def rejection_rate_under_null(values: np.ndarray, splits: int = 2000, seed: int = 0) -> float:
    """Share of random half-and-half splits of `values` that a Welch test calls significant. Should be about ALPHA."""
    rng = np.random.default_rng(seed)
    half = len(values) // 2
    hits = 0
    for _ in range(splits):
        order = rng.permutation(len(values))
        hits += stats.ttest_ind(values[order[:half]], values[order[half:2 * half]], equal_var=False).pvalue < ALPHA
    return hits / splits


def aa_false_positive_rate(metric: str = PRIMARY, runs: int = 60, splits: int = 2000, seed: int = 0) -> float:
    """A/A test: runs of the SAME arm, split at random into two groups, tested as if they were arms."""
    values = np.array([run_arm(AA_SEEDS_START + i, "A")[metric] for i in range(runs)])
    return rejection_rate_under_null(values, splits=splits, seed=seed)


def verdict(pairs: pd.DataFrame, curve: dict[str, float], guardrails: pd.DataFrame) -> str:
    parts = []
    for _, r in pairs.iterrows():
        clears = "clears" if r["adj_ci_lo"] >= MIN_WORTHWHILE else "does not clear"
        parts.append(f"{r['comparison']}: {r['difference']:+.1f} drones (adjusted CI {r['adj_ci_lo']:+.1f} to "
                     f"{r['adj_ci_hi']:+.1f}), {clears} the {MIN_WORTHWHILE}-drone bar")
    breach = (guardrails["difference"] > GUARDRAIL_LIMIT_H).any()
    ft = ", ".join(f"{r['comparison']} {r['difference']:+.1f} h" for _, r in guardrails.iterrows())
    return ("\n".join(parts) + f"\nDiminishing returns: curvature {curve['difference']:+.1f} drones "
            f"(95% CI {curve['ci_lo']:+.1f} to {curve['ci_hi']:+.1f}, p = {curve['p_t']:.3g}).\n"
            f"Final Test wait against A: {ft} ({'GUARDRAIL BREACH' if breach else 'within the 24 h guardrail'}).")


# --- Command line -------------------------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Avionics capacity experiment.")
    parser.add_argument("stage", choices=["pilot", "run"])
    parser.add_argument("--seeds", type=int, default=None, help="experiment seeds (default: from the power analysis)")
    args = parser.parse_args()
    RESULTS_DIR.mkdir(exist_ok=True)
    pd.set_option("display.float_format", lambda v: f"{v:.3f}", "display.width", 160)
    if args.stage == "pilot":
        runs = collect(PILOT_SEEDS)
        runs.to_csv(RESULTS_DIR / "experiment_pilot_runs.csv", index=False)
        third, fourth = pilot_summary(runs), pilot_summary(runs, arm="C", base="B")
        plan = sample_size_plan(third)
        plan.to_csv(RESULTS_DIR / "experiment_sample_size.csv", index=False)
        sd_curve = float(curvature(runs).std(ddof=1))
        print(f"Pilot on {len(PILOT_SEEDS)} seeds, outcome '{PRIMARY}':")
        print(f"  third lane (B vs A): SD of paired difference {third.sd_diff:.1f}, correlation {third.correlation:.2f}, "
              f"observed {third.mean_diff:+.1f}")
        print(f"  fourth lane (C vs B): SD of paired difference {fourth.sd_diff:.1f}, observed {fourth.mean_diff:+.1f}")
        print(f"  curvature A-2B+C: mean {curvature(runs).mean():+.1f}, SD {sd_curve:.1f}\n")
        print(f"Seeds needed for {POWER:.0%} power at {ALPHA:.0%}, third lane:\n{plan.to_string(index=False)}")
        print(f"\nSeeds needed to detect a curvature of {MIN_WORTHWHILE}: {seeds_needed(sd_curve, MIN_WORTHWHILE, True)}")
        return
    pilot_runs = pd.read_csv(RESULTS_DIR / "experiment_pilot_runs.csv")
    needed = required_seeds(pilot_runs)
    n = args.seeds or max(needed, MIN_SEEDS)
    print(f"Power analysis asks for {needed} seeds; using {n} (floor {MIN_SEEDS}).")
    runs = collect(range(EXPERIMENT_SEEDS_START, EXPERIMENT_SEEDS_START + n))
    runs.to_csv(RESULTS_DIR / "experiment_runs.csv", index=False)
    pairs = pairwise_table(runs)
    curve = curvature_test(runs)
    secondary = pd.DataFrame([paired_test(runs, m, arm, base) for m in ("avionics_queue_at_extract", "avionics_wait_h")
                              for arm, base in COMPARISONS])
    guardrails = pd.DataFrame([paired_test(runs, GUARDRAIL, arm, "A") for arm in ("B", "C")])
    pairs.to_csv(RESULTS_DIR / "experiment_results.csv", index=False)
    secondary.to_csv(RESULTS_DIR / "experiment_secondary.csv", index=False)
    guardrails.to_csv(RESULTS_DIR / "experiment_guardrail.csv", index=False)
    print(f"Experiment on {n} seeds, each run under all three arms. Drones shipped:\n")
    print(pairs[["comparison", "mean_base", "mean_arm", "difference", "adj_ci_lo", "adj_ci_hi", "p_holm"]].to_string(index=False))
    print("\nSecondary outcomes and the guardrail (paired differences):")
    print(pd.concat([secondary, guardrails])[["metric", "comparison", "mean_base", "mean_arm", "difference", "ci_lo", "ci_hi"]]
          .to_string(index=False))
    un = unpaired_test(runs, PRIMARY)
    print(f"\nUnpaired design, A vs B (each seed given one arm at random): difference {un['difference']:+.1f}, "
          f"Welch p = {un['p_welch']:.3g}, n = {un['n_A']} vs {un['n_B']}")
    print(f"A/A false-positive rate: {aa_false_positive_rate():.3f} (should be about {ALPHA})\n")
    print(verdict(pairs, curve, guardrails))


if __name__ == "__main__":
    main()
