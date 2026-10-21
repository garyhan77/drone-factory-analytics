-- severity: error
-- category: sanity
-- description: work order status other than COMPLETE or IN_PROGRESS
SELECT COALESCE(wo_id, '(no id)') AS record_key
FROM raw_work_orders
WHERE status IS DISTINCT FROM 'COMPLETE' AND status IS DISTINCT FROM 'IN_PROGRESS'
