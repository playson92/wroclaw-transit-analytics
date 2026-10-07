"""SQL execution, admission, bounds and append-only publication in one transaction."""

import hashlib
import re
from importlib.resources import files

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from ..database.connection import connect
from ..database.migrations import migration_files
from ..preparation.source import MODEL_VERSION
from .contract import METRICS_VERSION, AnalyticsError, AnalyticsResult, analysis_id, dates

OUTPUTS = {
    "analysis_days": "write_days.sql",
    "active_services": "write_services.sql",
    "route_daily": "write_routes.sql",
    "stop_daily": "write_stops.sql",
    "route_stop_hourly": "write_hourly.sql",
    "route_stop_headways": "write_headways.sql",
    "service_span": "write_spans.sql",
    "coverage_daily": "write_coverage.sql",
}


def sql_text(name: str) -> str:
    return (
        files("wroclaw_transit_analytics.analytics")
        .joinpath("sql", name)
        .read_text(encoding="utf-8")
    )


def rules_digest() -> str:
    root = files("wroclaw_transit_analytics.analytics").joinpath("sql")
    digest = hashlib.sha256(METRICS_VERSION.encode())
    for path in sorted(root.iterdir(), key=lambda value: value.name):
        if path.name.endswith(".sql"):
            digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _execute(connection, name, parameters=None):
    return connection.execute(sql_text(name), parameters)


def _admit(connection, identity):
    if connection.execute("SELECT to_regclass('meta.analyses')").fetchone()[0] is None:
        raise AnalyticsError("MIGRATIONS_REQUIRED: wykonaj db-init i ponowne granty loadera.")
    actual = dict(connection.execute("SELECT version, checksum FROM meta.migrations"))
    expected = {name: checksum for name, checksum, _ in migration_files()}
    if actual != expected:
        raise AnalyticsError("MIGRATIONS_REQUIRED: niezgodna historia/checksum; wykonaj db-init.")
    dataset = connection.execute(
        "SELECT logical_fingerprint, status, capabilities, data_kind, model_version, quality_report "
        "FROM meta.datasets WHERE dataset_id=%s",
        (identity,),
    ).fetchone()
    if dataset is None:
        raise AnalyticsError("DATASET_NOT_FOUND: najpierw db-load wskazanego datasetu.")
    fingerprint, status, capabilities, data_kind, model, quality = dataset
    if status != "complete" or model != MODEL_VERSION:
        raise AnalyticsError("INCOMPLETE_DATASET: wymagany kompletny wta-silver-v1.")
    if not isinstance(capabilities, dict) or not isinstance(capabilities.get("frequencies"), dict):
        raise AnalyticsError("UNSUPPORTED_CAPABILITIES: brak poprawnych metadanych capabilities.")
    frequencies = capabilities["frequencies"]
    count = frequencies.get("row_count")
    if type(count) is int and count > 0:
        raise AnalyticsError("UNSUPPORTED_FREQUENCIES: v1 nie rozwija szablonów frequencies.")
    if (
        capabilities.get("quantitative_gold_supported") is not True
        or type(count) is not int
        or count != 0
    ):
        raise AnalyticsError(
            "UNSUPPORTED_CAPABILITIES: brak potwierdzonej obsługi ilościowego gold."
        )
    context = {
        "data_kind": data_kind,
        "model_version": model,
        "agency_timezones": [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT agency_timezone FROM silver.agency WHERE dataset_id=%s ORDER BY 1",
                (identity,),
            )
        ],
        "static_silver_quality_scope": quality.get("scope"),
        "static_silver_time_coverage": quality.get("time_coverage"),
        "capabilities": capabilities,
    }
    return fingerprint, context


def _inputs(connection, parameters, limits):
    _execute(connection, "context.sql", parameters)
    _execute(connection, "days.sql")
    _execute(connection, "services.sql")
    _execute(connection, "instances.sql")
    events, instances, grid_rows = _execute(connection, "estimate.sql").fetchone()
    if (
        events > limits["max_events"]
        or instances > limits["max_events"]
        or grid_rows > limits["max_grid_rows"]
    ):
        raise AnalyticsError(
            f"LIMIT_EXCEEDED: events={events}, trip_instances={instances}, grid_rows={grid_rows}; "
            "zmniejsz zakres lub jawnie podnieś limity. Brak częściowego gold."
        )
    connection.execute("ANALYZE wta_instances")
    _execute(connection, "events.sql")
    connection.execute("ANALYZE wta_events")
    _execute(connection, "departures.sql")
    _execute(connection, "coverage.sql")
    return _execute(connection, "summary.sql").fetchone()[0]


