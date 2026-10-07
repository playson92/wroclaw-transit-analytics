WITH days AS (
    SELECT * FROM gold.analysis_days
    WHERE dataset_id=%(dataset)s AND analysis_id=%(analysis)s
      AND service_date BETWEEN %(start)s AND %(end)s
), cov AS (
    SELECT sum(regular_known_departures) AS departures, sum(regular_events) AS regular_events,
           sum(total_events) AS total_events, sum(missing_departures) AS missing_departures,
           sum(no_pickup_events) AS no_pickup_events, sum(on_request_events) AS on_request_events,
           sum(approximate_regular_departures) AS approximate_departures
    FROM gold.coverage_daily WHERE dataset_id=%(dataset)s AND analysis_id=%(analysis)s
      AND service_date BETWEEN %(start)s AND %(end)s
)
SELECT (SELECT sum(trip_instances) FROM days) AS trips, cov.*,
       (SELECT count(*) FILTER (WHERE calendar_covered) FROM days) AS covered_days,
       (SELECT count(*) FROM days) AS requested_days,
       CASE WHEN EXISTS(SELECT 1 FROM days WHERE calendar_covered) THEN
         (SELECT count(DISTINCT route_id) FROM gold.route_daily
          WHERE dataset_id=%(dataset)s AND analysis_id=%(analysis)s
            AND service_date BETWEEN %(start)s AND %(end)s AND trip_count>0) END AS active_routes,
       CASE WHEN EXISTS(SELECT 1 FROM days WHERE calendar_covered) THEN
         (SELECT count(DISTINCT stop_id) FROM gold.service_span
          WHERE dataset_id=%(dataset)s AND analysis_id=%(analysis)s
            AND service_date BETWEEN %(start)s AND %(end)s) END AS served_stops,
       (SELECT count(*) FROM gold.stop_catalog WHERE dataset_id=%(dataset)s) AS catalog_stops
FROM cov
