"""Bounded reader queries. Reuse the exact gold service-calendar inclusion/exclusion SQL."""

from datetime import date
from importlib.resources import files

from ..dashboard.data import DashboardError, reader, rows


def active_services_sql():
    original = (
        files("wroclaw_transit_analytics.analytics").joinpath("sql/services.sql").read_text("utf-8")
    )
    select = original.split(" AS\n", 1)[1]
    return (
        "WITH wta_context AS (SELECT %(dataset_id)s::text AS dataset_id), "
        "wta_days AS (SELECT %(day)s::date AS service_date), active AS ("
        + select.replace("silver.calendar_dates", "explorer.calendar_dates").replace(
            "silver.calendar", "explorer.calendar"
        )
        + ") "
    )


ACTIVE_TRIPS = (
    "FROM explorer.trips t WHERE t.dataset_id=%(dataset_id)s "
    "AND t.route_id=%(route)s AND t.service_id IN (SELECT service_id FROM active) "
)


def metadata(dataset):
    with reader() as conn:
        result = conn.execute(
            "SELECT dataset_id,data_kind,source_sha256,provenance,capabilities,loaded_at "
            "FROM meta.datasets WHERE dataset_id=%s AND status='complete'",
            (dataset,),
        ).fetchone()
        if result is None:
            raise DashboardError("Brak wybranego kompletnego snapshotu.")
        bounds = conn.execute(
            "SELECT min(first_day) AS start_date,max(last_day) AS end_date FROM ("
            "SELECT start_date AS first_day,end_date AS last_day FROM explorer.calendar WHERE dataset_id=%s "
            "UNION ALL SELECT date,date FROM explorer.calendar_dates WHERE dataset_id=%s) bounds",
            (dataset, dataset),
        ).fetchone()
        return {**result, **bounds}


def fetch(kind, dataset, day: date | None = None, route=None, variant=None, trip=None, stop=None):
    if kind != "routes" and not isinstance(day, date):
        raise DashboardError("Wybierz poprawny dzień usługowy.")
    p = {
        "dataset_id": dataset,
        "day": day,
        "route": route,
        "variant": variant,
        "trip": trip,
        "stop": stop,
    }
    active = active_services_sql()
    with reader() as conn:
        if kind == "routes":
            return rows(
                conn,
                "SELECT * FROM explorer.routes WHERE dataset_id=%(dataset_id)s "
                "ORDER BY route_short_name,agency_id,route_id",
                p,
                limit=2000,
            )
        if kind == "active_routes":
            return rows(
                conn,
                active + "SELECT DISTINCT route_id FROM explorer.trips "
                "WHERE dataset_id=%(dataset_id)s AND service_id IN (SELECT service_id FROM active)",
                p,
                limit=2000,
            )
        if kind == "variants":
            return rows(
                conn,
                active + "SELECT variant_key,trip_headsign,direction_id,shape_id,"
                "source_variant_id,count(*) AS trip_count,min(start_seconds) AS first_seconds "
                + ACTIVE_TRIPS
                + "GROUP BY variant_key,trip_headsign,direction_id,shape_id,source_variant_id "
                "ORDER BY direction_id NULLS FIRST,first_seconds NULLS LAST,variant_key",
                p,
                limit=500,
            )
        if kind == "trips":
            return rows(
                conn,
                active + "SELECT t.* " + ACTIVE_TRIPS + "AND variant_key=%(variant)s "
                "ORDER BY start_seconds NULLS LAST,trip_id",
                p,
                limit=2000,
            )
        if kind == "stops":
            return rows(
                conn,
                active + "SELECT s.*,c.stop_name,c.stop_lat,c.stop_lon,c.location_type "
                "FROM explorer.stop_times s JOIN explorer.stops c USING(dataset_id,stop_id) "
                "WHERE s.dataset_id=%(dataset_id)s AND s.trip_id=%(trip)s AND EXISTS (SELECT 1 "
                + ACTIVE_TRIPS
                + "AND t.trip_id=s.trip_id AND t.variant_key=%(variant)s) "
                "ORDER BY s.stop_sequence",
                p,
                limit=1000,
            )
        if kind == "geometry":
            return rows(
                conn,
                active + "SELECT g.latitude,g.longitude,g.shape_pt_sequence "
                "FROM explorer.shape_points g JOIN meta.datasets d USING(dataset_id,source_sha256) "
                "WHERE g.dataset_id=%(dataset_id)s AND g.shape_id=(SELECT shape_id "
                + ACTIVE_TRIPS
                + "AND trip_id=%(trip)s AND variant_key=%(variant)s) "
                "ORDER BY g.shape_pt_sequence",
                p,
                limit=20000,
            )
        if kind == "departures":
            return rows(
                conn,
                active + "SELECT s.trip_id,s.stop_sequence,s.arrival_seconds,s.departure_seconds,"
                "s.pickup_type,s.timepoint,t.trip_headsign,t.direction_id,t.variant_key "
                "FROM explorer.stop_times s JOIN explorer.trips t USING(dataset_id,trip_id) "
                "WHERE s.dataset_id=%(dataset_id)s AND s.stop_id=%(stop)s AND t.route_id=%(route)s "
                "AND t.service_id IN (SELECT service_id FROM active) "
                "ORDER BY s.departure_seconds NULLS LAST,s.trip_id,s.stop_sequence",
                p,
                limit=5000,
            )
        raise DashboardError("Nieznane zapytanie przeglądarki kursów.")
