INSERT INTO gold.route_stop_hourly
    (analysis_id, dataset_id, service_date, route_id, stop_id, direction_id, service_hour,
     departure_count, approximate_departures)
SELECT ctx.analysis_id, e.dataset_id, e.service_date, e.route_id, e.stop_id, e.direction_id,
       e.departure_seconds / 3600 AS service_hour, count(*), count(*) FILTER (WHERE timepoint = 0)
FROM wta_departures e CROSS JOIN wta_context ctx
GROUP BY ctx.analysis_id, e.dataset_id, e.service_date, e.route_id, e.stop_id, e.direction_id,
         e.departure_seconds / 3600
