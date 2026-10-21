"""Run the SQL data quality checks in sql/checks/ and score them against the answer key.

Each check is one .sql file. Its header comments give a severity, a category and a description, and the
query returns one row per offending record in a column called ``record_key``. The file name is the check name.

Categories:
  planted         an error the generator deliberately planted; scored against the answer key
  reconciliation  catches the effect of a planted error from a second angle; scored against the answer key
  guard        a relationship nothing was planted into; should flag nothing
  sanity       a standard validation rule; should flag nothing here
  operational  something operations should see, not a data error; not scored

For the scored categories, every flagged row that is not in the answer key counts as a false positive.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import psycopg

from factory.db import ROOT, connect, load_dq_table

CHECKS_DIR = ROOT / "sql" / "checks"
SEVERITIES = {"error", "warn"}
CATEGORIES = {"planted", "reconciliation", "guard", "sanity", "operational"}
SCORED = {"planted", "reconciliation", "guard", "sanity"}


@dataclass(frozen=True)
class Check:
    name: str
    severity: str
    category: str
    description: str
    sql: str


def _header(sql: str, field: str, path: Path) -> str:
    match = re.search(rf"^--\s*{field}:\s*(.+)$", sql, re.M)
    if not match:
        raise ValueError(f"{path.name} is missing a '-- {field}:' header")
    return match.group(1).strip()


def discover_checks(directory: Path = CHECKS_DIR) -> list[Check]:
    checks = []
    for path in sorted(directory.glob("*.sql")):
        sql = path.read_text()
        check = Check(path.stem, _header(sql, "severity", path), _header(sql, "category", path),
                      _header(sql, "description", path), sql)
        if check.severity not in SEVERITIES:
            raise ValueError(f"{path.name}: severity must be one of {sorted(SEVERITIES)}, got {check.severity!r}")
        if check.category not in CATEGORIES:
            raise ValueError(f"{path.name}: category must be one of {sorted(CATEGORIES)}, got {check.category!r}")
        checks.append(check)
    return checks


def run_check(conn: psycopg.Connection, check: Check) -> list[str]:
    """The record keys a check flags, without repeats and in order."""
    keys = [str(row[0]) for row in conn.execute(check.sql).fetchall()]
    return sorted(set(keys))


def score(checks: list[Check], flagged: dict[str, list[str]], answer_key: dict[str, list[str]]) -> pd.DataFrame:
    """One row per check: how many rows it flagged and, for scored checks, caught, missed and false positives."""
    rows = []
    for check in checks:
        found = set(flagged[check.name])
        row = {"check_name": check.name, "category": check.category, "severity": check.severity,
               "description": check.description, "flagged_rows": len(found),
               "planted_rows": pd.NA, "caught": pd.NA, "missed": pd.NA, "false_positives": pd.NA}
        if check.category in SCORED:
            expected = set(answer_key.get(check.name, []))
            row.update(planted_rows=len(expected), caught=len(expected & found),
                       missed=len(expected - found), false_positives=len(found - expected))
        rows.append(row)
    df = pd.DataFrame(rows)
    for col in ("planted_rows", "caught", "missed", "false_positives"):
        df[col] = df[col].astype("Int64")
    return df


def run_all(conn: psycopg.Connection, answer_key: dict[str, list[str]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run every check. Returns (results per check, one row per flagged record)."""
    checks = discover_checks()
    flagged = {c.name: run_check(conn, c) for c in checks}
    results = score(checks, flagged, answer_key)
    rows = pd.DataFrame([(name, key) for name, keys in flagged.items() for key in keys],
                        columns=["check_name", "record_key"])
    return results, rows


def store_answer_key(conn: psycopg.Connection, answer_key: dict[str, list[str]]) -> None:
    rows = pd.DataFrame([(name, key) for name, keys in answer_key.items() for key in keys],
                        columns=["check_name", "record_key"])
    load_dq_table(conn, "dq_answer_key", rows)


def read_answer_key(conn: psycopg.Connection) -> dict[str, list[str]]:
    key: dict[str, list[str]] = {}
    for name, record in conn.execute("SELECT check_name, record_key FROM dq_answer_key ORDER BY 1, 2"):
        key.setdefault(name, []).append(record)
    return key


def store_results(conn: psycopg.Connection, results: pd.DataFrame, flagged: pd.DataFrame) -> None:
    conn.execute("TRUNCATE dq_results, dq_flagged")
    conn.commit()
    load_dq_table(conn, "dq_results", results)
    load_dq_table(conn, "dq_flagged", flagged)


def check_database(conn: psycopg.Connection) -> pd.DataFrame:
    """Run every check against the database, using the stored answer key, and store the results."""
    results, flagged = run_all(conn, read_answer_key(conn))
    store_results(conn, results, flagged)
    return results


def main() -> None:
    with connect() as conn:
        results = check_database(conn)
    scored = results[results["category"].isin(SCORED)]
    print(results[["check_name", "category", "flagged_rows", "planted_rows", "caught", "missed", "false_positives"]].to_string(index=False))
    planted = results[results["category"] == "planted"]
    print(f"\nplanted errors: {int(planted['caught'].sum())} of {int(planted['planted_rows'].sum())} caught, "
          f"{int(scored['missed'].sum())} missed, {int(scored['false_positives'].sum())} false positives across {len(scored)} scored checks")


if __name__ == "__main__":
    main()
