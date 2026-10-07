"""Disk-backed global checks; SQLite is a private disposable index, not a data layer."""

import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

from .contract import DAYS, SPECS, Diagnostics, python_value
from .source import SOURCE_RECORD

INDEX_COLUMNS = {
    "agency": ("_agency_key", "agency_id", "agency_timezone"),
    "stops": ("stop_id", "parent_station", "location_type"),
    "routes": ("route_id", "_agency_key"),
    "trips": ("trip_id", "route_id", "service_id", "direction_id"),
    "stop_times": (
        "trip_id",
        "stop_id",
        "stop_sequence",
        "arrival_seconds",
        "departure_seconds",
        "pickup_type",
        "drop_off_type",
        "timepoint",
    ),
    "calendar": ("service_id", "start_date", "end_date", *DAYS),
    "calendar_dates": ("service_id", "date", "exception_type"),
}
UNIQUE_KEYS = {
    "agency": ("_agency_key",),
    "stops": ("stop_id",),
    "routes": ("route_id",),
    "trips": ("trip_id",),
    "stop_times": ("trip_id", "stop_sequence"),
    "calendar": ("service_id",),
    "calendar_dates": ("service_id", "date"),
}


class QualityIndex:
    def __init__(self, path: Path, diagnostics: Diagnostics) -> None:
        self.path = path
        self.diagnostics = diagnostics
        self.connection = sqlite3.connect(path)
        # Only private scratch data: bounded page cache and disk-based sorts.
        self.connection.execute("PRAGMA cache_size=-8192")
        self.connection.execute("PRAGMA temp_store=FILE")
        for table, columns in INDEX_COLUMNS.items():
            definitions = [f'"{SOURCE_RECORD}" INTEGER NOT NULL']
            for column in columns:
                spec = SPECS[table].get(column)
                integer = (spec is not None and spec.kind == "integer") or column.endswith(
                    "_seconds"
                )
                definitions.append(f'"{column}" {"INTEGER" if integer else "TEXT"}')
            self.connection.execute(f'CREATE TABLE "{table}" ({", ".join(definitions)})')

    def add(self, table: str, frame: pd.DataFrame) -> None:
        columns = (SOURCE_RECORD, *INDEX_COLUMNS[table])
        fields = ", ".join(f'"{column}"' for column in columns)

        def rows():
            for row in frame.loc[:, list(columns)].itertuples(index=False, name=None):
                values = [python_value(value) for value in row]
                yield tuple(
                    value.isoformat() if isinstance(value, date) else value for value in values
                )

        self.connection.executemany(
            f'INSERT INTO "{table}" ({fields}) VALUES ({", ".join("?" for _ in columns)})', rows()
        )

    def agency_keys(self) -> tuple[str, ...]:
        return tuple(
            row[0] for row in self.connection.execute('SELECT DISTINCT "_agency_key" FROM agency')
        )

    def _check(self, code: str, table: str, column: str, query: str) -> None:
        count = self.connection.execute(f"SELECT COUNT(*) FROM ({query})").fetchone()[0]
        if not count:
            return
        samples = (
            {"record": int(row[0]), "value": str(row[1])[:100]}
            for row in self.connection.execute(query + " LIMIT 5")
        )
        self.diagnostics.add(code, table, column, count, samples)

    def check(self) -> dict:
        self.connection.commit()
        for table, keys in UNIQUE_KEYS.items():
            key_sql = ", ".join(f'"{key}"' for key in keys)
            known = " AND ".join(f'"{key}" IS NOT NULL' for key in keys)
            self.connection.execute(f'CREATE INDEX "dq_{table}_key" ON "{table}" ({key_sql})')
            self._check(
                "duplicate_key",
                table,
                ",".join(keys),
                f'SELECT MIN("{SOURCE_RECORD}"), {key_sql} FROM "{table}" '
                f"WHERE {known} GROUP BY {key_sql} HAVING COUNT(*) > 1",
            )
        for table, column, target, key in (
            ("routes", "_agency_key", "agency", "_agency_key"),
            ("trips", "route_id", "routes", "route_id"),
            ("stop_times", "trip_id", "trips", "trip_id"),
            ("stop_times", "stop_id", "stops", "stop_id"),
            ("stops", "parent_station", "stops", "stop_id"),
        ):
            self._check(
                "orphan_reference",
                table,
                column,
                f'SELECT s."{SOURCE_RECORD}", s."{column}" FROM "{table}" s '
                f'LEFT JOIN "{target}" t ON s."{column}" = t."{key}" '
                f'WHERE s."{column}" IS NOT NULL AND t."{key}" IS NULL',
            )
        self._check(
            "unknown_service",
            "trips",
            "service_id",
            f'SELECT t."{SOURCE_RECORD}", t.service_id FROM trips t '
            "LEFT JOIN (SELECT service_id FROM calendar UNION SELECT service_id "
            "FROM calendar_dates) c USING (service_id) "
            "WHERE t.service_id IS NOT NULL AND c.service_id IS NULL",
        )
        self._check(
            "calendar_range",
            "calendar",
            "start_date,end_date",
            f'SELECT "{SOURCE_RECORD}", service_id FROM calendar WHERE start_date > end_date',
        )
        self._check(
            "required_parent",
            "stops",
            "parent_station",
            f'SELECT "{SOURCE_RECORD}", stop_id FROM stops '
            "WHERE location_type IN (2,3,4) AND parent_station IS NULL",
        )
        self._check(
            "invalid_parent_type",
            "stops",
            "parent_station",
            f'SELECT s."{SOURCE_RECORD}", s.stop_id FROM stops s '
            "LEFT JOIN stops p ON s.parent_station = p.stop_id "
            "WHERE (s.location_type=1 AND s.parent_station IS NOT NULL) "
            "OR (s.location_type IN (0,2,3) AND p.location_type<>1) "
            "OR (s.location_type=4 AND p.location_type<>0)",
        )
        self._check(
            "invalid_event_location",
            "stop_times",
            "stop_id",
            f'SELECT e."{SOURCE_RECORD}", e.stop_id FROM stop_times e '
            "JOIN stops s USING (stop_id) WHERE s.location_type<>0",
        )
        self._check(
            "missing_exact_time",
            "stop_times",
            "arrival_time,departure_time",
            f'SELECT "{SOURCE_RECORD}", trip_id FROM stop_times WHERE timepoint=1 '
            "AND (arrival_seconds IS NULL OR departure_seconds IS NULL)",
        )
        self._check(
            "missing_endpoint_arrival",
            "stop_times",
            "arrival_time",
            f'SELECT s."{SOURCE_RECORD}", s.trip_id FROM stop_times s JOIN '
            "(SELECT trip_id, MIN(stop_sequence) lo, MAX(stop_sequence) hi "
            "FROM stop_times GROUP BY trip_id) t USING (trip_id) "
            "WHERE s.arrival_seconds IS NULL AND s.stop_sequence IN (t.lo,t.hi)",
        )
        self._check(
            "time_decreases",
            "stop_times",
            "arrival_time,departure_time",
            f'SELECT "{SOURCE_RECORD}", trip_id FROM ('
            f'SELECT "{SOURCE_RECORD}", trip_id, seconds, LAG(seconds) OVER '
            "(PARTITION BY trip_id ORDER BY stop_sequence, phase) AS previous FROM ("
            f'SELECT "{SOURCE_RECORD}", trip_id, stop_sequence, 0 phase, arrival_seconds seconds '
            "FROM stop_times WHERE arrival_seconds IS NOT NULL AND stop_sequence IS NOT NULL "
            "UNION ALL "
            f'SELECT "{SOURCE_RECORD}", trip_id, stop_sequence, 1 phase, departure_seconds seconds '
            "FROM stop_times WHERE departure_seconds IS NOT NULL AND stop_sequence IS NOT NULL"
            ")) WHERE seconds < previous",
        )
        agency_count, missing_ids, zones = self.connection.execute(
            "SELECT COUNT(*), SUM(agency_id IS NULL), COUNT(DISTINCT agency_timezone) FROM agency"
        ).fetchone()
        if agency_count > 1 and missing_ids:
            self.diagnostics.add("multi_agency_missing_id", "agency", "agency_id", missing_ids)
        if zones > 1:
            self.diagnostics.add("multiple_agency_timezones", "agency", "agency_timezone", zones)
        counts = self.connection.execute(
            "SELECT COUNT(*), SUM(arrival_seconds IS NOT NULL), "
            "SUM(departure_seconds IS NOT NULL), "
            "SUM(pickup_type=0), SUM(pickup_type=1), SUM(pickup_type IN (2,3)), "
            "SUM(timepoint=0), SUM(pickup_type=0 AND departure_seconds IS NOT NULL) FROM stop_times"
        ).fetchone()
        total, arrival, departure, regular, excluded, on_request, approximate, known_regular = (
            value or 0 for value in counts
        )
        self.diagnostics.add(
            "unknown_departure",
            "stop_times",
            "departure_time",
            total - departure,
            severity="warning",
        )
        self.diagnostics.add(
            "unknown_arrival", "stop_times", "arrival_time", total - arrival, severity="warning"
        )
        domain = self.connection.execute(
            "SELECT MIN(value), MAX(value) FROM ("
            "SELECT start_date value FROM calendar UNION ALL SELECT end_date FROM calendar "
            "UNION ALL SELECT date FROM calendar_dates)"
        ).fetchone()
        return {
            "service_date_range": {"start_date": domain[0], "end_date": domain[1]},
            "time_coverage": {
                "stop_time_records": total,
                "known_arrivals": arrival,
                "known_departures": departure,
                "departure_ratio": departure / total if total else None,
                "regular_pickup_records": regular,
                "known_regular_departures": known_regular,
                "no_pickup_records": excluded,
                "on_request_pickup_records": on_request,
                "approximate_timepoint_records": approximate,
            },
            "agency_count": agency_count,
            "unknown_directions": self.connection.execute(
                "SELECT COUNT(*) FROM trips WHERE direction_id IS NULL"
            ).fetchone()[0],
        }

    def close(self) -> None:
        self.connection.close()
        self.path.unlink(missing_ok=True)
