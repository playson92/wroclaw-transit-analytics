INSERT INTO gold.route_stop_headways
    (analysis_id, dataset_id, service_date, route_id, stop_id, direction_id,
     departure_count, interval_count, avg_seconds, median_seconds, p90_seconds)
WITH groups AS (
    SELECT DISTINCT dataset_id, service_date, route_id, stop_id, direction_id FROM wta_events
), gaps AS (
    SELECT dataset_id, service_date, route_id, stop_id, direction_id, count(*) AS departures,
           count(headway_seconds) AS intervals, avg(headway_seconds) AS average,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY headway_seconds::double precision) AS median,
           percentile_cont(0.9) WITHIN GROUP (ORDER BY headway_seconds::double precision) AS p90
    FROM wta_departures GROUP BY dataset_id, service_date, route_id, stop_id, direction_id
)
SELECT ctx.analysis_id, g.dataset_id, g.service_date, g.route_id, g.stop_id, g.direction_id,
       coalesce(x.departures, 0), coalesce(x.intervals, 0), x.average, x.median, x.p90
FROM groups g CROSS JOIN wta_context ctx LEFT JOIN gaps x
    ON x.dataset_id = g.dataset_id AND x.service_date = g.service_date
    AND x.route_id = g.route_id AND x.stop_id = g.stop_id
    AND x.direction_id IS NOT DISTINCT FROM g.direction_id
