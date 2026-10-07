CREATE TEMP TABLE wta_services ON COMMIT DROP AS
WITH included AS (
    SELECT c.dataset_id, d.service_date, c.service_id
    FROM silver.calendar c JOIN wta_context ctx ON ctx.dataset_id = c.dataset_id
    JOIN wta_days d ON d.service_date BETWEEN c.start_date AND c.end_date
    WHERE CASE extract(isodow FROM d.service_date)
        WHEN 1 THEN monday WHEN 2 THEN tuesday WHEN 3 THEN wednesday WHEN 4 THEN thursday
        WHEN 5 THEN friday WHEN 6 THEN saturday WHEN 7 THEN sunday END = 1
    UNION
    SELECT c.dataset_id, c.date, c.service_id
    FROM silver.calendar_dates c JOIN wta_context ctx ON ctx.dataset_id = c.dataset_id
    JOIN wta_days d ON d.service_date = c.date
    WHERE c.exception_type = 1
)
SELECT * FROM included
EXCEPT
SELECT c.dataset_id, c.date, c.service_id
FROM silver.calendar_dates c JOIN wta_context ctx ON ctx.dataset_id = c.dataset_id
JOIN wta_days d ON d.service_date = c.date
WHERE c.exception_type = 2
