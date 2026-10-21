-- Failure rate by lot: for each lot, the drones it went into and how many failed their first inspection at the
-- station where it was installed, against that station's overall failure rate (lift = lot rate / station rate).
CREATE OR REPLACE VIEW v_lot_quality AS
WITH per_drone AS (
    SELECT DISTINCT l.lot_id, l.part_id, l.station_code, l.serial_number, (i.result = 'FAIL') AS failed
    FROM clean_drone_part_lots l
    JOIN clean_inspections i
      ON i.serial_number = l.serial_number AND i.station_code = l.station_code AND i.attempt = 1
),
station_rate AS (
    SELECT station_code, AVG(failed::int) AS station_fail_rate
    FROM (SELECT DISTINCT serial_number, station_code, failed FROM per_drone) d
    GROUP BY station_code
)
SELECT
    d.lot_id,
    d.part_id,
    d.station_code,
    r.supplier_id,
    su.supplier_name,
    COUNT(*) AS drones_inspected,
    COUNT(*) FILTER (WHERE d.failed) AS fails,
    ROUND(AVG(d.failed::int)::numeric, 4) AS fail_rate,
    ROUND(sr.station_fail_rate::numeric, 4) AS station_fail_rate,
    ROUND((AVG(d.failed::int) / NULLIF(sr.station_fail_rate, 0))::numeric, 2) AS lift
FROM per_drone d
JOIN station_rate sr USING (station_code)
LEFT JOIN clean_receiving r ON r.lot_id = d.lot_id
LEFT JOIN clean_suppliers su ON su.supplier_id = r.supplier_id
GROUP BY d.lot_id, d.part_id, d.station_code, r.supplier_id, su.supplier_name, sr.station_fail_rate;

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
FROM clean_drone_part_lots l
JOIN clean_work_orders w ON w.serial_number = l.serial_number AND w.station_code = l.station_code
LEFT JOIN clean_finished_goods f ON f.serial_number = l.serial_number
GROUP BY l.lot_id, l.part_id, l.station_code;
