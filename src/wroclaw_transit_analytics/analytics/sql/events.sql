CREATE TEMP TABLE wta_events ON COMMIT DROP AS
SELECT i.dataset_id, i.service_date, i.route_id, i.direction_id,
       s.trip_id, s.stop_id, s.stop_sequence, s.arrival_seconds, s.departure_seconds,
       s.pickup_type, s.timepoint
FROM wta_instances i
JOIN silver.stop_times s ON s.dataset_id = i.dataset_id AND s.trip_id = i.trip_id
