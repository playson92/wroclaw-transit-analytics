INSERT INTO gold.analysis_days
    (analysis_id, dataset_id, service_date, calendar_covered, coverage_state, active_services, trip_instances)
SELECT ctx.analysis_id, ctx.dataset_id, d.service_date, d.calendar_covered,
       CASE WHEN d.calendar_covered THEN 'within-calendar-envelope' ELSE 'outside-calendar-envelope' END,
       CASE WHEN d.calendar_covered THEN coalesce(s.n, 0) END,
       CASE WHEN d.calendar_covered THEN coalesce(i.n, 0) END
FROM wta_days d CROSS JOIN wta_context ctx
LEFT JOIN (SELECT service_date, count(*) AS n FROM wta_services GROUP BY service_date) s USING (service_date)
LEFT JOIN (SELECT service_date, count(*) AS n FROM wta_instances GROUP BY service_date) i USING (service_date)
