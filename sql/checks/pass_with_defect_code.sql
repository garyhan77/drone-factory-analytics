-- severity: error
-- category: sanity
-- description: passing inspection that carries a defect code
SELECT inspection_id AS record_key
FROM raw_inspections
WHERE result = 'PASS' AND defect_code IS NOT NULL AND TRIM(defect_code) <> ''
