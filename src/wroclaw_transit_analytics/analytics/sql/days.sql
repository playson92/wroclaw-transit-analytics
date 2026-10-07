CREATE TEMP TABLE wta_days ON COMMIT DROP AS
WITH envelope AS (
    SELECT min(value) AS source_start, max(value) AS source_end
    FROM (
        SELECT start_date AS value FROM silver.calendar WHERE dataset_id = (SELECT dataset_id FROM wta_context)
        UNION ALL
        SELECT end_date FROM silver.calendar WHERE dataset_id = (SELECT dataset_id FROM wta_context)
        UNION ALL
        SELECT date FROM silver.calendar_dates WHERE dataset_id = (SELECT dataset_id FROM wta_context)
    ) boundaries
)
SELECT d::date AS service_date, source_start, source_end,
       coalesce(d::date BETWEEN source_start AND source_end, false) AS calendar_covered
FROM wta_context c CROSS JOIN envelope
CROSS JOIN LATERAL generate_series(c.start_date::timestamp, c.end_date::timestamp, interval '1 day') d
