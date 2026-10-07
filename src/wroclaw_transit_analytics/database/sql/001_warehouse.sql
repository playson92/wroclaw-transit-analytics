CREATE SCHEMA silver;

CREATE TABLE meta.datasets (
    dataset_id TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    model_version TEXT NOT NULL,
    logical_fingerprint TEXT NOT NULL CHECK (logical_fingerprint ~ '^[0-9a-f]{64}$'),
    provenance JSONB NOT NULL,
    data_kind TEXT NOT NULL CHECK (data_kind IN ('real_gtfs', 'synthetic_demo')),
    capabilities JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status = 'complete'),
    source_manifest JSONB NOT NULL,
    quality_report JSONB NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE silver.agency (
    dataset_id TEXT NOT NULL REFERENCES meta.datasets(dataset_id),
    _agency_key TEXT NOT NULL,
    agency_id TEXT,
    agency_name TEXT NOT NULL,
    agency_url TEXT NOT NULL,
    agency_timezone TEXT NOT NULL,
    _wta_source_record BIGINT NOT NULL CHECK (_wta_source_record > 0),
    extra_fields JSONB NOT NULL,
    PRIMARY KEY (dataset_id, _agency_key)
);

CREATE TABLE silver.stops (
    dataset_id TEXT NOT NULL REFERENCES meta.datasets(dataset_id),
    stop_id TEXT NOT NULL,
    stop_name TEXT NOT NULL,
    stop_lat DOUBLE PRECISION CHECK (stop_lat BETWEEN -90 AND 90),
    stop_lon DOUBLE PRECISION CHECK (stop_lon BETWEEN -180 AND 180),
    location_type SMALLINT NOT NULL CHECK (location_type BETWEEN 0 AND 4),
    parent_station TEXT,
    _wta_source_record BIGINT NOT NULL CHECK (_wta_source_record > 0),
    extra_fields JSONB NOT NULL,
    PRIMARY KEY (dataset_id, stop_id),
    FOREIGN KEY (dataset_id, parent_station) REFERENCES silver.stops(dataset_id, stop_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE silver.routes (
    dataset_id TEXT NOT NULL REFERENCES meta.datasets(dataset_id),
    route_id TEXT NOT NULL,
    agency_id TEXT,
    route_short_name TEXT NOT NULL,
    route_long_name TEXT NOT NULL,
    route_type BIGINT NOT NULL CHECK (route_type >= 0),
    _agency_key TEXT NOT NULL,
    route_type_description TEXT NOT NULL,
    _wta_source_record BIGINT NOT NULL CHECK (_wta_source_record > 0),
    extra_fields JSONB NOT NULL,
    PRIMARY KEY (dataset_id, route_id),
    FOREIGN KEY (dataset_id, _agency_key) REFERENCES silver.agency(dataset_id, _agency_key)
);

CREATE TABLE silver.services (
    dataset_id TEXT NOT NULL REFERENCES meta.datasets(dataset_id),
    service_id TEXT NOT NULL,
    PRIMARY KEY (dataset_id, service_id)
);

CREATE TABLE silver.calendar (
    dataset_id TEXT NOT NULL REFERENCES meta.datasets(dataset_id),
    service_id TEXT NOT NULL,
    monday SMALLINT NOT NULL CHECK (monday IN (0, 1)),
    tuesday SMALLINT NOT NULL CHECK (tuesday IN (0, 1)),
    wednesday SMALLINT NOT NULL CHECK (wednesday IN (0, 1)),
    thursday SMALLINT NOT NULL CHECK (thursday IN (0, 1)),
    friday SMALLINT NOT NULL CHECK (friday IN (0, 1)),
    saturday SMALLINT NOT NULL CHECK (saturday IN (0, 1)),
    sunday SMALLINT NOT NULL CHECK (sunday IN (0, 1)),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    _wta_source_record BIGINT NOT NULL CHECK (_wta_source_record > 0),
    extra_fields JSONB NOT NULL,
    PRIMARY KEY (dataset_id, service_id),
    CHECK (start_date <= end_date),
    FOREIGN KEY (dataset_id, service_id) REFERENCES silver.services(dataset_id, service_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE silver.calendar_dates (
    dataset_id TEXT NOT NULL REFERENCES meta.datasets(dataset_id),
    service_id TEXT NOT NULL,
    date DATE NOT NULL,
    exception_type SMALLINT NOT NULL CHECK (exception_type IN (1, 2)),
    _wta_source_record BIGINT NOT NULL CHECK (_wta_source_record > 0),
    extra_fields JSONB NOT NULL,
    PRIMARY KEY (dataset_id, service_id, date),
    FOREIGN KEY (dataset_id, service_id) REFERENCES silver.services(dataset_id, service_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE silver.trips (
    dataset_id TEXT NOT NULL REFERENCES meta.datasets(dataset_id),
    trip_id TEXT NOT NULL,
    route_id TEXT NOT NULL,
    service_id TEXT NOT NULL,
    direction_id SMALLINT CHECK (direction_id IN (0, 1)),
    trip_headsign TEXT NOT NULL,
    _wta_source_record BIGINT NOT NULL CHECK (_wta_source_record > 0),
    extra_fields JSONB NOT NULL,
    PRIMARY KEY (dataset_id, trip_id),
    FOREIGN KEY (dataset_id, route_id) REFERENCES silver.routes(dataset_id, route_id),
    FOREIGN KEY (dataset_id, service_id) REFERENCES silver.services(dataset_id, service_id)
);

CREATE TABLE silver.stop_times (
    dataset_id TEXT NOT NULL REFERENCES meta.datasets(dataset_id),
    trip_id TEXT NOT NULL,
    stop_id TEXT NOT NULL,
    stop_sequence BIGINT NOT NULL CHECK (stop_sequence >= 0),
    arrival_time TEXT NOT NULL,
    departure_time TEXT NOT NULL,
    arrival_seconds BIGINT CHECK (arrival_seconds >= 0),
    departure_seconds BIGINT CHECK (departure_seconds >= 0),
    pickup_type SMALLINT NOT NULL CHECK (pickup_type BETWEEN 0 AND 3),
    drop_off_type SMALLINT NOT NULL CHECK (drop_off_type BETWEEN 0 AND 3),
    timepoint SMALLINT NOT NULL CHECK (timepoint IN (0, 1)),
    _wta_source_record BIGINT NOT NULL CHECK (_wta_source_record > 0),
    extra_fields JSONB NOT NULL,
    PRIMARY KEY (dataset_id, trip_id, stop_sequence),
    FOREIGN KEY (dataset_id, trip_id) REFERENCES silver.trips(dataset_id, trip_id),
    FOREIGN KEY (dataset_id, stop_id) REFERENCES silver.stops(dataset_id, stop_id)
);

CREATE INDEX routes_agency ON silver.routes(dataset_id, _agency_key);
CREATE INDEX trips_route ON silver.trips(dataset_id, route_id);
CREATE INDEX trips_service ON silver.trips(dataset_id, service_id);
CREATE INDEX stop_times_stop ON silver.stop_times(dataset_id, stop_id);
CREATE INDEX stops_parent ON silver.stops(dataset_id, parent_station);
