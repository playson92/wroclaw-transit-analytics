INSERT INTO gold.service_span
    (analysis_id, dataset_id, service_date, route_id, stop_id, direction_id,
     first_departure_seconds, last_departure_seconds, observation_count, regular_event_count,
     missing_regular_departures, approximate_departures, known_regular_ratio)
SELECT ctx.analysis_id, e.dataset_id, service_date, route_id, stop_id, direction_id,
       min(departure_seconds) FILTER (WHERE pickup_type = 0),
       max(departure_seconds) FILTER (WHERE pickup_type = 0),
       count(*) FILTER (WHERE pickup_type = 0 AND departure_seconds IS NOT NULL),
       count(*) FILTER (WHERE pickup_type = 0),
       count(*) FILTER (WHERE pickup_type = 0 AND departure_seconds IS NULL),
       count(*) FILTER (WHERE pickup_type = 0 AND departure_seconds IS NOT NULL AND timepoint = 0),
       count(*) FILTER (WHERE pickup_type = 0 AND departure_seconds IS NOT NULL)::numeric /
           nullif(count(*) FILTER (WHERE pickup_type = 0), 0)
FROM wta_events e CROSS JOIN wta_context ctx
GROUP BY ctx.analysis_id, e.dataset_id, service_date, route_id, stop_id, direction_id
