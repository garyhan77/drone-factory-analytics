-- severity: error
-- category: sanity
-- description: work order at a station code that is not in the station list
SELECT w.wo_id AS record_key
FROM raw_work_orders w
WHERE NOT EXISTS (SELECT 1 FROM raw_stations s WHERE s.station_code = w.station_code)
