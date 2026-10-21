-- severity: error
-- category: sanity
-- description: inventory snapshot at a location other than WAREHOUSE or LINE_SIDE
SELECT snapshot_date::text || '|' || part_id || '|' || COALESCE(location, '(null)') AS record_key
FROM raw_inventory_snapshots
WHERE location IS DISTINCT FROM 'WAREHOUSE' AND location IS DISTINCT FROM 'LINE_SIDE'
