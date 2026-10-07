CREATE TEMP TABLE wta_instances ON COMMIT DROP AS
SELECT t.dataset_id, s.service_date, t.trip_id, t.route_id, t.service_id, t.direction_id
FROM wta_services s
JOIN silver.trips t ON t.dataset_id = s.dataset_id AND t.service_id = s.service_id
