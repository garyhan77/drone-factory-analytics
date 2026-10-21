-- severity: error
-- category: guard
-- description: a lot recorded against a drone that has no matching shipment in receiving
SELECT DISTINCT l.lot_id AS record_key
FROM raw_drone_part_lots l
WHERE NOT EXISTS (SELECT 1 FROM raw_receiving r WHERE r.lot_id = l.lot_id)
