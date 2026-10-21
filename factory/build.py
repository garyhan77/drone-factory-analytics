"""Generate the data, create the tables, and load everything into PostgreSQL.

    python -m factory.build          (or: make build)

This DROPS and recreates the raw tables in the database that DATABASE_URL points at.
"""
from __future__ import annotations

import argparse
import json

from factory import config as cfg
from factory.checks import check_database, store_answer_key
from factory.db import ROOT, apply_schema, apply_views, connect, load_all
from factory.generate import Generated, generate

DATA_DIR = ROOT / "data"


def build(url: str | None = None, seed: int = cfg.SEED, write_files: bool = True) -> Generated:
    data = generate(seed)
    with connect(url) as conn:
        apply_schema(conn)
        load_all(conn, data.tables)
        apply_views(conn)
        store_answer_key(conn, data.answer_key)
        data.results = check_database(conn)
    if write_files:
        DATA_DIR.mkdir(exist_ok=True)
        (DATA_DIR / "answer_key.json").write_text(json.dumps({
            "seed": seed,
            "planted": data.answer_key,
            "windows": data.windows.ranges,
        }, indent=2))
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=cfg.SEED)
    args = parser.parse_args()
    data = build(seed=args.seed)
    for name, df in data.tables.items():
        print(f"{name:22s}{len(df):>8,} rows")
    print("\nplanted errors:")
    for name in cfg.PLANTED_COUNTS:
        print(f"  {name:24s}{len(data.answer_key[name]):>3}")
    print(f"\nAnswer key written to {DATA_DIR / 'answer_key.json'}")


if __name__ == "__main__":
    main()
