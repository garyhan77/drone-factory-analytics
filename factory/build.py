"""Generate the data, create the tables, and load everything into PostgreSQL.

    python -m factory.build          (or: make build)

This DROPS and recreates the raw tables in the database that DATABASE_URL points at. It refuses to touch a database on
another machine unless you pass --remote.

    python -m factory.build --remote --grant-to app_readonly     load a hosted database and let the read-only role read it
"""
from __future__ import annotations

import argparse

from factory import config as cfg
from factory.db import apply_grants, apply_schema, apply_views, connect, load_all
from factory.generate import Generated, generate


def build(url: str | None = None, seed: int = cfg.SEED, *,
          allow_remote: bool = False, grant_to: str | None = None) -> Generated:
    data = generate(seed)
    with connect(url) as conn:
        apply_schema(conn, allow_remote=allow_remote)
        load_all(conn, data.tables)
        apply_views(conn)
        if grant_to:
            apply_grants(conn, grant_to)
        data.target = f"{conn.info.host}/{conn.info.dbname}"
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=cfg.SEED)
    parser.add_argument("--remote", action="store_true", help="allow dropping and recreating tables on a remote database")
    parser.add_argument("--grant-to", metavar="ROLE", help="let this read-only role read everything after the build")
    args = parser.parse_args()
    data = build(seed=args.seed, allow_remote=args.remote, grant_to=args.grant_to)
    for name, df in data.tables.items():
        print(f"{name:22s}{len(df):>8,} rows")
    print(f"\nLoaded into {data.target}" + (f"; {args.grant_to} can read it" if args.grant_to else ""))


if __name__ == "__main__":
    main()
