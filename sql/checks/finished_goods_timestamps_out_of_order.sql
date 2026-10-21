-- severity: error
-- category: guard
-- description: finished goods times out of order (test passed, then packed, then shipped), or shipped without being packed
SELECT serial_number AS record_key
FROM raw_finished_goods
WHERE packed_ts < test_passed_ts
   OR shipped_ts < packed_ts
   OR (shipped_ts IS NOT NULL AND packed_ts IS NULL)
