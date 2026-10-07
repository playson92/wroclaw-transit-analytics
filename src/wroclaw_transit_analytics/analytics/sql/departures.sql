CREATE TEMP TABLE wta_departures ON COMMIT DROP AS
SELECT e.*,
       departure_seconds - lag(departure_seconds) OVER (
           PARTITION BY dataset_id, service_date, route_id, stop_id, direction_id
           ORDER BY departure_seconds, trip_id, stop_sequence
       ) AS headway_seconds
FROM wta_events e
WHERE pickup_type = 0 AND departure_seconds IS NOT NULL