def _counts(connection, identity):
    return {
        name: connection.execute(
            sql.SQL("SELECT count(*) FROM {} WHERE analysis_id=%s").format(
                sql.Identifier("gold", name)
            ),
            (identity,),
        ).fetchone()[0]
        for name in OUTPUTS
    }


def analyze(
    dataset_id,
    start_date,
    end_date,
    database_url=None,
    *,
    max_days=31,
    max_events=5_000_000,
    max_grid_rows=5_000_000,
    timeout_seconds=120,
):
    start, end = dates(start_date, end_date)
    if not isinstance(dataset_id, str) or not re.fullmatch(r"gtfs_[0-9a-f]{64}", dataset_id):
        raise AnalyticsError("INVALID_DATASET_ID: wymagany pełny identyfikator gtfs_<sha256>.")
    limits = {
        "max_days": max_days,
        "max_events": max_events,
        "max_grid_rows": max_grid_rows,
        "timeout_seconds": timeout_seconds,
    }
    if (
        any(type(value) is not int or value <= 0 for value in limits.values())
        or max_days > 3660
        or timeout_seconds > 3600
    ):
        raise AnalyticsError(
            "INVALID_LIMITS: dodatnie liczby całkowite, max-days <= 3660, timeout <= 3600 s."
        )
    if (end - start).days + 1 > max_days:
        raise AnalyticsError("LIMIT_EXCEEDED: zakres przekracza max-days (domyślnie 31).")
    identity = analysis_id(dataset_id, start, end)
    rules = rules_digest()
    parameters = {
        "dataset_id": dataset_id,
        "analysis_id": identity,
        "start_date": start,
        "end_date": end,
    }
    key = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big", signed=True)
    with connect(database_url) as connection, connection.transaction():
        try:
            connection.execute(
                "SELECT set_config('statement_timeout', %s, true)", (str(timeout_seconds * 1000),)
            )
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
            fingerprint, source_context = _admit(connection, dataset_id)
            existing = connection.execute(
                "SELECT dataset_id, metrics_version, start_date, end_date, input_fingerprint, "
                "rules_sha256, status, coverage, source_context FROM meta.analyses WHERE analysis_id=%s",
                (identity,),
            ).fetchone()
            if existing:
                if existing[:7] != (
                    dataset_id,
                    METRICS_VERSION,
                    start,
                    end,
                    fingerprint,
                    rules,
                    "complete",
                ):
                    raise AnalyticsError(
                        "CONFLICT: istniejąca analiza ma inny fingerprint, reguły lub parametry."
                    )
                return AnalyticsResult(
                    "ALREADY_ANALYZED",
                    identity,
                    dataset_id,
                    METRICS_VERSION,
                    start.isoformat(),
                    end.isoformat(),
                    _counts(connection, identity),
                    existing[7],
                    existing[8],
                )
            coverage = _inputs(connection, parameters, limits)
            connection.execute(
                "INSERT INTO meta.analyses (analysis_id, dataset_id, metrics_version, start_date, "
                "end_date, input_fingerprint, rules_sha256, status, coverage, source_context, execution_limits) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'complete',%s,%s,%s)",
                (
                    identity,
                    dataset_id,
                    METRICS_VERSION,
                    start,
                    end,
                    fingerprint,
                    rules,
                    Jsonb(coverage),
                    Jsonb(source_context),
                    Jsonb(limits),
                ),
            )
            counts = {
                name: _execute(connection, resource).rowcount for name, resource in OUTPUTS.items()
            }
        except psycopg.errors.QueryCanceled:
            raise AnalyticsError(
                "TIMEOUT: przekroczono limit czasu; nowa analiza została wycofana."
            ) from None
    return AnalyticsResult(
        "ANALYZED",
        identity,
        dataset_id,
        METRICS_VERSION,
        start.isoformat(),
        end.isoformat(),
        counts,
        coverage,
        source_context,
    )
