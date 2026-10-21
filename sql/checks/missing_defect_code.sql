-- severity: error
-- category: planted
-- description: failed inspection with no usable defect code (NULL, empty or only spaces)
SELECT inspection_id AS record_key
FROM raw_inspections
WHERE result = 'FAIL' AND (defect_code IS NULL OR TRIM(defect_code) = '')
