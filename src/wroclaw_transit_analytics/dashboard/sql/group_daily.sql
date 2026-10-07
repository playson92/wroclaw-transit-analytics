SELECT d.service_date, d.calendar_covered,
       CASE WHEN d.calendar_covered THEN coalesce(sum(s.observation_count),0) END AS departures,
       CASE WHEN d.calendar_covered THEN coalesce(sum(s.regular_event_count),0) END AS regular_events,
       CASE WHEN d.calendar_covered THEN coalesce(sum(s.missing_regular_departures),0) END AS missing,
       CASE WHEN d.calendar_covered THEN coalesce(sum(s.approximate_departures),0) END AS approximate,
       min(s.first_departure_seconds) AS first_seconds, max(s.last_departure_seconds) AS last_seconds
FROM gold.analysis_days d
LEFT JOIN gold.service_span s ON s.dataset_id=d.dataset_id AND s.analysis_id=d.analysis_id
    AND s.service_date=d.service_date AND s.route_id=%(route)s AND s.stop_id=%(stop)s
    AND (%(direction)s='ALL' OR (%(direction)s='NULL' AND s.direction_id IS NULL)
         OR s.direction_id::text=%(direction)s)
WHERE d.dataset_id=%(dataset)s AND d.analysis_id=%(analysis)s
  AND d.service_date BETWEEN %(start)s AND %(end)s
GROUP BY d.service_date, d.calendar_covered ORDER BY d.service_date
