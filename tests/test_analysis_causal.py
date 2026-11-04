"""The causal estimators: built only from observable data, correct on toy cases, and close to the planted truth."""
import numpy as np
import pandas as pd
import pytest
import statsmodels.formula.api as smf

from analysis.causal import (
    adjusted, estimate, evaluate_seed, ipw, naive, observed_frame, run_study, strata, summarize,
)
from analysis.sim import TRUE_EFFECT, simulate_analysis
from factory import config as cfg


@pytest.fixture(scope="module")
def gen():
    return simulate_analysis(cfg.SEED)


def test_observed_frame_agrees_with_the_hidden_truth(gen):
    """The analyst's view (traceability, work orders, first inspections) reproduces the generator's own record."""
    df = observed_frame(gen).set_index("serial_number")
    truth = gen.truth[gen.truth["station_code"] == cfg.SPIKE_STATION].set_index("serial_number")
    joined = df.join(truth, rsuffix="_truth")
    assert len(df) > 600 and df["treated"].sum() > 20
    assert (joined["treated"] == joined["substitute"]).all()
    assert (joined["week"] == joined["week_truth"]).all()
    assert (joined["failed"] == joined["failed_truth"]).all()


def test_estimators_on_a_small_hand_checked_example():
    # Week 1: 2 treated (1 fails), 2 control (0 fail). Week 2: 1 treated (1 fails), 3 control (1 fails).
    week = np.array([1, 1, 1, 1, 2, 2, 2, 2])
    treated = np.array([1, 1, 0, 0, 1, 0, 0, 0], dtype=bool)
    failed = np.array([1, 0, 0, 0, 1, 1, 0, 0], dtype=bool)
    s = strata(week, treated, failed)
    assert naive(s) == pytest.approx(2 / 3 - 1 / 5)
    # within-week differences 0.5 and 2/3; weights n1*n0/(n1+n0) = 1 and 0.75
    assert adjusted(s) == pytest.approx((1 * 0.5 + 0.75 * (1 - 1 / 3)) / 1.75)
    # propensities 0.5 and 0.25: treated mean (2 + 4) / (4 + 4) = 0.75, control mean (0 + 4/3) / (4 + 4) = 1/6
    assert ipw(s) == pytest.approx(0.75 - 1 / 6)


def test_adjusted_estimator_equals_ols_with_a_dummy_for_every_week(gen):
    df = observed_frame(gen)
    model = smf.ols("failed ~ treated + C(week)", data=df.astype({"failed": float, "treated": float})).fit()
    s = strata(df["week"].to_numpy(), df["treated"].to_numpy(), df["failed"].to_numpy())
    assert adjusted(s) == pytest.approx(model.params["treated"])


def test_bootstrap_interval_contains_the_point_estimate_and_is_reproducible(gen):
    df = observed_frame(gen)
    first, second = estimate(df, boot=100, seed=1), estimate(df, boot=100, seed=1)
    pd.testing.assert_frame_equal(first, second)
    assert ((first["lo"] <= first["estimate"]) & (first["estimate"] <= first["hi"])).all()


def test_a_seed_with_no_substitute_lots_is_skipped():
    assert evaluate_seed(12, boot=10) is None


def test_estimators_recover_the_planted_effect_and_naive_does_not():
    """Over 30 seeds: naive is biased high; adjusted and IPW are close to 19.5 points; the placebo shows why."""
    study, skipped = run_study(range(30), boot=50)
    assert len(skipped) < 8
    s = summarize(study).set_index(["station", "estimator"])
    assert s.loc[("MTR", "naive"), "bias"] > 0.03
    assert abs(s.loc[("MTR", "adjusted"), "bias"]) < 0.04
    assert abs(s.loc[("MTR", "ipw"), "bias"]) < 0.04
    for station in ("AFL", "WNG"):  # no true effect: naive finds one anyway, adjusted does not
        assert s.loc[(station, "naive"), "mean_estimate"] > 0.03
        assert abs(s.loc[(station, "adjusted"), "mean_estimate"]) < 0.03
