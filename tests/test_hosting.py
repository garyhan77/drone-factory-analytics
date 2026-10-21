"""Hosted-database safety: the remote guard, the read-only role, and the app's reconnecting connection."""
import psycopg
import pytest

from factory import db
from factory.build import build
from factory.hosting import check_readonly, create_readonly_role, report
from factory.viz.data import SharedConnection, to_frame

ROLE = "df_test_readonly"


# ---- the remote guard ----

@pytest.mark.parametrize("host, remote", [
    ("localhost", False), ("127.0.0.1", False), ("::1", False), ("LOCALHOST", False), ("", False), (None, False),
    ("/var/run/postgresql", False),
    ("ep-cool-1234.us-east-2.aws.neon.tech", True), ("10.0.0.5", True), ("localhost.example.com", True),
])
def test_remote_host_detection(host, remote):
    assert db.is_remote_host(host) is remote


class _FakeConn:
    def __init__(self, host):
        self.info = type("Info", (), {"host": host})()
        self.executed = []

    def execute(self, statement):
        self.executed.append(statement)

    def commit(self):
        pass


def test_schema_is_refused_on_a_remote_host_and_nothing_is_run():
    conn = _FakeConn("ep-cool-1234.us-east-2.aws.neon.tech")
    with pytest.raises(RuntimeError, match="remote database"):
        db.apply_schema(conn)
    assert conn.executed == []


def test_schema_runs_on_a_remote_host_only_when_allowed():
    conn = _FakeConn("ep-cool-1234.us-east-2.aws.neon.tech")
    db.apply_schema(conn, allow_remote=True)
    assert conn.executed  # the drop-and-create script ran


# ---- the read-only role, against the local test database ----

def _drop_role(c):
    c.rollback()
    if c.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (ROLE,)).fetchone():
        c.execute(f"DROP OWNED BY {ROLE}")
        c.execute(f"DROP ROLE {ROLE}")
    c.commit()


def test_role_rejects_a_second_create_without_reset(conn):
    _drop_role(conn)
    try:
        assert create_readonly_role(conn, ROLE, "a-long-test-password-123") == "created"
        with pytest.raises(RuntimeError, match="already exists"):
            create_readonly_role(conn, ROLE, "another-long-password-456")
        assert create_readonly_role(conn, ROLE, "another-long-password-456", reset=True) == "reset"
    finally:
        _drop_role(conn)


def test_created_role_is_read_only_and_verification_passes(conn, monkeypatch):
    import os
    url = os.environ["TEST_DATABASE_URL"]
    conn.close()
    admin = psycopg.connect(url)
    _drop_role(admin)
    password = "a-long-test-password-123"
    try:
        create_readonly_role(admin, ROLE, password)
        build(url=url, write_files=False, grant_to=ROLE)
        info = admin.info
        ro_url = f"postgresql://{ROLE}:{password}@{info.host}:{info.port}/{info.dbname}"
        checks = check_readonly(ro_url)
        assert all(c.passed for c in checks), report(checks)
        names = {c.name for c in checks}
        assert {"INSERT is refused", "DROP TABLE is refused", "TRUNCATE is refused", "CREATE TABLE is refused"} <= names
        # and the data really is untouched
        assert admin.execute("SELECT COUNT(*) FROM raw_stations").fetchone()[0] == 5
    finally:
        _drop_role(admin)
        admin.close()


def test_verification_fails_for_a_role_that_can_write(conn):
    import os
    url = os.environ["TEST_DATABASE_URL"]
    conn.close()
    # the admin connection itself is NOT read-only, so the check must say so
    build(url=url, write_files=False)
    checks = {c.name: c for c in check_readonly(url)}
    assert not checks["INSERT is refused"].passed
    assert not checks["is read-only by default"].passed
    assert "FAILED" in report(list(checks.values()))


# ---- the app's reconnecting connection ----

class _Cursor:
    description = [type("Col", (), {"name": "n"})()]

    def fetchall(self):
        return [(1,)]


class _Link:
    def __init__(self, fail_times=0, error=psycopg.OperationalError):
        self.closed, self.fail_times, self.error, self.calls = False, fail_times, error, 0

    def execute(self, sql, params=None):
        self.calls += 1
        if self.fail_times:
            self.fail_times -= 1
            raise self.error("server closed the connection unexpectedly")
        return _Cursor()

    def close(self):
        self.closed = True


def _factory(*links):
    made = list(links)
    opened = []

    def connect(url):
        link = made.pop(0)
        opened.append(link)
        return link
    return connect, opened


def test_connection_is_reused_between_queries():
    connect, opened = _factory(_Link())
    shared = SharedConnection("u", connect)
    shared.fetch("SELECT 1")
    shared.fetch("SELECT 1")
    assert len(opened) == 1 and opened[0].calls == 2


@pytest.mark.parametrize("error", [psycopg.OperationalError, psycopg.InterfaceError])
def test_a_dropped_connection_is_replaced_and_the_query_retried_once(error):
    connect, opened = _factory(_Link(fail_times=1, error=error), _Link())
    columns, rows = SharedConnection("u", connect).fetch("SELECT 1")
    assert (columns, rows) == (["n"], [(1,)])
    assert len(opened) == 2 and opened[0].closed


def test_a_second_failure_is_raised_not_hidden():
    connect, opened = _factory(_Link(fail_times=1), _Link(fail_times=1))
    with pytest.raises(psycopg.OperationalError):
        SharedConnection("u", connect).fetch("SELECT 1")
    assert len(opened) == 2


def test_a_bad_query_is_not_retried():
    link = _Link(fail_times=1, error=psycopg.errors.UndefinedTable)
    connect, opened = _factory(link)
    with pytest.raises(psycopg.errors.UndefinedTable):
        SharedConnection("u", connect).fetch("SELECT * FROM nope")
    assert link.calls == 1 and len(opened) == 1


def test_a_closed_connection_is_reopened_before_use():
    first, second = _Link(), _Link()
    connect, opened = _factory(first, second)
    shared = SharedConnection("u", connect)
    shared.fetch("SELECT 1")
    first.closed = True
    shared.fetch("SELECT 1")
    assert opened == [first, second]


def test_decimals_become_floats_and_other_columns_are_untouched():
    from decimal import Decimal
    df = to_frame(["d", "s"], [(Decimal("1.5"), "a"), (Decimal("2.5"), "b")])
    assert df["d"].dtype == float and list(df["d"]) == [1.5, 2.5] and list(df["s"]) == ["a", "b"]
