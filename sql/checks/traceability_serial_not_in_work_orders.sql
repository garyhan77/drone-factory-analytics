-- severity: error
-- category: guard
-- description: traceability record for a drone that has no work order
SELECT DISTINCT l.serial_number AS record_key
FROM raw_drone_part_lots l
WHERE NOT EXISTS (SELECT 1 FROM raw_work_orders w WHERE w.serial_number = l.serial_number)
