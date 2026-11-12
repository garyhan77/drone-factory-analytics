-- One row per shipment that has arrived, with how late it was and whether it was short.
-- The pre-launch shipments that make up the starting stock are left out.
--   days_late = days after the expected date (0 when on time or early)
--   short     = fewer units arrived than were expected
--   emergency = bought from the spot-buy distributor after a shortage (lot IDs start with SUB)
CREATE OR REPLACE VIEW v_deliveries AS
SELECT
    r.shipment_id,
    r.lot_id,
    r.part_id,
    p.part_name,
    r.supplier_id,
    su.supplier_name,
    r.expected_date,
    r.received_date,
    GREATEST(r.received_date - r.expected_date, 0) AS days_late,
    r.qty_expected,
    r.qty_received,
    (r.qty_received < r.qty_expected) AS short,
    (r.lot_id LIKE 'SUB-%') AS emergency
FROM raw_receiving r
JOIN raw_parts p ON p.part_id = r.part_id
JOIN raw_suppliers su ON su.supplier_id = r.supplier_id
WHERE r.received_date IS NOT NULL AND r.received_date >= (SELECT launch_date FROM v_calendar);
