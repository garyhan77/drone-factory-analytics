"""The analysis layer must not change the default data, and its confounder must behave as documented."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from analysis.sim import ANALYSIS_PRESSURE_SLOPE, TRUE_EFFECT, override, simulate, simulate_analysis
from factory import config as cfg
from factory.generate import generate

FIXTURE = Path(__file__).parent / "fixtures" / "default_fingerprints.json"


def fingerprint(gen) -> dict[str, str]:
    return {
        name: hashlib.sha256(pd.util.hash_pandas_object(df.reset_index(drop=True), index=False).values.tobytes()).hexdigest()[:16]
        for name, df in sorted(gen.tables.items())
    }


def test_default_output_is_unchanged():
    """Every table, for seeds 0-5 and the default seed, is identical to what it was before the analysis layer."""
    expected = json.loads(FIXTURE.read_text())
    assert cfg.FAIL_RATE_PRESSURE_SLOPE == 0.0
    for seed, tables in expected.items():
        assert fingerprint(generate(int(seed))) == tables, f"seed {seed} changed"


def test_override_restores_the_setting_even_on_error():
    before = cfg.REORDER_SAFETY_DAYS
    with pytest.raises(RuntimeError):
        with override(REORDER_SAFETY_DAYS=99):
            assert cfg.REORDER_SAFETY_DAYS == 99
            raise RuntimeError
    assert cfg.REORDER_SAFETY_DAYS == before


def test_override_rejects_unknown_settings():
    with pytest.raises(AttributeError):
        override(NOT_A_SETTING=1).__enter__()


def test_truth_has_one_row_per_job():
    gen = generate(cfg.SEED)
    jobs = gen.clean["work_orders"].groupby("station_code").size()
    assert gen.truth.groupby("station_code").size().to_dict() == jobs.to_dict()


def test_pressure_applies_only_in_the_swamped_weeks():
    truth = simulate_analysis(cfg.SEED).truth
    in_window = truth["week"].isin(cfg.PRESSURE_WEEKS)
    assert (truth.loc[in_window, "pressure"] == ANALYSIS_PRESSURE_SLOPE).all()
    assert (truth.loc[~in_window, "pressure"] == 0.0).all()


def test_every_outcome_follows_the_documented_rule_and_the_effect_is_constant():
    """failed == fail_draw < base + pressure (+ the planted lot effect), so the true effect is the same for every job."""
    truth = simulate_analysis(cfg.SEED).truth
    base = truth["station_code"].map({s.code: s.fail_rate for s in cfg.STATIONS})
    rate = base + truth["pressure"]
    rate = rate.where(~truth["substitute"], cfg.SUBSTITUTE_FAIL_RATE + truth["pressure"])
    assert ((truth["fail_draw"] < rate) == truth["failed"]).all()
    assert TRUE_EFFECT == pytest.approx(0.195)
    assert truth["substitute"].any()
    assert (truth.loc[truth["substitute"], "station_code"] == cfg.SPIKE_STATION).all()


def test_confounder_makes_the_naive_estimate_too_high():
    """Pooled over a few seeds, the naive difference sits well above the true effect with the confounder on."""
    fails = n = fails0 = n0 = 0
    for seed in range(8):
        t = simulate_analysis(seed).truth
        m = t[t["station_code"] == cfg.SPIKE_STATION]
        fails, n = fails + m.loc[m["substitute"], "failed"].sum(), n + m["substitute"].sum()
        fails0, n0 = fails0 + m.loc[~m["substitute"], "failed"].sum(), n0 + (~m["substitute"]).sum()
    naive = fails / n - fails0 / n0
    assert naive > TRUE_EFFECT + 0.02
