-- severity: error
-- category: guard
-- description: work order status disagrees with its end time (COMPLETE with no end, or IN_PROGRESS with one)
SELECT wo_id AS record_key
FROM raw_work_orders
WHERE (status = 'COMPLETE' AND end_ts IS NULL)
   OR (status = 'IN_PROGRESS' AND end_ts IS NOT NULL)
