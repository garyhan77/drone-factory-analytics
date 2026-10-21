"""Generate all ten raw tables, with the planted errors and the answer key.

    clean = generate(seed).clean      the tables as they would be with no mistakes
    dirty = generate(seed).tables     the tables the data quality checks should run on
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from factory import config as cfg
from factory.dimensions import build_bom, build_parts, build_suppliers
from factory.errors import Windows, plant_errors
from factory.line import simulate_line
from factory.shipping import build_finished_goods


@dataclass
class Generated:
    tables: dict[str, pd.DataFrame]  # with planted errors
    clean: dict[str, pd.DataFrame]  # without
    answer_key: dict[str, list[str]]  # check name -> record keys that were corrupted
    windows: Windows


def generate(seed: int = cfg.SEED) -> Generated:
    line = simulate_line(np.random.default_rng(seed))
    clean = {
        "stations": line.stations,
        "suppliers": build_suppliers(),
        "parts": build_parts(),
        "bom": build_bom(),
        "inventory_snapshots": line.inventory_snapshots,
        "receiving": line.receiving,
        "work_orders": line.work_orders,
        "inspections": line.inspections,
        "drone_part_lots": line.drone_part_lots,
        "finished_goods": build_finished_goods(line.work_orders, np.random.default_rng(seed + 1)),
    }
    tables, answer_key, windows = plant_errors(clean, np.random.default_rng(seed + 2))
    return Generated(tables, clean, answer_key, windows)
