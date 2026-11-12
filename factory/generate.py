"""Generate all ten raw tables.

    tables = generate(seed).tables
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from factory import config as cfg
from factory.dimensions import build_bom, build_parts, build_suppliers
from factory.line import simulate_line
from factory.shipping import build_finished_goods


@dataclass
class Generated:
    tables: dict[str, pd.DataFrame]
    target: str | None = None  # "host/database" the data was loaded into, filled in by factory.build (never the password)
    truth: pd.DataFrame | None = None  # internal: per-job fail draw, pressure and substitute flag


def generate(seed: int = cfg.SEED) -> Generated:
    line = simulate_line(np.random.default_rng(seed))
    tables = {
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
    return Generated(tables, truth=line.job_truth)
