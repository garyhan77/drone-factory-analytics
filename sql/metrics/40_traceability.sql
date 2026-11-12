-- Failure rate by lot: for each lot, the drones it went into and how many of them failed inspection at the
-- station where it was installed. A drone counts as failed if it failed its first inspection, even if it passed after rework.
CREATE OR REPLACE VIEW v_lot_quality AS
WITH per_drone AS (
    SELECT DISTINCT l.lot_id, l.part_id, l.station_code, l.serial_number, (i.result = 'FAIL') AS failed
    FROM raw_drone_part_lots l
    JOIN raw_inspections i
      ON i.serial_number = l.serial_number AND i.station_code = l.station_code AND i.attempt = 1
)
SELECT
    d.lot_id,
    d.part_id,
    d.station_code,
    r.supplier_id,
    su.supplier_name,
    COUNT(*) AS drones_inspected,
    COUNT(*) FILTER (WHERE d.failed) AS fails,
    ROUND(AVG(d.failed::int)::numeric, 4) AS fail_rate
FROM per_drone d
LEFT JOIN raw_receiving r ON r.lot_id = d.lot_id
LEFT JOIN raw_suppliers su ON su.supplier_id = r.supplier_id
GROUP BY d.lot_id, d.part_id, d.station_code, r.supplier_id, su.supplier_name;

-- Recall scope: for each lot, every drone that contains it and where those drones are now.
CREATE OR REPLACE VIEW v_recall_scope AS
SELECT
    l.lot_id,
    l.part_id,
    l.station_code,
    COUNT(DISTINCT l.serial_number) AS drones_containing_lot,
    COUNT(DISTINCT l.serial_number) FILTER (WHERE f.shipped_ts IS NOT NULL) AS already_shipped,
    COUNT(DISTINCT l.serial_number) FILTER (WHERE f.serial_number IS NOT NULL AND f.shipped_ts IS NULL) AS packed_not_shipped,
    COUNT(DISTINCT l.serial_number) FILTER (WHERE f.serial_number IS NULL) AS still_in_the_line,
    MIN(w.start_ts)::date AS first_installed,
    MAX(w.start_ts)::date AS last_installed
FROM raw_drone_part_lots l
JOIN raw_work_orders w ON w.serial_number = l.serial_number AND w.station_code = l.station_code
LEFT JOIN raw_finished_goods f ON f.serial_number = l.serial_number
GROUP BY l.lot_id, l.part_id, l.station_code;
