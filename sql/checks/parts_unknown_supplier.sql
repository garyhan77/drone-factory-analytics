-- severity: error
-- category: sanity
-- description: part assigned to a supplier that is not in the supplier master
SELECT p.part_id AS record_key
FROM raw_parts p
WHERE NOT EXISTS (SELECT 1 FROM raw_suppliers s WHERE s.supplier_id = p.supplier_id)
