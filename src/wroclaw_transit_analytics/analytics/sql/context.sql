CREATE TEMP TABLE wta_context ON COMMIT DROP AS
SELECT %(dataset_id)s::text AS dataset_id, %(analysis_id)s::text AS analysis_id,
       %(start_date)s::date AS start_date, %(end_date)s::date AS end_date
