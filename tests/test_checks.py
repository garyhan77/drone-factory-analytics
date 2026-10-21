"""The data quality checks: each against a hand-made bad row, the scorer on hand-made inputs, then the full data."""
import os
from dataclasses import replace

import pandas as pd
import pytest
from dotenv import load_dotenv

from factory import config as cfg
from factory.build import build
from factory.checks import Check, discover_checks, run_all, run_check, score
from factory.db import ROOT, connect

CHECKS = {c.name: c for c in discover_checks()}


# ---------------------------------------------------------------------------- the registry

def test_every_check_file_has_valid_headers_and_the_expected_mix():
    by_category = {}
    for c in CHECKS.values():
        by_category.setdefault(c.category, []).append(c.name)
    assert {k: len(v) for k, v in by_category.items()} == {"planted": 6, "guard": 5, "sanity": 13, "operational": 1}
    assert set(by_category["planted"]) == set(cfg.PLANTED_COUNTS)
    assert set(by_category["guard"]) == set(cfg.GUARD_CHECKS)
    assert CHECKS["overdue_open_shipments"].severity == "warn"
    assert all(c.severity == "error" for c in CHECKS.values() if c.category != "operational")


def test_bad_headers_are_rejected(tmp_path):
    (tmp_path / "a.sql").write_text("-- severity: error\n-- category: planted\nSELECT 1\n")
    with pytest.raises(ValueError, match="description"):
        discover_checks(tmp_path)
    (tmp_path / "a.sql").write_text("-- severity: loud\n-- category: planted\n-- description: x\nSELECT 1\n")
    with pytest.raises(ValueError, match="severity"):
        discover_checks(tmp_path)
    (tmp_path / "a.sql").write_text("-- severity: error\n-- category: mystery\n-- description: x\nSELECT 1\n")
    with pytest.raises(ValueError, match="category"):
        discover_checks(tmp_path)


def test_every_check_runs_on_empty_tables_and_flags_nothing(conn):
    for check in CHECKS.values():
        assert run_check(conn, check) == [], check.name


# ---------------------------------------------------------------------------- the scorer, by hand

def fake(name, category):
    return Check(name, "error", category, "x", "")


def test_scoring_counts_caught_missed_and_false_positives():
    checks = [fake("p", "planted"), fake("g", "guard"), fake("o", "operational")]
    flagged = {"p": ["a", "b", "z"], "g": ["q"], "o": ["w"]}
    out = score(checks, flagged, {"p": ["a", "b", "c"]}).set_index("check_name")
    assert out.loc["p", ["flagged_rows", "planted_rows", "caught", "missed", "false_positives"]].tolist() == [3, 3, 2, 1, 1]
    assert out.loc["g", ["planted_rows", "caught", "missed", "false_positives"]].tolist() == [0, 0, 0, 1]
    assert out.loc["o", "flagged_rows"] == 1 and out.loc[["o"], ["planted_rows", "caught", "missed", "false_positives"]].isna().all().all()


def test_a_perfect_check_scores_zero_missed_and_zero_false_positives():
    out = score([fake("p", "planted")], {"p": ["b", "a"]}, {"p": ["a", "b"]}).iloc[0]
    assert (out["caught"], out["missed"], out["false_positives"]) == (2, 0, 0)


# ---------------------------------------------------------------------------- one hand-made bad row per check

CLEAN_ROWS = """
INSERT INTO raw_stations VALUES (1, 'AAA', 'Alpha'), (2, 'FNT', 'Final Test');
INSERT INTO raw_suppliers VALUES ('SUP-01', 'Acme');
INSERT INTO raw_parts VALUES ('P1', 'Widget', 'SUP-01', 1.0, 5, 10);
INSERT INTO raw_bom VALUES ('AAA', 'P1', 2);
INSERT INTO raw_receiving VALUES ('S1', 'LOT-1', 'SUP-01', 'P1', '2026-02-01', '2026-02-11', '2026-02-11', 100, 100);
INSERT INTO raw_inventory_snapshots VALUES ('2026-03-02', 'P1', 'WAREHOUSE', 10), ('2026-03-02', 'P1', 'LINE_SIDE', 5);
INSERT INTO raw_work_orders VALUES
  ('WO1', 'DF-000001', 'AAA', '2026-03-02 08:00', '2026-03-02 11:00', 'COMPLETE'),
  ('WO2', 'DF-000001', 'FNT', '2026-03-02 12:00', '2026-03-02 15:00', 'COMPLETE'),
  ('WO3', 'DF-000002', 'AAA', '2026-03-02 09:00', NULL, 'IN_PROGRESS');
INSERT INTO raw_inspections VALUES
  ('I1', 'DF-000001', 'AAA', 1, '2026-03-02 11:00', 'PASS', NULL),
  ('I2', 'DF-000001', 'FNT', 1, '2026-03-02 14:00', 'FAIL', 'FNT-X'),
  ('I3', 'DF-000001', 'FNT', 2, '2026-03-02 15:00', 'PASS', NULL);
INSERT INTO raw_drone_part_lots VALUES ('DF-000001', 'AAA', 'P1', 'LOT-1'), ('DF-000002', 'AAA', 'P1', 'LOT-1');
INSERT INTO raw_finished_goods VALUES ('DF-000001', '2026-03-02 15:00', '2026-03-02 16:00', NULL);
"""

