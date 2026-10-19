-- PostgreSQL. Raw tables, deliberately without constraints: real ERP/MES extracts arrive
-- with duplicates and broken references, and the data quality checks exist
-- to find them.

DROP TABLE IF EXISTS raw_stations;
CREATE TABLE raw_stations (
    station_seq   INTEGER,
    station_code  VARCHAR,
    station_name  VARCHAR
);

DROP TABLE IF EXISTS raw_suppliers;
CREATE TABLE raw_suppliers (
    supplier_id   VARCHAR,
    supplier_name VARCHAR
);

DROP TABLE IF EXISTS raw_parts;
CREATE TABLE raw_parts (
    part_id        VARCHAR,
    part_name      VARCHAR,
    supplier_id    VARCHAR,
    unit_cost      DOUBLE PRECISION,
    reorder_point  INTEGER,
    lead_time_days INTEGER      -- quoted by the supplier
);

DROP TABLE IF EXISTS raw_bom;
CREATE TABLE raw_bom (
    station_code  VARCHAR,
    part_id       VARCHAR,
    qty_per_unit  INTEGER
);

DROP TABLE IF EXISTS raw_inventory_snapshots;
CREATE TABLE raw_inventory_snapshots (
    snapshot_date DATE,
    part_id       VARCHAR,
    location      VARCHAR,     -- WAREHOUSE | LINE_SIDE
    on_hand       INTEGER
);

DROP TABLE IF EXISTS raw_receiving;
CREATE TABLE raw_receiving (
    shipment_id    VARCHAR,
    lot_id         VARCHAR,    -- each shipment is one supplier lot
    part_id        VARCHAR,
    order_date     DATE,
    expected_date  DATE,
    received_date  DATE,       -- NULL while the shipment is in transit
    qty_expected   INTEGER,
    qty_received   INTEGER     -- NULL while the shipment is in transit
);

DROP TABLE IF EXISTS raw_work_orders;
CREATE TABLE raw_work_orders (
    wo_id          VARCHAR,
    serial_number  VARCHAR,
    station_code   VARCHAR,
    start_ts       TIMESTAMP,
    end_ts         TIMESTAMP,  -- NULL while IN_PROGRESS
    status         VARCHAR     -- COMPLETE | IN_PROGRESS
);

DROP TABLE IF EXISTS raw_inspections;
CREATE TABLE raw_inspections (
    inspection_id  VARCHAR,
    serial_number  VARCHAR,
    station_code   VARCHAR,
    attempt        INTEGER,    -- 1 = first pass, 2 = after rework
    inspected_ts   TIMESTAMP,
    result         VARCHAR,    -- PASS | FAIL
    defect_code    VARCHAR     -- required when result = FAIL
);

-- Traceability: which lot of each part went into which drone, and where.
DROP TABLE IF EXISTS raw_drone_part_lots;
CREATE TABLE raw_drone_part_lots (
    serial_number  VARCHAR,
    station_code   VARCHAR,    -- station where the part was installed
    part_id        VARCHAR,
    lot_id         VARCHAR
);

-- One row per drone that passed Final Test.
DROP TABLE IF EXISTS raw_finished_goods;
CREATE TABLE raw_finished_goods (
    serial_number   VARCHAR,
    test_passed_ts  TIMESTAMP,
    packed_ts       TIMESTAMP, -- NULL until packed
    shipped_ts      TIMESTAMP  -- NULL until shipped
);
