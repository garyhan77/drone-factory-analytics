-- severity: error
-- category: sanity
-- description: shipment from a supplier that is not in the supplier master
SELECT r.shipment_id AS record_key
FROM raw_receiving r
WHERE NOT EXISTS (SELECT 1 FROM raw_suppliers s WHERE s.supplier_id = r.supplier_id)
