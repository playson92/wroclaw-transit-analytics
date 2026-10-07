INSERT INTO gold.stop_daily
    (analysis_id, dataset_id, service_date, stop_id, calendar_covered, regular_known_departures, distinct_routes)
SELECT ctx.analysis_id, s.dataset_id, d.service_date, s.stop_id, d.calendar_covered,
       CASE WHEN d.calendar_covered THEN coalesce(e.n, 0) END,
       CASE WHEN d.calendar_covered THEN coalesce(e.routes, 0) END
FROM wta_context ctx JOIN silver.stops s ON s.dataset_id = ctx.dataset_id AND s.location_type = 0
CROSS JOIN wta_days d
LEFT JOIN (SELECT dataset_id, service_date, stop_id, count(*) AS n, count(DISTINCT route_id) AS routes
           FROM wta_departures GROUP BY dataset_id, service_date, stop_id) e
    ON e.dataset_id = s.dataset_id AND e.service_date = d.service_date AND e.stop_id = s.stop_id
