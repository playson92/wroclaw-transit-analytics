"""Bounded parameterized presentation queries; one closed read-only connection per fetch."""

import hashlib
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from importlib.resources import files

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from ..analytics.contract import METRICS_VERSION

MAX_ROWS = 20_000


class DashboardError(Exception):
    """Only safe public messages may cross the UI boundary."""


@dataclass(frozen=True)
class Context:
    dataset: str
    analysis: str
    start: date
    end: date
    route: str | None = None
    stop: str | None = None
    direction: str = "ALL"

    def parameters(self):
        if self.start > self.end or self.direction not in ("ALL", "NULL", "0", "1"):
            raise DashboardError("Niepoprawny zakres dat lub kierunek.")
        return vars(self)


def source_key():
    value = os.environ.get("READONLY_DATABASE_URL", "")
    if not value.strip():
        raise DashboardError("Ustaw READONLY_DATABASE_URL dla roli wta_reader.")
    # Include credentials in the digest to prevent stale cache after credential rotation.
    return hashlib.sha256(value.encode()).hexdigest()


@contextmanager
def reader():
    source_key()
    try:
        settings = conninfo_to_dict(os.environ["READONLY_DATABASE_URL"])
        if settings.get("user") != "wta_reader":
            raise DashboardError("READONLY_DATABASE_URL musi wskazywać rolę wta_reader.")
        if not all(settings.get(key) for key in ("host", "dbname", "password")):
            raise DashboardError(
                "READONLY_DATABASE_URL wymaga hosta, bazy i własnego hasła readera."
            )
        with psycopg.connect(
            os.environ["READONLY_DATABASE_URL"],
            port=settings.get("port", "5432"),
            connect_timeout=5,
            row_factory=dict_row,
        ) as conn:
            if conn.info.server_version // 10000 != 17:
                raise DashboardError("Dashboard wymaga PostgreSQL 17.")
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SELECT set_config('statement_timeout','15000',true)")
            conn.execute("SELECT set_config('lock_timeout','3000',true)")
            if conn.execute("SELECT current_user AS role").fetchone()["role"] != "wta_reader":
                raise DashboardError("READONLY_DATABASE_URL musi wskazywać rolę wta_reader.")
            yield conn
    except (psycopg.Error, ValueError, UnicodeError):
        raise DashboardError(
            "Baza niedostępna lub konfiguracja/granty niepoprawne. Sprawdź połączenie i db-init."
        ) from None


def rows(conn, query, parameters=None, limit=MAX_ROWS):
    # Queries are internal static SQL. Limit is applied on server, never caller SQL.
    values = {**(parameters or {}), "fetch_limit": limit + 1}
    result = conn.execute("SELECT * FROM (" + query + ") AS bounded LIMIT %(fetch_limit)s", values)
    result = result.fetchmany(limit + 1)
    if len(result) > limit:
        raise DashboardError("Przekroczono limit widoku; zmniejsz zakres dat lub filtry.")
    return result


def sql_text(name):
    if name not in ("overview.sql", "group_daily.sql"):
        raise DashboardError("Nieznane zapytanie dashboardu.")
    return files("wroclaw_transit_analytics.dashboard").joinpath("sql", name).read_text("utf-8")


def catalog():
    with reader() as conn:
        datasets = rows(
            conn,
            "SELECT dataset_id, data_kind, loaded_at FROM meta.datasets "
            "WHERE status='complete' ORDER BY loaded_at DESC, dataset_id",
            limit=1000,
        )
        analyses = rows(
            conn,
            "SELECT analysis_id, dataset_id, start_date, end_date, metrics_version "
            "FROM meta.analyses WHERE status='complete' AND metrics_version=%(version)s "
            "ORDER BY created_at DESC, analysis_id",
            {"version": METRICS_VERSION},
            limit=2000,
        )
    return {"datasets": datasets, "analyses": analyses}


BASE = "dataset_id=%(dataset)s AND analysis_id=%(analysis)s AND service_date BETWEEN %(start)s AND %(end)s"
GROUP = (
    BASE + " AND route_id=%(route)s AND stop_id=%(stop)s AND "
    "(%(direction)s='ALL' OR (%(direction)s='NULL' AND direction_id IS NULL) "
    "OR direction_id::text=%(direction)s)"
)


