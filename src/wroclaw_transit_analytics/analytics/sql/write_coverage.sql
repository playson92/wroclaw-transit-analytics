INSERT INTO gold.coverage_daily
    (analysis_id, dataset_id, service_date, calendar_covered, total_events,
     known_arrivals, missing_arrivals, known_departures, missing_departures,
     regular_events, regular_known_departures, regular_missing_departures,
     no_pickup_events, on_request_events, pickup_type_2_events, pickup_type_3_events,
     exact_timepoint_events, approximate_timepoint_events, approximate_regular_departures,
     known_arrival_ratio, known_departure_ratio, known_regular_departure_ratio)
SELECT ctx.analysis_id, ctx.dataset_id, c.service_date, c.calendar_covered, c.total_events,
       c.known_arrivals, c.missing_arrivals, c.known_departures, c.missing_departures,
       c.regular_events, c.regular_known_departures, c.regular_missing_departures,
       c.no_pickup_events, c.on_request_events, c.pickup_type_2_events, c.pickup_type_3_events,
       c.exact_timepoint_events, c.approximate_timepoint_events, c.approximate_regular_departures,
       c.known_arrival_ratio, c.known_departure_ratio, c.known_regular_departure_ratio
FROM wta_coverage c CROSS JOIN wta_context ctx
