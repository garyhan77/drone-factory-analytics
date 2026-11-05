"""The Avionics capacity experiment: arms, power analysis and tests behave as designed."""
import numpy as np
import pandas as pd
import pytest

from analysis import experiment as ex
from factory import config as cfg


def test_arms_change_only_the_avionics_lane_count_and_leave_the_default_alone():
    stations = ex.avionics_lanes(3)
    assert [s.lanes for s in stations if s.code == "AVN"] == [3]
    assert [s for s in stations if s.code != "AVN"] == [s for s in cfg.STATIONS if s.code != "AVN"]
    before = [s.lanes for s in cfg.STATIONS]
    ex.run_arm(0, "B")
    assert [s.lanes for s in cfg.STATIONS] == before


def test_each_extra_lane_ships_more_drones_but_the_fourth_adds_much_less():
    runs = ex.collect(range(3))
    w = ex.wide(runs, ex.PRIMARY)
    assert ((w["B"] - w["A"]) > 20).all()  # the third lane is a clear gain on every seed
    assert (w["C"] - w["B"]).mean() < (w["B"] - w["A"]).mean() / 3  # the fourth is a much smaller one
    queue = ex.wide(runs, "avionics_queue_at_extract")
    assert (queue["B"] < queue["A"]).all()
    assert ex.curvature(runs).mean() < 0


def test_runs_are_reproducible():
    assert ex.run_arm(1, "B") == ex.run_arm(1, "B")


def test_power_analysis_matches_the_textbook_case_and_inverts():
    assert ex.seeds_needed(sd=1.0, effect=1.0, paired=True) == 10  # one-sample t-test, d = 1, 80% power
    n = ex.seeds_needed(15.0, 25.0, paired=True)
    assert ex.minimum_detectable_effect(15.0, n, paired=True) <= 25.0 < ex.minimum_detectable_effect(15.0, n - 1, paired=True)
    assert ex.seeds_needed(15.0, 10.0, paired=True) > ex.seeds_needed(15.0, 25.0, paired=True)


def test_pairing_needs_fewer_runs_when_the_arms_are_correlated():
    pilot = ex.Pilot(sd_a=17.0, sd_b=20.0, sd_diff=15.0, correlation=0.69, mean_diff=44.0)
    plan = ex.sample_size_plan(pilot).set_index("smallest_effect")
    # paired: every seed is run under both arms (2n runs); unpaired: n per arm (2n runs), so compare n directly
    assert (plan["paired_seeds"] < plan["unpaired_seeds_per_arm"]).all()


def test_sign_flip_test_separates_a_clear_effect_from_noise():
    assert ex.sign_flip_p(np.full(10, 5.0)) < 0.01
    assert ex.sign_flip_p(np.array([1.0, -1.0] * 5)) > 0.9


def test_paired_test_on_a_known_difference():
    rng = np.random.default_rng(0)
    base = rng.normal(600, 20, 30)
    runs = pd.DataFrame({"seed": np.tile(np.arange(30), 2), "arm": ["A"] * 30 + ["B"] * 30,
                         "shipped": np.concatenate([base, base + 40 + rng.normal(0, 5, 30)])})
    r = ex.paired_test(runs, "shipped")
    assert r["ci_lo"] < 40 < r["ci_hi"] and r["p_t"] < 1e-6 and r["p_permutation"] < 1e-3


def test_a_null_comparison_is_rejected_about_five_percent_of_the_time():
    values = np.random.default_rng(1).normal(600, 20, 60)
    assert 0.02 < ex.rejection_rate_under_null(values, splits=1500) < 0.09


def test_pilot_first_version_and_experiment_seeds_do_not_overlap():
    first_version = range(1000, 1020)  # the two-arm run that preceded the fourth lane
    assert max(ex.PILOT_SEEDS) < min(first_version)
    assert max(first_version) < ex.EXPERIMENT_SEEDS_START < ex.AA_SEEDS_START


def _synthetic_runs(n=30, seed=0):
    rng = np.random.default_rng(seed)
    base = rng.normal(600, 20, n)
    third = 50 + rng.normal(0, 8, n)
    fourth = 6 + rng.normal(0, 8, n)
    return pd.DataFrame({
        "seed": np.tile(np.arange(n), 3), "arm": ["A"] * n + ["B"] * n + ["C"] * n,
        "shipped": np.concatenate([base, base + third, base + third + fourth]),
    })


def test_curvature_is_the_gain_from_lane_four_minus_the_gain_from_lane_three():
    runs = pd.DataFrame({"seed": [0, 0, 0], "arm": ["A", "B", "C"], "shipped": [600.0, 650.0, 656.0]})
    assert ex.curvature(runs).tolist() == [-44.0]  # (656 - 650) - (650 - 600)


def test_pairwise_table_adjusts_for_three_comparisons():
    table = ex.pairwise_table(_synthetic_runs())
    assert table["comparison"].tolist() == ["B vs A", "C vs B", "C vs A"]
    assert ((table["adj_ci_hi"] - table["adj_ci_lo"]) > (table["ci_hi"] - table["ci_lo"])).all()  # simultaneous CIs are wider
    assert (table["p_holm"] >= table["p_t"] - 1e-12).all()
    assert (table["p_holm"] <= 1).all()


def test_the_decision_rule_builds_the_third_lane_but_not_the_fourth_on_a_known_effect():
    table = ex.pairwise_table(_synthetic_runs())
    clears = (table["adj_ci_lo"] >= ex.MIN_WORTHWHILE).tolist()
    assert clears == [True, False, True]
    curve = ex.curvature_test(_synthetic_runs())
    assert curve["ci_hi"] < 0 and curve["p_t"] < 1e-6


def test_required_seeds_uses_the_larger_of_the_two_power_needs():
    n = ex.required_seeds(_synthetic_runs(60))
    runs = _synthetic_runs(60)
    sd_third = ex.pilot_summary(runs).sd_diff
    sd_curve = float(ex.curvature(runs).std(ddof=1))
    assert n == max(ex.seeds_needed(sd_third, ex.MIN_WORTHWHILE, True), ex.seeds_needed(sd_curve, ex.MIN_WORTHWHILE, True))
