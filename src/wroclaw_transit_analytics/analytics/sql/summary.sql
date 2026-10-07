SELECT jsonb_build_object(
    'calendar_envelope', jsonb_build_object('start_date', min(source_start), 'end_date', max(source_end)),
    'calendar_coverage_method', 'min/max of calendar bounds and calendar_dates; not proof of complete feed validity',
    'requested_days', count(*), 'covered_days', count(*) FILTER (WHERE calendar_covered),
    'outside_calendar_days', count(*) FILTER (WHERE NOT calendar_covered),
    'total_events', sum(total_events), 'known_arrivals', sum(known_arrivals),
    'missing_arrivals', sum(missing_arrivals), 'known_departures', sum(known_departures),
    'missing_departures', sum(missing_departures), 'regular_events', sum(regular_events),
    'regular_known_departures', sum(regular_known_departures),
    'regular_missing_departures', sum(regular_missing_departures),
    'no_pickup_events', sum(no_pickup_events), 'on_request_events', sum(on_request_events),
    'approximate_timepoint_events', sum(approximate_timepoint_events),
    'known_departure_ratio', sum(known_departures)::numeric / nullif(sum(total_events), 0),
    'known_regular_departure_ratio', sum(regular_known_departures)::numeric / nullif(sum(regular_events), 0),
    'time_axis', 'service_date plus GTFS seconds; no UTC or DST wall-clock conversion'
)
FROM wta_coverage
