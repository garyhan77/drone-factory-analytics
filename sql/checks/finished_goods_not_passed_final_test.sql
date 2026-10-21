-- severity: error
-- category: guard
-- description: drone in finished goods with no passing Final Test inspection
SELECT f.serial_number AS record_key
FROM raw_finished_goods f
WHERE NOT EXISTS (
    SELECT 1 FROM raw_inspections i
    WHERE i.serial_number = f.serial_number AND i.station_code = 'FNT' AND i.result = 'PASS'
)
