"""Run the factory simulation with some settings changed, without editing the default configuration."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from factory import config as cfg
from factory.generate import Generated, generate

# The effect planted in the generator: a Motor & Prop job on a substitute (spot-buy) fastener lot fails this
# much more often than on a regular lot, whatever else is going on. It is exact by construction.
TRUE_EFFECT = cfg.SUBSTITUTE_FAIL_RATE - next(s.fail_rate for s in cfg.STATIONS if s.code == cfg.SPIKE_STATION)


# The confounder used by every analysis run: in the weeks inspectors are swamped (config.PRESSURE_WEEKS) every
# station's baseline first-pass fail rate is 10 points higher. Those are also the weeks substitute lots reach
# the line, so a naive comparison overstates the lot effect (about 25% against a true 19.5 points).
ANALYSIS_PRESSURE_SLOPE = 0.10


@contextmanager
def override(**values: object) -> Iterator[None]:
    """Temporarily set config values (by name), restoring the originals afterwards, even on an error."""
    unknown = [name for name in values if not hasattr(cfg, name)]
    if unknown:
        raise AttributeError(f"not a config setting: {', '.join(unknown)}")
    saved = {name: getattr(cfg, name) for name in values}
    for name, value in values.items():
        setattr(cfg, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(cfg, name, value)


def simulate(seed: int, **overrides: object) -> Generated:
    """generate(seed) with the given config settings changed for this run only."""
    with override(**overrides):
        return generate(seed)


def simulate_analysis(seed: int, **overrides: object) -> Generated:
    """The analysis dataset for a seed: the usual factory with the pressure confounder switched on."""
    return simulate(seed, **{"FAIL_RATE_PRESSURE_SLOPE": ANALYSIS_PRESSURE_SLOPE, **overrides})
