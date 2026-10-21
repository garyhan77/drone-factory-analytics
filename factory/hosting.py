"""Set up and check the hosted database's read-only role.

The live app connects with a role that can only read. Create it with SQL, never in a hosting provider's web console:
on Neon, console-created roles are made members of neon_superuser, which can write everything.

    make create-readonly-role     (needs DATABASE_URL = the admin connection string; prompts for the new password)
    make verify-hosting           (prompts for the read-only connection string; proves it can read and cannot write)
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from dataclasses import dataclass

import psycopg
from psycopg import sql

POWERFUL_ROLES = ("pg_write_all_data", "neon_superuser", "pg_execute_server_program", "pg_write_server_files")

# Harmless to run: each is tried inside a transaction that is always rolled back.
WRITE_PROBES = {
    "INSERT": "INSERT INTO raw_stations (station_seq, station_code, station_name) VALUES (99, 'ZZZ', 'probe')",
    "UPDATE": "UPDATE raw_stations SET station_name = station_name",
    "DELETE": "DELETE FROM raw_stations",
    "TRUNCATE": "TRUNCATE raw_stations",
    "DROP TABLE": "DROP TABLE raw_stations",
    "CREATE TABLE": "CREATE TABLE readonly_probe (x integer)",
}


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


def create_readonly_role(conn: psycopg.Connection, role: str, password: str, *, reset: bool = False) -> str:
    """Create a login role that can only read. Returns "created" or "reset".

    NOINHERIT and every NO* attribute keep it from gaining powers; default_transaction_read_only and a statement
    timeout are role settings, so they apply to every connection it opens, including through a pooler.
    """
    who = sql.Identifier(role)
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone() is not None
    if exists and not reset:
        raise RuntimeError(f"The role {role!r} already exists. Run with --reset-password to set a new password for it.")
    if exists:
        conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(who, sql.Literal(password)))
    else:
        conn.execute(sql.SQL(
            "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS "
            "CONNECTION LIMIT 10").format(who, sql.Literal(password)))
    conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(who))
    conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '30s'").format(who))
    conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(conn.info.dbname), who))
    conn.commit()
    return "reset" if exists else "created"


def check_readonly(url: str) -> list[Check]:
    """Connect as the app's role and verify it can read, and cannot write, create or drop anything."""
    checks: list[Check] = []
    with psycopg.connect(url, autocommit=True, connect_timeout=30) as conn:
        for label, table in (("a raw table", "raw_work_orders"), ("a metric view", "v_station_summary")):
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                checks.append(Check(f"can read {label}", count > 0, f"{count:,} rows in {table}"))
            except psycopg.Error as error:
                checks.append(Check(f"can read {label}", False, str(error).splitlines()[0]))

        user = conn.execute("SELECT current_user").fetchone()[0]
        attrs = conn.execute(
            "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_roles WHERE rolname = current_user").fetchone()
        checks.append(Check("is not a superuser and cannot create roles or databases", not any(attrs), f"role {user}"))

        held = [r for r in POWERFUL_ROLES
                if conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (r,)).fetchone()
                and conn.execute("SELECT pg_has_role(current_user, %s, 'member')", (r,)).fetchone()[0]]
        checks.append(Check("belongs to no powerful role", not held, ", ".join(held) or "none of " + ", ".join(POWERFUL_ROLES)))

        for label, statement in WRITE_PROBES.items():
            try:
                with conn.transaction(force_rollback=True):  # nothing is ever kept, even if the statement succeeds
                    conn.execute(statement)
                checks.append(Check(f"{label} is refused", False, "it SUCCEEDED (then rolled back): this role can write"))
            except psycopg.Error as error:
                checks.append(Check(f"{label} is refused", True, str(error).splitlines()[0]))

        setting = conn.execute("SHOW default_transaction_read_only").fetchone()[0]
        checks.append(Check("is read-only by default", setting == "on", f"default_transaction_read_only = {setting}"))
        timeout = conn.execute("SHOW statement_timeout").fetchone()[0]
        checks.append(Check("has a statement timeout", timeout not in ("0", "0ms"), f"statement_timeout = {timeout}"))
    return checks


def report(checks: list[Check]) -> str:
    lines = [f"{'PASS' if c.passed else 'FAIL'}  {c.name}" + (f"  ({c.detail})" if c.detail else "") for c in checks]
    failed = sum(not c.passed for c in checks)
    lines.append("")
    lines.append("All checks passed: this role is safe to give the live app." if not failed
                 else f"{failed} check(s) FAILED: do not use this role for the live app.")
    return "\n".join(lines)


def _ask_password() -> str:
    first = getpass.getpass("New password for the read-only role (input is hidden): ")
    if len(first) < 16:
        sys.exit("Use at least 16 characters.")
    if getpass.getpass("Type it again: ") != first:
        sys.exit("The passwords do not match.")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-role", help="create the read-only role (uses DATABASE_URL, the admin connection)")
    create.add_argument("--name", default="app_readonly")
    create.add_argument("--reset-password", action="store_true")
    commands.add_parser("verify", help="check a read-only connection string (APP_DATABASE_URL, or prompted)")
    args = parser.parse_args(argv)

    if args.command == "create-role":
        url = os.environ.get("DATABASE_URL")
        if not url:
            sys.exit("Set DATABASE_URL to the admin connection string first.")
        with psycopg.connect(url) as conn:
            outcome = create_readonly_role(conn, args.name, _ask_password(), reset=args.reset_password)
            print(f"Role {args.name!r} {outcome} on {conn.info.host}/{conn.info.dbname}.")
        return 0

    url = os.environ.get("APP_DATABASE_URL") or getpass.getpass("Read-only connection string (input is hidden): ")
    checks = check_readonly(url)
    print(report(checks))
    return 0 if all(c.passed for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
