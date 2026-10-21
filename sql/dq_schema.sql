-- Data quality results. These tables sit beside the raw tables so the app can show scores from the database.

DROP TABLE IF EXISTS dq_answer_key;
CREATE TABLE dq_answer_key (
    check_name  VARCHAR,
    record_key  VARCHAR
);

DROP TABLE IF EXISTS dq_flagged;
CREATE TABLE dq_flagged (
    check_name  VARCHAR,
    record_key  VARCHAR
);

DROP TABLE IF EXISTS dq_results;
CREATE TABLE dq_results (
    check_name       VARCHAR,
    category         VARCHAR,   -- planted | guard | sanity | operational
    severity         VARCHAR,   -- error | warn
    description      VARCHAR,
    flagged_rows     INTEGER,
    planted_rows     INTEGER,   -- NULL for checks that are not scored
    caught           INTEGER,
    missed           INTEGER,
    false_positives  INTEGER
);
