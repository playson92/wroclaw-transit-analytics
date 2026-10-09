CREATE SCHEMA explorer;

-- Owner-backed views expose only the columns needed by the explorer, not silver grants.
CREATE VIEW explorer.routes AS
SELECT r.dataset_id, r.route_id, r.agency_id, a.agency_name, r.route_short_name,
       r.route_long_name, r.route_type
FROM silver.routes r JOIN silver.agency a USING (dataset_id, _agency_key);
CREATE VIEW explorer.stops AS
SELECT dataset_id, stop_id, stop_name, stop_lat, stop_lon, location_type FROM silver.stops;
CREATE VIEW explorer.calendar AS
SELECT dataset_id, service_id, monday, tuesday, wednesday, thursday, friday, saturday,
       sunday, start_date, end_date FROM silver.calendar;
CREATE VIEW explorer.calendar_dates AS
SELECT dataset_id, service_id, date, exception_type FROM silver.calendar_dates;
CREATE VIEW explorer.stop_times AS
SELECT dataset_id, trip_id, stop_id, stop_sequence, arrival_seconds, departure_seconds,
       pickup_type, drop_off_type, timepoint FROM silver.stop_times;
CREATE VIEW explorer.trips AS
SELECT t.dataset_id, t.trip_id, t.route_id, t.service_id, t.direction_id, t.trip_headsign,
       NULLIF(t.extra_fields->>'shape_id','') AS shape_id,
       NULLIF(t.extra_fields->>'variant_id','') AS source_variant_id,
       t.extra_fields->>'vehicle_id' AS scheduled_vehicle_type_id,
       t.extra_fields->>'brigade_id' AS scheduled_brigade_id,
       b.start_seconds, b.end_seconds,
       md5(jsonb_build_array(t.direction_id, t.trip_headsign, t.extra_fields->>'shape_id',
           t.extra_fields->>'variant_id', b.stop_pattern)::text) AS variant_key
FROM silver.trips t
CROSS JOIN LATERAL (
    SELECT (array_agg(COALESCE(departure_seconds,arrival_seconds) ORDER BY stop_sequence))[1]
               AS start_seconds,
           (array_agg(COALESCE(arrival_seconds,departure_seconds) ORDER BY stop_sequence DESC))[1]
               AS end_seconds,
           array_agg(stop_id ORDER BY stop_sequence) AS stop_pattern
    FROM silver.stop_times s WHERE s.dataset_id=t.dataset_id AND s.trip_id=t.trip_id
) b;

CREATE UNIQUE INDEX datasets_source_identity ON meta.datasets(dataset_id, source_sha256);
CREATE TABLE explorer.geometry_imports (
    dataset_id TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    importer_version TEXT NOT NULL CHECK (importer_version='wta-shapes-v1'),
    status TEXT NOT NULL CHECK (status IN ('complete','absent')),
    point_count BIGINT NOT NULL CHECK (point_count >= 0),
    imported_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (dataset_id,source_sha256),
    FOREIGN KEY (dataset_id,source_sha256) REFERENCES meta.datasets(dataset_id,source_sha256)
);
CREATE TABLE explorer.shape_points (
    dataset_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    shape_id TEXT NOT NULL,
    shape_pt_sequence BIGINT NOT NULL CHECK (shape_pt_sequence >= 0),
    latitude DOUBLE PRECISION NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    PRIMARY KEY (dataset_id,source_sha256,shape_id,shape_pt_sequence),
    FOREIGN KEY (dataset_id,source_sha256)
        REFERENCES explorer.geometry_imports(dataset_id,source_sha256) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX explorer_trip_route_service ON silver.trips(dataset_id,route_id,service_id);
CREATE INDEX explorer_stop_departures ON silver.stop_times(dataset_id,stop_id,departure_seconds);
