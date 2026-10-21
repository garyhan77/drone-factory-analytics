-- severity: error
-- category: planted
-- description: inventory snapshot with a negative on-hand quantity
SELECT snapshot_date::text || '|' || part_id || '|' || location AS record_key
FROM raw_inventory_snapshots
WHERE on_hand < 0
