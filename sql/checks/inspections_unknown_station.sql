-- severity: error
-- category: sanity
-- description: inspection at a station code that is not in the station list
SELECT i.inspection_id AS record_key
FROM raw_inspections i
WHERE NOT EXISTS (SELECT 1 FROM raw_stations s WHERE s.station_code = i.station_code)
