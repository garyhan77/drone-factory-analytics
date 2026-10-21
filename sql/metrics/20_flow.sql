-- One row per work order: how long it took, and how long the drone waited after the previous station finished.
-- Wait is elapsed time, so it includes off-shift hours and weekends. It is blank where either end time is unknown.
CREATE OR REPLACE VIEW v_work_order_flow AS
SELECT
    w.wo_id,
    w.serial_number,
    w.station_code,
    s.station_name,
    s.station_seq,
    w.start_ts,
    w.end_ts,
    EXTRACT(EPOCH FROM (w.end_ts - w.start_ts)) / 3600.0 AS cycle_hours,
    EXTRACT(EPOCH FROM (
        w.start_ts - LAG(w.end_ts) OVER (PARTITION BY w.serial_number ORDER BY s.station_seq)
    )) / 3600.0 AS queue_wait_hours
FROM clean_work_orders w
JOIN clean_stations s USING (station_code);

CREATE OR REPLACE VIEW v_station_summary AS
SELECT
    station_seq,
    station_code,
    station_name,
    COUNT(cycle_hours) AS completed_orders,
    ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY cycle_hours))::numeric, 2) AS median_cycle_hours,
    ROUND((percentile_cont(0.9) WITHIN GROUP (ORDER BY cycle_hours))::numeric, 2) AS p90_cycle_hours,
    ROUND(AVG(queue_wait_hours)::numeric, 2) AS avg_wait_hours,
    ROUND((percentile_cont(0.9) WITHIN GROUP (ORDER BY queue_wait_hours))::numeric, 2) AS p90_wait_hours
FROM v_work_order_flow
GROUP BY station_seq, station_code, station_name;

CREATE OR REPLACE VIEW v_queue_wait_weekly AS
SELECT
    date_trunc('week', start_ts)::date AS week_start,
    station_seq,
    station_code,
    station_name,
    ROUND(AVG(queue_wait_hours)::numeric, 2) AS avg_wait_hours
FROM v_work_order_flow
WHERE queue_wait_hours IS NOT NULL
GROUP BY 1, 2, 3, 4;

-- Drones entering the first station and leaving the last one, by week.
CREATE OR REPLACE VIEW v_weekly_output AS
SELECT
    week_start,
    SUM(started)::int AS units_started,
    SUM(completed)::int AS units_completed
FROM (
    SELECT date_trunc('week', start_ts)::date AS week_start, 1 AS started, 0 AS completed
    FROM clean_work_orders
    WHERE station_code = (SELECT station_code FROM clean_stations ORDER BY station_seq LIMIT 1)
    UNION ALL
    SELECT date_trunc('week', end_ts)::date, 0, 1
    FROM clean_work_orders
    WHERE end_ts IS NOT NULL
      AND station_code = (SELECT station_code FROM clean_stations ORDER BY station_seq DESC LIMIT 1)
) t
GROUP BY week_start;
