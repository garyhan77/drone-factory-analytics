-- The clean layer. Every metric reads from these views, never from raw_*.
--
-- What each view does with the rows the data quality checks flag:
--   work orders    re-keyed duplicates are dropped (the earliest wo_id is kept); a job that ends before it
--                  starts is KEPT with its end time set to NULL and end_unknown = true, so it still counts
--                  as started but drops out of cycle time and does not stretch the next station's wait
--   inspections    inspections for a drone with no work order at that station are dropped; failures with no
--                  usable defect code are KEPT and labelled <station>-UNCODED
--   inventory      a negative reading is replaced by the last good reading for that part and location
--   receiving      an over-received shipment is KEPT with the quantity capped at what was expected
-- Tables with no planted errors pass straight through so the app only ever reads clean_* and v_* names.

-- Reference dates, found from the data itself.
CREATE OR REPLACE VIEW v_calendar AS
SELECT
    (SELECT MIN(start_ts)::date FROM raw_work_orders) AS launch_date,
    (SELECT MAX(snapshot_date) FROM raw_inventory_snapshots) AS as_of_date,
    GREATEST(
        (SELECT MAX(start_ts) FROM raw_work_orders),
        (SELECT MAX(inspected_ts) FROM raw_inspections),
        (SELECT MAX(packed_ts) FROM raw_finished_goods)
    ) AS as_of_ts;

CREATE OR REPLACE VIEW clean_stations AS SELECT * FROM raw_stations;
CREATE OR REPLACE VIEW clean_suppliers AS SELECT * FROM raw_suppliers;
CREATE OR REPLACE VIEW clean_parts AS SELECT * FROM raw_parts;
CREATE OR REPLACE VIEW clean_bom AS SELECT * FROM raw_bom;
CREATE OR REPLACE VIEW clean_drone_part_lots AS SELECT * FROM raw_drone_part_lots;
CREATE OR REPLACE VIEW clean_finished_goods AS SELECT * FROM raw_finished_goods;

CREATE OR REPLACE VIEW clean_work_orders AS
WITH numbered AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY serial_number, station_code, start_ts ORDER BY wo_id) AS copy_number
    FROM raw_work_orders
)
SELECT
    wo_id,
    serial_number,
    station_code,
    start_ts,
    CASE WHEN end_ts < start_ts THEN NULL ELSE end_ts END AS end_ts,
    status,
    COALESCE(end_ts < start_ts, FALSE) AS end_unknown
FROM numbered
WHERE copy_number = 1;

CREATE OR REPLACE VIEW clean_inspections AS
SELECT
    i.inspection_id,
    i.serial_number,
    i.station_code,
    i.attempt,
    i.inspected_ts,
    i.result,
    CASE WHEN i.result = 'FAIL'
         THEN COALESCE(NULLIF(TRIM(i.defect_code), ''), i.station_code || '-UNCODED')
    END AS defect_code,
    (i.result = 'FAIL' AND COALESCE(TRIM(i.defect_code), '') = '') AS code_was_missing
FROM raw_inspections i
WHERE EXISTS (
    SELECT 1 FROM clean_work_orders w
    WHERE w.serial_number = i.serial_number AND w.station_code = i.station_code
);

CREATE OR REPLACE VIEW clean_inventory_snapshots AS
WITH marked AS (
    SELECT snapshot_date, part_id, location, on_hand,
           CASE WHEN on_hand >= 0 THEN on_hand END AS good_reading,
           COUNT(CASE WHEN on_hand >= 0 THEN 1 END)
               OVER (PARTITION BY part_id, location ORDER BY snapshot_date) AS good_so_far
    FROM raw_inventory_snapshots
),
patched AS (
    SELECT
        snapshot_date,
        part_id,
        location,
        COALESCE(good_reading, MAX(good_reading) OVER (PARTITION BY part_id, location, good_so_far)) AS on_hand,
        (on_hand < 0) AS repaired
    FROM marked
)
SELECT snapshot_date, part_id, location, on_hand, repaired
FROM patched
WHERE on_hand IS NOT NULL;  -- a negative first reading has no earlier good value to carry forward, so it is dropped

CREATE OR REPLACE VIEW clean_receiving AS
SELECT
    shipment_id,
    lot_id,
    supplier_id,
    part_id,
    order_date,
    expected_date,
    received_date,
    qty_expected,
    CASE WHEN qty_received > qty_expected THEN qty_expected ELSE qty_received END AS qty_received,
    COALESCE(qty_received > qty_expected, FALSE) AS qty_capped,
    COALESCE(received_date < (SELECT launch_date FROM v_calendar), FALSE) AS is_pre_launch
FROM raw_receiving;
