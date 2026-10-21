-- Lead time and dwell for every drone that has shipped.
--   lead time = first station start to shipped
--   dwell     = passing Final Test to shipped
-- Only shipped drones can be measured, so the longest waits (drones still in the line) are missing from recent
-- weeks. See v_wip_age for those.
CREATE OR REPLACE VIEW v_drone_delivery AS
WITH first_start AS (
    SELECT serial_number, MIN(start_ts) AS first_start
    FROM clean_work_orders
    WHERE station_code = (SELECT station_code FROM clean_stations ORDER BY station_seq LIMIT 1)
    GROUP BY serial_number
)
SELECT
    f.serial_number,
    fs.first_start,
    f.test_passed_ts,
    f.packed_ts,
    f.shipped_ts,
    EXTRACT(EPOCH FROM (f.shipped_ts - fs.first_start)) / 86400.0 AS lead_days,
    EXTRACT(EPOCH FROM (f.shipped_ts - f.test_passed_ts)) / 86400.0 AS dwell_days
FROM clean_finished_goods f
JOIN first_start fs USING (serial_number)
WHERE f.shipped_ts IS NOT NULL;

CREATE OR REPLACE VIEW v_lead_time_weekly AS
SELECT
    date_trunc('week', shipped_ts)::date AS week_start,
    COUNT(*) AS drones_shipped,
    ROUND(AVG(lead_days)::numeric, 1) AS avg_lead_days,
    ROUND(AVG(dwell_days)::numeric, 1) AS avg_dwell_days
FROM v_drone_delivery
GROUP BY 1;

-- Drones that have started but not shipped, how long they have been in the line, and where they are now:
--   In <station>          the latest job has started and has not finished
--   Waiting for <station> the latest job is done and the next station has not started it (queued)
--   Awaiting shipment     passed Final Test, packed or being packed, not yet shipped
CREATE OR REPLACE VIEW v_wip_age AS
WITH latest_job AS (
    SELECT DISTINCT ON (w.serial_number)
           w.serial_number, w.station_code, s.station_name, s.station_seq, w.start_ts, w.end_ts, w.end_unknown
    FROM clean_work_orders w
    JOIN clean_stations s USING (station_code)
    ORDER BY w.serial_number, s.station_seq DESC
),
first_start AS (
    SELECT serial_number, MIN(start_ts) AS first_start FROM clean_work_orders GROUP BY serial_number
)
SELECT
    j.serial_number,
    fs.first_start,
    ROUND((EXTRACT(EPOCH FROM ((SELECT as_of_ts FROM v_calendar) - fs.first_start)) / 86400.0)::numeric, 1) AS age_days,
    CASE
        WHEN f.serial_number IS NOT NULL THEN 'Awaiting shipment'
        WHEN j.end_ts IS NULL AND NOT j.end_unknown THEN 'In ' || j.station_name  -- started, not finished
        ELSE 'Waiting for ' || COALESCE(nxt.station_name, 'shipping')
    END AS stage
FROM latest_job j
JOIN first_start fs USING (serial_number)
LEFT JOIN clean_stations nxt ON nxt.station_seq = j.station_seq + 1
LEFT JOIN clean_finished_goods f ON f.serial_number = j.serial_number
WHERE f.shipped_ts IS NULL;

CREATE OR REPLACE VIEW v_wip_by_stage AS
SELECT
    stage,
    COUNT(*) AS drones,
    ROUND(AVG(age_days), 1) AS avg_age_days,
    MAX(age_days) AS max_age_days
FROM v_wip_age
GROUP BY stage;
