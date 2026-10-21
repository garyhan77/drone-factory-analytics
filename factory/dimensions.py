"""The reference tables: suppliers, parts and the bill of materials."""
from __future__ import annotations

import math
from collections import Counter

import pandas as pd

from factory import config as cfg
from factory.inventory import PartSpec


def part_ids() -> list[str]:
    """Part IDs in config order: the station code and a running number, for example MTR-003."""
    counts: Counter[str] = Counter()
    ids = []
    for part in cfg.PARTS:
        counts[part.station_code] += 1
        ids.append(f"{part.station_code}-{counts[part.station_code]:03d}")
    return ids


def launch_drones_per_day() -> float:
    """Average drones released per calendar day during the launch weeks."""
    weekly = [cfg.weekly_releases(w) for w in cfg.LAUNCH_DEMAND_WEEKS]
    return sum(weekly) / len(weekly) / 7


def build_suppliers() -> pd.DataFrame:
    return pd.DataFrame(
        [(s.supplier_id, s.name) for s in cfg.SUPPLIERS],
        columns=["supplier_id", "supplier_name"],
    )


def build_parts() -> pd.DataFrame:
    """Parts master. The reorder point covers launch demand over (lead time + safety days)."""
    lead = {s.supplier_id: s.lead_days for s in cfg.SUPPLIERS}
    rows = []
    for part_id, part in zip(part_ids(), cfg.PARTS):
        daily_demand = launch_drones_per_day() * part.qty_per_drone
        lead_days = lead[part.supplier_id]
        rows.append({
            "part_id": part_id,
            "part_name": part.name,
            "supplier_id": part.supplier_id,
            "unit_cost": part.unit_cost,
            "reorder_point": math.ceil(daily_demand * (lead_days + cfg.REORDER_SAFETY_DAYS)),
            "lead_time_days": lead_days,
        })
    return pd.DataFrame(rows)


def build_bom() -> pd.DataFrame:
    return pd.DataFrame(
        [(part.station_code, part_id, part.qty_per_drone) for part_id, part in zip(part_ids(), cfg.PARTS)],
        columns=["station_code", "part_id", "qty_per_unit"],
    )


def part_specs(station_code: str | None = None) -> list[PartSpec]:
    """Parts in kit-list order (config order), ready for the inventory simulation."""
    reorder = build_parts().set_index("part_id")["reorder_point"]
    lead = {s.supplier_id: s.lead_days for s in cfg.SUPPLIERS}
    return [
        PartSpec(
            part_id=part_id, name=part.name, supplier_id=part.supplier_id, qty_per_drone=part.qty_per_drone,
            reorder_point=int(reorder[part_id]), lead_days=lead[part.supplier_id],
            launch_daily_units=launch_drones_per_day() * part.qty_per_drone,
        )
        for part_id, part in zip(part_ids(), cfg.PARTS)
        if station_code is None or part.station_code == station_code
    ]
