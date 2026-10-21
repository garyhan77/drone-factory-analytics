-- severity: error
-- category: sanity
-- description: shipment for a part number that is not in the parts master
SELECT r.shipment_id AS record_key
FROM raw_receiving r
WHERE NOT EXISTS (SELECT 1 FROM raw_parts p WHERE p.part_id = r.part_id)
