-- severity: error
-- category: planted
-- description: received quantity is higher than the quantity expected on the shipment
SELECT shipment_id AS record_key
FROM raw_receiving
WHERE qty_received > qty_expected