# name -> (statements that add one problem, the record keys each check should then flag)
# Every check is compared, so a case also proves no other check fires unless it is listed.
CASES = {
    "negative_inventory": ("INSERT INTO raw_inventory_snapshots VALUES ('2026-03-03', 'P1', 'WAREHOUSE', -4)",
                           {"negative_inventory": ["2026-03-03|P1|WAREHOUSE"]}),
    "missing_defect_code_null": ("INSERT INTO raw_inspections VALUES ('I9', 'DF-000001', 'AAA', 1, '2026-03-02 12:00', 'FAIL', NULL)",
                                 {"missing_defect_code": ["I9"]}),
    "missing_defect_code_empty": ("INSERT INTO raw_inspections VALUES ('I9', 'DF-000001', 'AAA', 1, '2026-03-02 12:00', 'FAIL', '')",
                                  {"missing_defect_code": ["I9"]}),
    "missing_defect_code_spaces": ("INSERT INTO raw_inspections VALUES ('I9', 'DF-000001', 'AAA', 1, '2026-03-02 12:00', 'FAIL', '   ')",
                                   {"missing_defect_code": ["I9"]}),
    "orphan_unknown_drone": ("INSERT INTO raw_inspections VALUES ('I9', 'DF-999999', 'AAA', 1, '2026-03-02 12:00', 'PASS', NULL)",
                             {"orphan_inspections": ["I9"]}),
    "orphan_wrong_station": ("INSERT INTO raw_inspections VALUES ('I9', 'DF-000002', 'FNT', 1, '2026-03-02 12:00', 'PASS', NULL)",
                             {"orphan_inspections": ["I9"]}),
    "over_receipt": ("INSERT INTO raw_receiving VALUES ('S2', 'LOT-2', 'SUP-01', 'P1', '2026-02-01', '2026-02-11', '2026-02-12', 100, 130)",
                     {"over_receipt": ["S2"]}),
    "duplicate_work_order": ("INSERT INTO raw_work_orders VALUES ('WO9', 'DF-000001', 'AAA', '2026-03-02 08:00', '2026-03-02 11:00', 'COMPLETE')",
                             {"duplicate_work_orders": ["WO9"]}),  # the copy, not the original WO1
    "two_copies_of_one_work_order": ("INSERT INTO raw_work_orders VALUES ('WO8', 'DF-000001', 'AAA', '2026-03-02 08:00', '2026-03-02 11:00', 'COMPLETE'), "
                                     "('WO9', 'DF-000001', 'AAA', '2026-03-02 08:00', '2026-03-02 11:00', 'COMPLETE')",
                                     {"duplicate_work_orders": ["WO8", "WO9"]}),
    "same_drone_and_station_at_a_different_time_is_not_a_duplicate": (
        "INSERT INTO raw_work_orders VALUES ('WO9', 'DF-000001', 'AAA', '2026-03-03 08:00', '2026-03-03 11:00', 'COMPLETE')", {}),
    "end_before_start": ("INSERT INTO raw_work_orders VALUES ('WO9', 'DF-000003', 'AAA', '2026-03-02 10:00', '2026-03-02 09:00', 'COMPLETE')",
                         {"end_before_start": ["WO9"]}),
    "status_complete_without_end": ("INSERT INTO raw_work_orders VALUES ('WO9', 'DF-000003', 'AAA', '2026-03-02 10:00', NULL, 'COMPLETE')",
                                    {"status_timestamp_mismatch": ["WO9"]}),
    "status_in_progress_with_end": ("INSERT INTO raw_work_orders VALUES ('WO9', 'DF-000003', 'AAA', '2026-03-02 10:00', '2026-03-02 12:00', 'IN_PROGRESS')",
                                    {"status_timestamp_mismatch": ["WO9"]}),
    "traceability_lot_not_in_receiving": ("INSERT INTO raw_drone_part_lots VALUES ('DF-000001', 'FNT', 'P1', 'LOT-X')",
                                          {"traceability_lot_not_in_receiving": ["LOT-X"]}),
    "traceability_serial_not_in_work_orders": ("INSERT INTO raw_drone_part_lots VALUES ('DF-777777', 'AAA', 'P1', 'LOT-1')",
                                               {"traceability_serial_not_in_work_orders": ["DF-777777"]}),
    "finished_goods_without_a_passing_test": ("INSERT INTO raw_finished_goods VALUES ('DF-000002', '2026-03-02 10:00', '2026-03-02 11:00', NULL)",
                                              {"finished_goods_not_passed_final_test": ["DF-000002"]}),
    "finished_goods_packed_before_test": ("UPDATE raw_finished_goods SET packed_ts = '2026-03-02 14:00'",
                                          {"finished_goods_timestamps_out_of_order": ["DF-000001"]}),
    "finished_goods_shipped_before_packed": ("UPDATE raw_finished_goods SET shipped_ts = '2026-03-02 15:30'",
                                             {"finished_goods_timestamps_out_of_order": ["DF-000001"]}),
    "finished_goods_shipped_but_never_packed": ("UPDATE raw_finished_goods SET packed_ts = NULL, shipped_ts = '2026-03-03 16:00'",
                                                {"finished_goods_timestamps_out_of_order": ["DF-000001"]}),
    "receiving_unknown_part": ("INSERT INTO raw_receiving VALUES ('S2', 'LOT-2', 'SUP-01', 'P404', '2026-02-01', '2026-02-11', '2026-02-11', 10, 10)",
                               {"receiving_unknown_part": ["S2"]}),
    "bom_unknown_part": ("INSERT INTO raw_bom VALUES ('AAA', 'P404', 1)", {"bom_unknown_part": ["AAA|P404"]}),
    "receiving_unknown_supplier": ("INSERT INTO raw_receiving VALUES ('S2', 'LOT-2', 'SUP-99', 'P1', '2026-02-01', '2026-02-11', '2026-02-11', 10, 10)",
                                   {"receiving_unknown_supplier": ["S2"]}),
    "parts_unknown_supplier": ("INSERT INTO raw_parts VALUES ('P2', 'Gadget', 'SUP-99', 1.0, 5, 10)", {"parts_unknown_supplier": ["P2"]}),
    "work_orders_unknown_station": ("INSERT INTO raw_work_orders VALUES ('WO9', 'DF-000001', 'ZZZ', '2026-03-02 13:00', '2026-03-02 14:00', 'COMPLETE')",
                                    {"work_orders_unknown_station": ["WO9"]}),
    "inspections_unknown_station": ("INSERT INTO raw_inspections VALUES ('I9', 'DF-000001', 'ZZZ', 1, '2026-03-02 12:00', 'PASS', NULL)",
                                    # also an orphan: the drone has no work order at station ZZZ
                                    {"inspections_unknown_station": ["I9"], "orphan_inspections": ["I9"]}),
    "invalid_work_order_status": ("INSERT INTO raw_work_orders VALUES ('WO9', 'DF-000003', 'AAA', '2026-03-02 10:00', '2026-03-02 12:00', 'DONE')",
                                  {"invalid_work_order_status": ["WO9"]}),
    "invalid_inspection_result": ("INSERT INTO raw_inspections VALUES ('I9', 'DF-000001', 'AAA', 1, '2026-03-02 12:00', 'MAYBE', NULL)",
                                  {"invalid_inspection_values": ["I9"]}),
    "invalid_inspection_attempt": ("INSERT INTO raw_inspections VALUES ('I9', 'DF-000001', 'AAA', 3, '2026-03-02 12:00', 'PASS', NULL)",
                                   {"invalid_inspection_values": ["I9"]}),
    "invalid_inventory_location": ("INSERT INTO raw_inventory_snapshots VALUES ('2026-03-03', 'P1', 'YARD', 4)",
                                   {"invalid_inventory_location": ["2026-03-03|P1|YARD"]}),
    "pass_with_defect_code": ("INSERT INTO raw_inspections VALUES ('I9', 'DF-000001', 'AAA', 1, '2026-03-02 12:00', 'PASS', 'AAA-X')",
                              {"pass_with_defect_code": ["I9"]}),
    "duplicate_inventory_snapshots": ("INSERT INTO raw_inventory_snapshots VALUES ('2026-03-02', 'P1', 'WAREHOUSE', 10)",
                                      {"duplicate_inventory_snapshots": ["2026-03-02|P1|WAREHOUSE"]}),
    "work_orders_missing_required": ("INSERT INTO raw_work_orders VALUES ('WO9', NULL, 'AAA', '2026-03-02 10:00', NULL, 'IN_PROGRESS')",
                                     {"work_orders_missing_required": ["WO9|(no serial)"]}),
    "receiving_missing_required": ("INSERT INTO raw_receiving VALUES ('S2', NULL, 'SUP-01', 'P1', '2026-02-01', '2026-02-11', '2026-02-11', 10, 10)",
                                   {"receiving_missing_required": ["S2|P1"]}),
    "overdue_open_shipment": ("INSERT INTO raw_receiving VALUES ('S2', 'LOT-2', 'SUP-01', 'P1', '2026-02-01', '2026-02-20', NULL, 10, NULL)",
                              {"overdue_open_shipments": ["S2"]}),
    "recent_open_shipment_is_not_overdue": ("INSERT INTO raw_receiving VALUES ('S2', 'LOT-2', 'SUP-01', 'P1', '2026-02-20', '2026-03-01', NULL, 10, NULL)", {}),
}


