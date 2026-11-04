"""The regression models: sound inputs, stable fits, and agreement with what the generator fixes."""
import numpy as np
import pytest

from analysis.causal import observed_frame
from analysis.regression import (
    avionics_frame, implied_hours_per_queued_drone, logistic_model, run_study, summarize_logit, summarize_wait,
    wait_model,
)
from analysis.sim import TRUE_EFFECT, simulate_analysis
from factory import config as cfg


@pytest.fixture(scope="module")
def gen():
    return simulate_analysis(cfg.SEED)


def test_queue_at_arrival_matches_a_brute_force_count(gen):
    df = avionics_frame(gen)
    start = df["start"].fillna(df["arrive"].max() + np.timedelta64(10_000, "D"))  # unstarted drones are still waiting
    for i in range(0, len(df), 25):  # a sample of drones, each checked against a direct count
        t = df.loc[i, "arrive"]
        waiting = ((df["arrive"] <= t) & (start > t)).sum() - int(start[i] > t)
        assert df.loc[i, "queue"] == waiting
    assert df["queue"].min() == 0
    assert (df["wait_h"].dropna() >= 0).all()


def test_logistic_fit_survives_a_time_block_with_no_failures(gen):
    """On the default seed one block has no failures and separates perfectly; that must not sink the fit."""
    df = observed_frame(gen)
    r = logistic_model(df, control=True, boot=50, seed=1)
    assert r is not None
    assert r.or_lo < r.odds_ratio < r.or_hi
    assert r.effect_lo < r.effect < r.effect_hi
    assert r.effect_lo < TRUE_EFFECT < r.effect_hi


def test_the_naive_logistic_model_overstates_the_effect_more_than_the_blocked_one(gen):
    df = observed_frame(gen)
    naive, blocked = logistic_model(df, control=False, boot=20), logistic_model(df, control=True, boot=20)
    assert naive.effect > blocked.effect


def test_avionics_wait_slope_agrees_with_the_throughput_check(gen):
    w = wait_model(gen)
    assert 5.0 < implied_hours_per_queued_drone(gen) < 8.0
    assert w.lo < w.slope < w.hi
    assert abs(w.slope / w.implied - 1) < 0.15
    assert w.r_squared > 0.9


def test_regressions_recover_what_the_generator_fixes():
    """Over 20 seeds: blocked logistic is close to 19.5 points and the naive one is not; wait slope matches throughput."""
    logit, wait, skipped = run_study(range(20), boot=20)
    assert len(skipped) < 6
    by_model = summarize_logit(logit).set_index("model")
    assert by_model.loc["time-blocks (3 weeks)", "bias"] < 0.04
    assert by_model.loc["time-blocks (3 weeks)", "bias"] > -0.04
    assert by_model.loc["naive (no time control)", "bias"] > 0.03
    w = summarize_wait(wait)
    assert abs(w["median_slope_over_implied"] - 1) < 0.1
    assert w["share_within_15pct"] > 0.9
