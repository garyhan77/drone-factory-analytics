-- severity: error
-- category: planted
-- description: work order that finished before it started
SELECT wo_id AS record_key
FROM raw_work_orders
WHERE end_ts IS NOT NULL AND end_ts < start_ts
