-- severity: error
-- category: reconciliation
-- description: for a part, what was received does not equal what went into drones plus what is in stock at the latest snapshot (a second way to see receiving quantities that do not match the physical stock)
WITH received AS (
    SELECT part_id, SUM(qty_received) AS qty
    FROM raw_receiving
    WHERE received_date IS NOT NULL
    GROUP BY part_id
),
installed AS (
    SELECT l.part_id, COUNT(*) * b.qty_per_unit AS qty
    FROM raw_drone_part_lots l
    JOIN raw_bom b ON b.part_id = l.part_id AND b.station_code = l.station_code
    GROUP BY l.part_id, b.qty_per_unit
),
in_stock AS (
    SELECT part_id, SUM(on_hand) AS qty
    FROM raw_inventory_snapshots
    WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM raw_inventory_snapshots)
    GROUP BY part_id
)
SELECT p.part_id AS record_key
FROM raw_parts p
LEFT JOIN received r ON r.part_id = p.part_id
LEFT JOIN installed i ON i.part_id = p.part_id
LEFT JOIN in_stock s ON s.part_id = p.part_id
WHERE COALESCE(r.qty, 0) - COALESCE(i.qty, 0) - COALESCE(s.qty, 0) <> 0