def scoped(alias):
    return (
        f"{alias}.dataset_id=%(dataset)s AND {alias}.analysis_id=%(analysis)s "
        f"AND {alias}.service_date BETWEEN %(start)s AND %(end)s"
    )


def fetch(view, context):
    p = context.parameters()
    with reader() as conn:
        analysis = conn.execute(
            "SELECT * FROM meta.analyses WHERE dataset_id=%(dataset)s AND analysis_id=%(analysis)s "
            "AND metrics_version=%(version)s AND status='complete'",
            {**p, "version": METRICS_VERSION},
        ).fetchone()
        if analysis is None:
            raise DashboardError("Brak kompletnej analizy gold dla wybranego snapshotu.")
        if context.start < analysis["start_date"] or context.end > analysis["end_date"]:
            raise DashboardError("Filtr dat musi mieścić się w wybranej analizie.")
        if view == "overview":
            return {
                "kpi": rows(conn, sql_text("overview.sql"), p)[0],
                "routes": rows(
                    conn,
                    "SELECT r.route_id,c.route_short_name,sum(r.trip_count) AS trips "
                    "FROM gold.route_daily r JOIN gold.route_catalog c USING(dataset_id,route_id) "
                    "WHERE "
                    + scoped("r")
                    + " GROUP BY r.route_id,c.route_short_name ORDER BY trips DESC NULLS LAST,r.route_id LIMIT 20",
                    p,
                ),
                "stops": rows(
                    conn,
                    "SELECT s.stop_id,c.stop_name,sum(s.regular_known_departures) AS departures "
                    "FROM gold.stop_daily s JOIN gold.stop_catalog c USING(dataset_id,stop_id) "
                    "WHERE "
                    + scoped("s")
                    + " GROUP BY s.stop_id,c.stop_name ORDER BY departures DESC NULLS LAST,s.stop_id LIMIT 20",
                    p,
                ),
                "hourly": rows(
                    conn,
                    "SELECT service_hour,sum(departure_count) AS departures "
                    "FROM gold.route_stop_hourly WHERE "
                    + BASE
                    + " GROUP BY service_hour ORDER BY service_hour",
                    p,
                ),
                "coverage": rows(
                    conn,
                    "SELECT * FROM gold.coverage_daily WHERE " + BASE + " ORDER BY service_date",
                    p,
                ),
            }
        if view == "filters":
            return {
                "routes": rows(
                    conn,
                    "SELECT route_id,route_short_name,route_long_name FROM gold.route_catalog "
                    "WHERE dataset_id=%(dataset)s ORDER BY route_short_name,route_id",
                    p,
                ),
                "stops": rows(
                    conn,
                    "SELECT DISTINCT s.stop_id,c.stop_name FROM gold.service_span s "
                    "JOIN gold.stop_catalog c USING(dataset_id,stop_id) WHERE "
                    + scoped("s")
                    + " AND s.route_id=%(route)s ORDER BY s.stop_id",
                    p,
                ),
                "directions": rows(
                    conn,
                    "SELECT DISTINCT direction_id FROM gold.service_span WHERE "
                    + BASE
                    + " AND route_id=%(route)s AND stop_id=%(stop)s ORDER BY direction_id NULLS FIRST",
                    p,
                ),
            }
        if view == "group":
            return {
                "daily": rows(conn, sql_text("group_daily.sql"), p),
                "hourly": rows(
                    conn,
                    "SELECT service_hour,sum(departure_count) AS departures "
                    "FROM gold.route_stop_hourly WHERE "
                    + GROUP
                    + " GROUP BY service_hour ORDER BY service_hour",
                    p,
                ),
                "headways": rows(
                    conn,
                    "SELECT service_date,direction_id,departure_count,interval_count,"
                    "avg_seconds,median_seconds,p90_seconds FROM gold.route_stop_headways WHERE "
                    + GROUP
                    + " ORDER BY service_date,direction_id NULLS FIRST",
                    p,
                ),
            }
        if view == "quality":
            return {
                "analysis": analysis,
                "dataset": conn.execute(
                    "SELECT * FROM meta.datasets WHERE dataset_id=%(dataset)s", p
                ).fetchone(),
                "coverage": rows(
                    conn,
                    "SELECT * FROM gold.coverage_daily WHERE " + BASE + " ORDER BY service_date",
                    p,
                ),
            }
        raise DashboardError("Nieznany widok dashboardu.")
