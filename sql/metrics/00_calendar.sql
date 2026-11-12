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
