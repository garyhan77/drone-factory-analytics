-- severity: error
-- category: sanity
-- description: shipment missing its id, lot, supplier, part, dates or expected quantity
SELECT COALESCE(shipment_id, '(no id)') || '|' || COALESCE(part_id, '(no part)') AS record_key
FROM raw_receiving
WHERE shipment_id IS NULL OR lot_id IS NULL OR supplier_id IS NULL OR part_id IS NULL
   OR order_date IS NULL OR expected_date IS NULL OR qty_expected IS NULL
