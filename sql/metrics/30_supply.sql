-- Supplier delivery performance, on shipments that have arrived. The pre-launch shipments that make up the
-- starting stock are left out: they are always "on time" and would flatter every supplier.
--   on time   = received on or before the expected date
--   in full   = received at least the expected quantity
--   lateness  = days after the expected date (0 when on time or early)
-- A shipment whose recorded quantity was over the expected quantity (capped in clean_receiving) has an unverifiable
-- quantity: the true figure could have been anything, including short. It still counts for on-time and lateness, but
-- not toward in-full or OTIF, so the cap can never make a supplier look better than the data supports.
CREATE OR REPLACE VIEW v_supplier_performance AS
SELECT
    su.supplier_id,
    su.supplier_name,
    COUNT(*) AS shipments_received,
    ROUND(AVG((r.received_date <= r.expected_date)::int)::numeric, 4) AS on_time_rate,
    ROUND(AVG(CASE WHEN NOT r.qty_capped THEN (r.qty_received >= r.qty_expected)::int END)::numeric, 4) AS in_full_rate,
    ROUND(AVG(CASE WHEN NOT r.qty_capped THEN (r.received_date <= r.expected_date AND r.qty_received >= r.qty_expected)::int END)::numeric, 4) AS otif_rate,
    COUNT(*) FILTER (WHERE r.qty_capped) AS quantity_unverified,
    ROUND(AVG(GREATEST(r.received_date - r.expected_date, 0))::numeric, 2) AS avg_days_late,
    ROUND((percentile_cont(0.9) WITHIN GROUP (ORDER BY GREATEST(r.received_date - r.expected_date, 0)))::numeric, 2) AS p90_days_late
FROM clean_receiving r
JOIN clean_suppliers su ON su.supplier_id = r.supplier_id
WHERE r.received_date IS NOT NULL AND NOT r.is_pre_launch
GROUP BY su.supplier_id, su.supplier_name;

-- Days of stock left against how long until the next delivery lands, for every part, at the extract.
--   daily demand     = BOM quantity x drones started at the part's station in the last 14 days, / 14
--   days remaining   = stock (warehouse + line-side) / daily demand
--   days to next     = days until the next open shipment is expected (or the quoted lead time if none is open)
--   bad-case arrival = days to next + the supplier's 90th-percentile lateness (the risk measure)
--   average arrival  = days to next + the supplier's average lateness (shown for comparison)
--   cushion          = days remaining - bad-case arrival; negative means the stock is expected to run out first
-- This is arithmetic on observed data, not a forecast.
CREATE OR REPLACE VIEW v_inventory_risk AS
WITH cal AS (
    SELECT as_of_date FROM v_calendar
),
latest AS (
    SELECT s.part_id, SUM(s.on_hand) AS on_hand
    FROM clean_inventory_snapshots s, cal
    WHERE s.snapshot_date = cal.as_of_date
    GROUP BY s.part_id
),
starts AS (
    SELECT w.station_code, COUNT(*) AS drones
    FROM clean_work_orders w, cal
    WHERE w.start_ts::date > cal.as_of_date - 14 AND w.start_ts::date <= cal.as_of_date
    GROUP BY w.station_code
),
demand AS (
    SELECT b.part_id, b.station_code, b.qty_per_unit, b.qty_per_unit * COALESCE(st.drones, 0) / 14.0 AS daily_demand
    FROM clean_bom b
    LEFT JOIN starts st USING (station_code)
),
inbound AS (
    SELECT part_id, MIN(expected_date) AS next_expected, SUM(qty_expected) AS inbound_qty
    FROM clean_receiving
    WHERE received_date IS NULL
    GROUP BY part_id
),
joined AS (
    SELECT
        p.part_id, p.part_name, p.supplier_id, su.supplier_name, d.station_code, p.lead_time_days,
        l.on_hand, d.daily_demand,
        l.on_hand / NULLIF(d.daily_demand, 0) AS days_remaining,
        i.next_expected, COALESCE(i.inbound_qty, 0) AS inbound_qty,
        GREATEST(0, COALESCE(i.next_expected - cal.as_of_date, p.lead_time_days)) AS days_to_next,
        COALESCE(sp.avg_days_late, 0) AS avg_days_late,
        COALESCE(sp.p90_days_late, 0) AS p90_days_late
    FROM clean_parts p
    JOIN clean_suppliers su ON su.supplier_id = p.supplier_id
    JOIN latest l ON l.part_id = p.part_id
    JOIN demand d ON d.part_id = p.part_id
    LEFT JOIN inbound i ON i.part_id = p.part_id
    LEFT JOIN v_supplier_performance sp ON sp.supplier_id = p.supplier_id
    CROSS JOIN cal
),
scored AS (
    SELECT *,
           days_to_next + ROUND(avg_days_late) AS arrival_avg_days,
           days_to_next + CEIL(p90_days_late) AS arrival_bad_case_days
    FROM joined
)
SELECT
    part_id, part_name, supplier_id, supplier_name, station_code, lead_time_days,
    on_hand,
    ROUND(daily_demand::numeric, 2) AS daily_demand,
    ROUND(days_remaining::numeric, 1) AS days_remaining,
    next_expected, inbound_qty, days_to_next,
    arrival_avg_days, arrival_bad_case_days,
    ROUND((days_remaining - arrival_bad_case_days)::numeric, 1) AS cushion_days,
    COALESCE(days_remaining < arrival_avg_days, FALSE) AS at_risk_average,
    CASE
        WHEN on_hand = 0 AND daily_demand > 0 THEN 'STOCKOUT'
        WHEN days_remaining < arrival_bad_case_days THEN 'AT RISK'
        WHEN days_remaining < arrival_bad_case_days + 5 THEN 'WATCH'
        ELSE 'OK'
    END AS risk_status
FROM scored;

-- Right part, wrong place: end-of-day snapshots where the warehouse holds enough for at least one drone
-- but the line-side shelf holds less than one drone's worth. Weekdays only.
CREATE OR REPLACE VIEW v_line_side_gap_daily AS
SELECT
    w.snapshot_date,
    w.part_id,
    b.station_code,
    w.on_hand AS warehouse_on_hand,
    l.on_hand AS line_side_on_hand
FROM clean_inventory_snapshots w
JOIN clean_inventory_snapshots l
  ON l.snapshot_date = w.snapshot_date AND l.part_id = w.part_id AND l.location = 'LINE_SIDE'
JOIN clean_bom b ON b.part_id = w.part_id
WHERE w.location = 'WAREHOUSE'
  AND w.on_hand >= b.qty_per_unit
  AND l.on_hand < b.qty_per_unit
  AND EXTRACT(ISODOW FROM w.snapshot_date) <= 5;

CREATE OR REPLACE VIEW v_line_side_gap AS
SELECT
    g.part_id,
    p.part_name,
    g.station_code,
    COUNT(*) AS days_short_at_line,
    MIN(g.snapshot_date) AS first_day,
    MAX(g.snapshot_date) AS last_day,
    ROUND(AVG(g.warehouse_on_hand)::numeric, 0) AS avg_warehouse_stock
FROM v_line_side_gap_daily g
JOIN clean_parts p USING (part_id)
GROUP BY g.part_id, p.part_name, g.station_code;
