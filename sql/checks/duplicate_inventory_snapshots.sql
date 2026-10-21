-- severity: error
-- category: sanity
-- description: more than one snapshot for the same part, location and day
SELECT snapshot_date::text || '|' || part_id || '|' || location AS record_key
FROM raw_inventory_snapshots
GROUP BY snapshot_date, part_id, location
HAVING COUNT(*) > 1
