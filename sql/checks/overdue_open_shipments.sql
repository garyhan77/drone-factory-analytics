-- severity: warn
-- category: operational
-- description: shipment still in transit more than 3 days after its expected date (not a data error, but something operations should see)
SELECT shipment_id AS record_key
FROM raw_receiving
WHERE received_date IS NULL
  AND expected_date < (SELECT MAX(snapshot_date) FROM raw_inventory_snapshots) - 3
