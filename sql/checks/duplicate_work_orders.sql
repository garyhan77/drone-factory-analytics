-- severity: error
-- category: planted
-- description: work order repeated for the same drone, station and start time (a re-keyed copy with a new wo_id); every copy after the first is flagged
SELECT wo_id AS record_key
FROM (
    SELECT wo_id,
           ROW_NUMBER() OVER (PARTITION BY serial_number, station_code, start_ts ORDER BY wo_id) AS copy_number
    FROM raw_work_orders
) numbered
WHERE copy_number > 1
