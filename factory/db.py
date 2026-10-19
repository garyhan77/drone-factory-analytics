"""Connect to PostgreSQL, apply the schema, and bulk-load DataFrames."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "sql" / "schema.sql"

# Every raw table, in the order the generator will fill them.
TABLES = [
    "stations",
    "suppliers",
    "parts",
    "bom",
    "inventory_snapshots",
    "receiving",
    "work_orders",
    "inspections",
    "drone_part_lots",
    "finished_goods",
]


def connect(url: str | None = None) -> psycopg.Connection:
    """Open a connection. Uses DATABASE_URL from the environment or .env if no url is given."""
    if url is None:
        load_dotenv(ROOT / ".env")
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and edit it.")
    return psycopg.connect(url)


def apply_schema(conn: psycopg.Connection) -> None:
    """Drop and recreate every raw table. Existing data in those tables is lost."""
    conn.execute(SCHEMA_PATH.read_text())
    conn.commit()


def load_dataframe(conn: psycopg.Connection, table: str, df: pd.DataFrame) -> int:
    """Bulk-load a DataFrame into raw_<table> with COPY. Returns the number of rows loaded."""
    if table not in TABLES:
        raise ValueError(f"Unknown table: {table!r}")
    columns = ", ".join(df.columns)
    rows = df.astype(object).where(df.notna(), None)  # NaN, NaT and pd.NA become NULL
    with conn.cursor() as cur:
        with cur.copy(f"COPY raw_{table} ({columns}) FROM STDIN") as copy:
            for row in rows.itertuples(index=False, name=None):
                copy.write_row(row)
    conn.commit()
    return len(df)


def load_all(conn: psycopg.Connection, frames: dict[str, pd.DataFrame]) -> dict[str, int]:
    """Load every table in TABLES that has a DataFrame. Returns rows loaded per table."""
    return {name: load_dataframe(conn, name, frames[name]) for name in TABLES if name in frames}


if __name__ == "__main__":
    with connect() as conn:
        apply_schema(conn)
        found = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE 'raw\\_%' ORDER BY 1"
        ).fetchall()
        print(f"Schema applied. {len(found)} tables:")
        for (name,) in found:
            print(f"  {name}")
