import os

import pytest
from dotenv import load_dotenv

from factory import config as cfg
from factory.build import build
from factory.db import ROOT, TABLES, connect


@pytest.fixture(scope="module")
def built():
    load_dotenv(ROOT / ".env")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    if not url.rstrip("/").rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail(f"TEST_DATABASE_URL must point at a database ending in _test, got: {url}")
    data = build(url=url, write_files=False)
    with connect(url) as conn:
        yield data, conn


def test_every_table_is_loaded_with_the_generated_row_count(built):
    data, conn = built
    for name in TABLES:
        assert conn.execute(f"SELECT COUNT(*) FROM raw_{name}").fetchone()[0] == len(data.tables[name]), name


def test_the_planted_errors_are_really_in_the_database(built):
    data, conn = built
    key = data.answer_key
    count = lambda sql, *args: conn.execute(sql, args).fetchone()[0]
    assert count("SELECT COUNT(*) FROM raw_inventory_snapshots WHERE on_hand < 0") == len(key["negative_inventory"])
    assert count("SELECT COUNT(*) FROM raw_work_orders WHERE end_ts < start_ts") == len(key["end_before_start"])
    assert count("SELECT COUNT(*) FROM raw_receiving WHERE qty_received > qty_expected") == len(key["over_receipt"])
    assert count("SELECT COUNT(*) FROM raw_work_orders WHERE wo_id = ANY(%s)", key["duplicate_work_orders"]) == len(key["duplicate_work_orders"])
    assert count("SELECT COUNT(*) FROM raw_inspections WHERE result = 'FAIL' AND (defect_code IS NULL OR TRIM(defect_code) = '')") == len(key["missing_defect_code"])
    assert count("""SELECT COUNT(*) FROM raw_inspections i
                    WHERE NOT EXISTS (SELECT 1 FROM raw_work_orders w WHERE w.serial_number = i.serial_number)""") == len(key["orphan_inspections"])


def test_nulls_survive_the_load(built):
    _, conn = built
    assert conn.execute("SELECT COUNT(*) FROM raw_work_orders WHERE status = 'IN_PROGRESS' AND end_ts IS NULL").fetchone()[0] > 0
    assert conn.execute("SELECT COUNT(*) FROM raw_receiving WHERE received_date IS NULL AND qty_received IS NULL").fetchone()[0] > 0
    assert conn.execute("SELECT COUNT(*) FROM raw_finished_goods WHERE shipped_ts IS NULL").fetchone()[0] > 0
