-- severity: error
-- category: planted
-- description: inspection for a drone that has no work order at that station
SELECT i.inspection_id AS record_key
FROM raw_inspections i
WHERE NOT EXISTS (
    SELECT 1 FROM raw_work_orders w
    WHERE w.serial_number = i.serial_number AND w.station_code = i.station_code
)
