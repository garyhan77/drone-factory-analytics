-- severity: error
-- category: sanity
-- description: inspection result other than PASS or FAIL, or attempt other than 1 or 2
SELECT inspection_id AS record_key
FROM raw_inspections
WHERE (result IS DISTINCT FROM 'PASS' AND result IS DISTINCT FROM 'FAIL')
   OR attempt IS NULL OR attempt NOT IN (1, 2)
