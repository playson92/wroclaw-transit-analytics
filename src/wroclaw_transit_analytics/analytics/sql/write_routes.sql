INSERT INTO gold.route_daily
    (analysis_id, dataset_id, service_date, route_id, calendar_covered, trip_count)
SELECT ctx.analysis_id, r.dataset_id, d.service_date, r.route_id, d.calendar_covered,
       CASE WHEN d.calendar_covered THEN coalesce(i.n, 0) END
FROM wta_context ctx JOIN silver.routes r ON r.dataset_id = ctx.dataset_id
CROSS JOIN wta_days d
LEFT JOIN (SELECT dataset_id, service_date, route_id, count(*) AS n
           FROM wta_instances GROUP BY dataset_id, service_date, route_id) i
    ON i.dataset_id = r.dataset_id AND i.service_date = d.service_date AND i.route_id = r.route_id
