-- severity: error
-- category: sanity
-- description: bill of materials line for a part number that is not in the parts master
SELECT b.station_code || '|' || b.part_id AS record_key
FROM raw_bom b
WHERE NOT EXISTS (SELECT 1 FROM raw_parts p WHERE p.part_id = b.part_id)
