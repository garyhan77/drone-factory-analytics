-- First-pass yield: the share of inspections that pass on the first attempt (rework passes do not count).
CREATE OR REPLACE VIEW v_first_pass_yield_weekly AS
SELECT
    date_trunc('week', i.inspected_ts)::date AS week_start,
    s.station_seq,
    i.station_code,
    s.station_name,
    COUNT(*) AS inspections,
    COUNT(*) FILTER (WHERE i.result = 'PASS') AS passes,
    ROUND(COUNT(*) FILTER (WHERE i.result = 'PASS')::numeric / COUNT(*), 4) AS fpy
FROM clean_inspections i
JOIN clean_stations s USING (station_code)
WHERE i.attempt = 1
GROUP BY 1, 2, 3, 4;

-- First-attempt failures by defect code. Failures with no usable code stay in as <station>-UNCODED.
CREATE OR REPLACE VIEW v_defect_pareto AS
WITH fails AS (
    SELECT station_code, defect_code, COUNT(*) AS fails
    FROM clean_inspections
    WHERE attempt = 1 AND result = 'FAIL'
    GROUP BY 1, 2
)
SELECT
    station_code,
    defect_code,
    fails,
    ROUND(fails::numeric / SUM(fails) OVER (), 4) AS pct_of_fails,
    ROUND(SUM(fails) OVER (ORDER BY fails DESC, defect_code)::numeric / SUM(fails) OVER (), 4) AS cum_pct
FROM fails
ORDER BY fails DESC, defect_code;

CREATE OR REPLACE VIEW v_defects_weekly AS
SELECT
    date_trunc('week', inspected_ts)::date AS week_start,
    station_code,
    defect_code,
    COUNT(*) AS fails
FROM clean_inspections
WHERE attempt = 1 AND result = 'FAIL'
GROUP BY 1, 2, 3;
