CREATE SCHEMA gold;

CREATE TABLE meta.analyses (
    analysis_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES meta.datasets(dataset_id),
    metrics_version TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL CHECK (end_date >= start_date),
    input_fingerprint TEXT NOT NULL,
    rules_sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status = 'complete'),
    coverage JSONB NOT NULL,
    source_context JSONB NOT NULL,
    execution_limits JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (analysis_id, dataset_id),
    UNIQUE (dataset_id, metrics_version, start_date, end_date)
);

CREATE TABLE gold.analysis_days (
    analysis_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    service_date DATE NOT NULL,
    calendar_covered BOOLEAN NOT NULL,
    coverage_state TEXT NOT NULL CHECK (coverage_state IN
        ('within-calendar-envelope', 'outside-calendar-envelope')),
    active_services BIGINT,
    trip_instances BIGINT,
    PRIMARY KEY (analysis_id, dataset_id, service_date),
    FOREIGN KEY (analysis_id, dataset_id) REFERENCES meta.analyses(analysis_id, dataset_id)
);

CREATE TABLE gold.active_services (
    analysis_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    service_date DATE NOT NULL,
    service_id TEXT NOT NULL,
    PRIMARY KEY (analysis_id, dataset_id, service_date, service_id),
    FOREIGN KEY (analysis_id, dataset_id, service_date)
        REFERENCES gold.analysis_days(analysis_id, dataset_id, service_date),
    FOREIGN KEY (dataset_id, service_id) REFERENCES silver.services(dataset_id, service_id)
);

CREATE TABLE gold.route_daily (
    analysis_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    service_date DATE NOT NULL,
    route_id TEXT NOT NULL,
    calendar_covered BOOLEAN NOT NULL,
    trip_count BIGINT CHECK (trip_count >= 0),
    CHECK ((calendar_covered AND trip_count IS NOT NULL) OR
        (NOT calendar_covered AND trip_count IS NULL)),
    PRIMARY KEY (analysis_id, dataset_id, service_date, route_id),
    FOREIGN KEY (analysis_id, dataset_id, service_date)
        REFERENCES gold.analysis_days(analysis_id, dataset_id, service_date),
    FOREIGN KEY (dataset_id, route_id) REFERENCES silver.routes(dataset_id, route_id)
);

CREATE TABLE gold.stop_daily (
    analysis_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    service_date DATE NOT NULL,
    stop_id TEXT NOT NULL,
    calendar_covered BOOLEAN NOT NULL,
    regular_known_departures BIGINT CHECK (regular_known_departures >= 0),
    distinct_routes BIGINT CHECK (distinct_routes >= 0),
    CHECK ((calendar_covered AND regular_known_departures IS NOT NULL AND distinct_routes IS NOT NULL)
        OR (NOT calendar_covered AND regular_known_departures IS NULL AND distinct_routes IS NULL)),
    PRIMARY KEY (analysis_id, dataset_id, service_date, stop_id),
    FOREIGN KEY (analysis_id, dataset_id, service_date)
        REFERENCES gold.analysis_days(analysis_id, dataset_id, service_date),
    FOREIGN KEY (dataset_id, stop_id) REFERENCES silver.stops(dataset_id, stop_id)
);

CREATE TABLE gold.route_stop_hourly (
    analysis_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    service_date DATE NOT NULL,
    route_id TEXT NOT NULL,
    stop_id TEXT NOT NULL,
    direction_id SMALLINT CHECK (direction_id IN (0, 1)),
    service_hour BIGINT NOT NULL CHECK (service_hour >= 0),
    departure_count BIGINT NOT NULL CHECK (departure_count > 0),
    approximate_departures BIGINT NOT NULL,
    UNIQUE NULLS NOT DISTINCT
        (analysis_id, dataset_id, service_date, route_id, stop_id, direction_id, service_hour),
    FOREIGN KEY (analysis_id, dataset_id, service_date)
        REFERENCES gold.analysis_days(analysis_id, dataset_id, service_date),
    FOREIGN KEY (dataset_id, route_id) REFERENCES silver.routes(dataset_id, route_id),
    FOREIGN KEY (dataset_id, stop_id) REFERENCES silver.stops(dataset_id, stop_id)
);

CREATE TABLE gold.route_stop_headways (
    analysis_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    service_date DATE NOT NULL,
    route_id TEXT NOT NULL,
    stop_id TEXT NOT NULL,
    direction_id SMALLINT CHECK (direction_id IN (0, 1)),
    departure_count BIGINT NOT NULL,
    interval_count BIGINT NOT NULL,
    avg_seconds NUMERIC,
    median_seconds DOUBLE PRECISION,
    p90_seconds DOUBLE PRECISION,
    UNIQUE NULLS NOT DISTINCT
        (analysis_id, dataset_id, service_date, route_id, stop_id, direction_id),
    FOREIGN KEY (analysis_id, dataset_id, service_date)
        REFERENCES gold.analysis_days(analysis_id, dataset_id, service_date),
    FOREIGN KEY (dataset_id, route_id) REFERENCES silver.routes(dataset_id, route_id),
    FOREIGN KEY (dataset_id, stop_id) REFERENCES silver.stops(dataset_id, stop_id)
);

CREATE TABLE gold.service_span (
    analysis_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    service_date DATE NOT NULL,
    route_id TEXT NOT NULL,
    stop_id TEXT NOT NULL,
    direction_id SMALLINT CHECK (direction_id IN (0, 1)),
    first_departure_seconds BIGINT,
    last_departure_seconds BIGINT,
    observation_count BIGINT NOT NULL,
    regular_event_count BIGINT NOT NULL,
    missing_regular_departures BIGINT NOT NULL,
    approximate_departures BIGINT NOT NULL,
    known_regular_ratio NUMERIC,
    UNIQUE NULLS NOT DISTINCT
        (analysis_id, dataset_id, service_date, route_id, stop_id, direction_id),
    FOREIGN KEY (analysis_id, dataset_id, service_date)
        REFERENCES gold.analysis_days(analysis_id, dataset_id, service_date),
    FOREIGN KEY (dataset_id, route_id) REFERENCES silver.routes(dataset_id, route_id),
    FOREIGN KEY (dataset_id, stop_id) REFERENCES silver.stops(dataset_id, stop_id)
);

CREATE TABLE gold.coverage_daily (
    analysis_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    service_date DATE NOT NULL,
    calendar_covered BOOLEAN NOT NULL,
    total_events BIGINT,
    known_arrivals BIGINT,
    missing_arrivals BIGINT,
    known_departures BIGINT,
    missing_departures BIGINT,
    regular_events BIGINT,
    regular_known_departures BIGINT,
    regular_missing_departures BIGINT,
    no_pickup_events BIGINT,
    on_request_events BIGINT,
    pickup_type_2_events BIGINT,
    pickup_type_3_events BIGINT,
    exact_timepoint_events BIGINT,
    approximate_timepoint_events BIGINT,
    approximate_regular_departures BIGINT,
    known_arrival_ratio NUMERIC,
    known_departure_ratio NUMERIC,
    known_regular_departure_ratio NUMERIC,
    PRIMARY KEY (analysis_id, dataset_id, service_date),
    FOREIGN KEY (analysis_id, dataset_id, service_date)
        REFERENCES gold.analysis_days(analysis_id, dataset_id, service_date)
);

CREATE VIEW gold.route_catalog AS
SELECT r.*, a.agency_name, a.agency_timezone
FROM silver.routes r
JOIN silver.agency a ON a.dataset_id = r.dataset_id AND a._agency_key = r._agency_key;

CREATE VIEW gold.stop_catalog AS SELECT * FROM silver.stops;
