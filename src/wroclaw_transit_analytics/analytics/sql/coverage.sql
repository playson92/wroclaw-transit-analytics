CREATE TEMP TABLE wta_coverage ON COMMIT DROP AS
WITH observations AS (
    SELECT service_date, count(*) AS total_events,
           count(*) FILTER (WHERE arrival_seconds IS NOT NULL) AS known_arrivals,
           count(*) FILTER (WHERE departure_seconds IS NOT NULL) AS known_departures,
           count(*) FILTER (WHERE pickup_type = 0) AS regular_events,
           count(*) FILTER (WHERE pickup_type = 0 AND departure_seconds IS NOT NULL) AS regular_known_departures,
           count(*) FILTER (WHERE pickup_type = 1) AS no_pickup_events,
           count(*) FILTER (WHERE pickup_type IN (2, 3)) AS on_request_events,
           count(*) FILTER (WHERE pickup_type = 2) AS pickup_type_2_events,
           count(*) FILTER (WHERE pickup_type = 3) AS pickup_type_3_events,
           count(*) FILTER (WHERE timepoint = 1) AS exact_timepoint_events,
           count(*) FILTER (WHERE timepoint = 0) AS approximate_timepoint_events,
           count(*) FILTER (WHERE timepoint = 0 AND pickup_type = 0 AND departure_seconds IS NOT NULL)
               AS approximate_regular_departures
    FROM wta_events GROUP BY service_date
), measured AS (
    SELECT d.*,
           CASE WHEN calendar_covered THEN coalesce(total_events, 0) END AS total_events,
           CASE WHEN calendar_covered THEN coalesce(known_arrivals, 0) END AS known_arrivals,
           CASE WHEN calendar_covered THEN coalesce(known_departures, 0) END AS known_departures,
           CASE WHEN calendar_covered THEN coalesce(regular_events, 0) END AS regular_events,
           CASE WHEN calendar_covered THEN coalesce(regular_known_departures, 0) END AS regular_known_departures,
           CASE WHEN calendar_covered THEN coalesce(no_pickup_events, 0) END AS no_pickup_events,
           CASE WHEN calendar_covered THEN coalesce(on_request_events, 0) END AS on_request_events,
           CASE WHEN calendar_covered THEN coalesce(pickup_type_2_events, 0) END AS pickup_type_2_events,
           CASE WHEN calendar_covered THEN coalesce(pickup_type_3_events, 0) END AS pickup_type_3_events,
           CASE WHEN calendar_covered THEN coalesce(exact_timepoint_events, 0) END AS exact_timepoint_events,
           CASE WHEN calendar_covered THEN coalesce(approximate_timepoint_events, 0) END AS approximate_timepoint_events,
           CASE WHEN calendar_covered THEN coalesce(approximate_regular_departures, 0) END AS approximate_regular_departures
    FROM wta_days d LEFT JOIN observations USING (service_date)
)
SELECT *, total_events - known_arrivals AS missing_arrivals,
       total_events - known_departures AS missing_departures,
       regular_events - regular_known_departures AS regular_missing_departures,
       known_arrivals::numeric / nullif(total_events, 0) AS known_arrival_ratio,
       known_departures::numeric / nullif(total_events, 0) AS known_departure_ratio,
       regular_known_departures::numeric / nullif(regular_events, 0) AS known_regular_departure_ratio
FROM measured
