WITH trip_counts AS (
    SELECT dataset_id, trip_id, count(*) AS events FROM silver.stop_times
    WHERE dataset_id = (SELECT dataset_id FROM wta_context) GROUP BY dataset_id, trip_id
)
SELECT coalesce((SELECT sum(c.events) FROM wta_instances i JOIN trip_counts c USING (dataset_id, trip_id)), 0) AS events,
       (SELECT count(*) FROM wta_instances) AS instances,
       (SELECT count(*) FROM wta_days) * (
           (SELECT count(*) FROM silver.routes WHERE dataset_id = (SELECT dataset_id FROM wta_context)) +
           (SELECT count(*) FROM silver.stops WHERE dataset_id = (SELECT dataset_id FROM wta_context) AND location_type = 0)
       ) AS grid_rows