@pytest.fixture
def tiny(conn):
    conn.execute(CLEAN_ROWS)
    conn.commit()
    return conn


def flagged_by_check(conn):
    return {name: run_check(conn, check) for name, check in CHECKS.items() if run_check(conn, check)}


def test_the_clean_hand_made_database_flags_nothing(tiny):
    assert flagged_by_check(tiny) == {}


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_bad_row_is_flagged_by_the_right_check_and_by_nothing_else(tiny, case):
    statement, expected = CASES[case]
    tiny.execute(statement)
    tiny.commit()
    assert flagged_by_check(tiny) == expected


def test_every_check_has_at_least_one_bad_row_case():
    covered = {name for _, expected in CASES.values() for name in expected}
    assert covered == set(CHECKS)


# ---------------------------------------------------------------------------- the generated dataset

@pytest.fixture(scope="module")
def test_url():
    load_dotenv(ROOT / ".env")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    if not url.rstrip("/").rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail(f"TEST_DATABASE_URL must point at a database ending in _test, got: {url}")
    return url


def test_every_planted_error_is_caught_with_no_false_positives(test_url):
    data = build(url=test_url, write_files=False)
    r = data.results.set_index("check_name")
    for name, count in cfg.PLANTED_COUNTS.items():
        assert (r.loc[name, "planted_rows"], r.loc[name, "caught"], r.loc[name, "missed"], r.loc[name, "false_positives"]) == (count, count, 0, 0), name
    scored = data.results[data.results["category"].isin(["planted", "guard", "sanity"])]
    assert scored["missed"].sum() == 0 and scored["false_positives"].sum() == 0
    assert (data.results.loc[data.results["category"].isin(["guard", "sanity"]), "flagged_rows"] == 0).all()


def test_results_and_the_answer_key_are_stored_in_the_database(test_url):
    data = build(url=test_url, write_files=False)
    with connect(test_url) as conn:
        assert conn.execute("SELECT COUNT(*) FROM dq_results").fetchone()[0] == 25
        assert conn.execute("SELECT COUNT(*) FROM dq_answer_key").fetchone()[0] == sum(cfg.PLANTED_COUNTS.values())
        assert conn.execute("SELECT SUM(caught) FROM dq_results WHERE category = 'planted'").fetchone()[0] == sum(cfg.PLANTED_COUNTS.values())
        assert conn.execute("SELECT COUNT(*) FROM dq_flagged").fetchone()[0] == sum(len(v) for v in data.answer_key.values())


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_the_checks_also_score_perfectly_on_other_seeds(test_url, seed):
    data = build(url=test_url, seed=seed, write_files=False)
    scored = data.results[data.results["category"].isin(["planted", "guard", "sanity"])]
    assert scored["missed"].sum() == 0 and scored["false_positives"].sum() == 0
    assert data.results.loc[data.results["category"] == "planted", "caught"].sum() == sum(len(data.answer_key[n]) for n in cfg.PLANTED_COUNTS)
