-- severity: error
-- category: sanity
-- description: work order missing its id, drone, station or start time
SELECT COALESCE(wo_id, '(no id)') || '|' || COALESCE(serial_number, '(no serial)') AS record_key
FROM raw_work_orders
WHERE wo_id IS NULL OR serial_number IS NULL OR station_code IS NULL OR start_ts IS NULL
