"""Hand-counted KPI, immutable publication, upgrade and one synthetic benchmark."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from time import perf_counter
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from tests.preparation.conftest import csv_contents

from wroclaw_transit_analytics.analytics import AnalyticsError, analysis_id, analyze, runner
from wroclaw_transit_analytics.database import initialize, load_silver
from wroclaw_transit_analytics.database.migrations import apply_migrations, migration_files
from wroclaw_transit_analytics.preparation import prepare
from wroclaw_transit_analytics.sample_data import sample_files

from .scenarios import CALENDAR_COLUMNS, benchmark_files, numerical_files

pytestmark = pytest.mark.integration


def load_files(db_url, make_raw, tmp_path, files):
    manifest = prepare(
        make_raw(files), tmp_path / ("prepared-" + uuid4().hex), batch_size=5000
    ).silver_manifest
    initialize(db_url)
    return load_silver(manifest, db_url).dataset_id


def query(db_url, statement, parameters=()):
    with psycopg.connect(db_url) as conn:
        return conn.execute(statement, parameters).fetchall()


def test_numerical_calendars_headways_pickups_and_bigint(db_url, make_raw, tmp_path):
    identity = load_files(db_url, make_raw, tmp_path, numerical_files())
    result = analyze(identity, "2026-10-01", "2026-10-05", db_url)
    assert result.status == "ANALYZED"
    assert query(
        db_url,
        "SELECT service_date, service_id FROM gold.active_services WHERE analysis_id=%s ORDER BY 1,2",
        (result.analysis_id,),
    ) == [
        (date(2026, 10, 1), "WD"),
        (date(2026, 10, 2), "WD"),
        (date(2026, 10, 2), "WE"),
        (date(2026, 10, 3), "EX"),
        (date(2026, 10, 3), "WE"),
        (date(2026, 10, 4), "WE"),
    ]
    routes = query(
        db_url,
        "SELECT service_date, route_id, trip_count FROM gold.route_daily WHERE analysis_id=%s ORDER BY 1,2",
        (result.analysis_id,),
    )
    assert [(row[1], row[2]) for row in routes if row[0] == date(2026, 10, 1)] == [
        ("R0", 0),
        ("R1", 3),
        ("R2", 1),
    ]
    assert [(row[1], row[2]) for row in routes if row[0] == date(2026, 10, 2)] == [
        ("R0", 0),
        ("R1", 4),
        ("R2", 1),
    ]
    assert all(row[2] == 0 for row in routes if row[0] == date(2026, 10, 5))
    assert query(
        db_url,
        "SELECT stop_id, regular_known_departures, distinct_routes FROM gold.stop_daily WHERE analysis_id=%s AND service_date='2026-10-01' ORDER BY stop_id",
        (result.analysis_id,),
    ) == [("0001", 5, 2), ("NA", 1, 1), ("NULL", 2, 2)]
    gaps = query(
        db_url,
        "SELECT departure_count, interval_count, avg_seconds, median_seconds, p90_seconds FROM gold.route_stop_headways WHERE analysis_id=%s AND service_date='2026-10-01' AND route_id='R1' AND stop_id='0001' AND direction_id=0",
        (result.analysis_id,),
    )
    # Four visits: 07:50, 08:10, 08:10, 08:40. Gaps 1200, 0, 1800.
    assert gaps == [(4, 3, Decimal(1000), 1200.0, 1680.0)]
    assert query(
        db_url,
        "SELECT service_hour, departure_count FROM gold.route_stop_hourly WHERE analysis_id=%s AND service_date='2026-10-01' AND route_id='R1' AND stop_id='0001' ORDER BY service_hour",
        (result.analysis_id,),
    ) == [(7, 1), (8, 3)]
    assert query(
        db_url,
        "SELECT departure_count, interval_count, avg_seconds, median_seconds, p90_seconds FROM gold.route_stop_headways WHERE analysis_id=%s AND service_date='2026-10-01' AND route_id='R2' AND stop_id='NA'",
        (result.analysis_id,),
    ) == [(1, 0, None, None, None)]
    assert query(
        db_url,
        "SELECT service_hour FROM gold.route_stop_hourly WHERE analysis_id=%s AND service_date='2026-10-01' AND route_id='R2' ORDER BY service_hour",
        (result.analysis_id,),
    ) == [(23,), (25,), (1_000_000,)]
    assert query(
        db_url,
        "SELECT first_departure_seconds,last_departure_seconds FROM gold.service_span WHERE analysis_id=%s AND service_date='2026-10-01' AND route_id='R2' AND stop_id='NULL'",
        (result.analysis_id,),
    ) == [(3_600_000_000, 3_600_000_000)]
    assert query(
        db_url,
        "SELECT direction_id, count(*) FROM gold.route_stop_hourly WHERE analysis_id=%s AND service_date='2026-10-03' GROUP BY direction_id",
        (result.analysis_id,),
    ) == [(None, 2)]
    coverage = query(
        db_url,
        "SELECT total_events, known_arrivals, missing_arrivals, known_departures, regular_events, regular_known_departures, regular_missing_departures, no_pickup_events, on_request_events, pickup_type_2_events, pickup_type_3_events, exact_timepoint_events, approximate_timepoint_events, approximate_regular_departures FROM gold.coverage_daily WHERE analysis_id=%s AND service_date='2026-10-01'",
        (result.analysis_id,),
    )
    assert coverage == [(12, 11, 1, 11, 9, 8, 1, 1, 2, 1, 1, 10, 2, 1)]
    missing_group = query(
        db_url,
        "SELECT observation_count, missing_regular_departures, first_departure_seconds, known_regular_ratio FROM gold.service_span WHERE analysis_id=%s AND service_date='2026-10-01' AND route_id='R1' AND stop_id='NA'",
        (result.analysis_id,),
    )
    assert missing_group == [(0, 1, None, Decimal(0))]
    assert result.source_context["agency_timezones"] == ["Europe/Warsaw"]
    # Repetition with different execution limits has identical meaning and adds no rows.
    repeated = analyze(
        identity, "2026-10-01", "2026-10-05", db_url, max_events=1, timeout_seconds=5
    )
    assert repeated.status == "ALREADY_ANALYZED" and repeated.row_counts == result.row_counts


def test_dates_only_partial_outside_and_zero_days(db_url, make_raw, tmp_path):
    files = sample_files()
    del files["calendar.txt"]
    files["calendar_dates.txt"] = csv_contents(
        ["service_id", "date", "exception_type"],
        [["WD", "20261001", 1], ["WE", "20261003", 1], ["EXTRA", "20261003", 2]],
    )
    identity = load_files(db_url, make_raw, tmp_path, files)
    result = analyze(identity, "2026-09-30", "2026-10-04", db_url)
    days = query(
        db_url,
        "SELECT service_date, calendar_covered, trip_instances FROM gold.analysis_days WHERE analysis_id=%s ORDER BY service_date",
        (result.analysis_id,),
    )
    assert days == [
        (date(2026, 9, 30), False, None),
        (date(2026, 10, 1), True, 3),
        (date(2026, 10, 2), True, 0),
        (date(2026, 10, 3), True, 1),
        (date(2026, 10, 4), False, None),
    ]
    assert query(
        db_url,
        "SELECT trip_count FROM gold.route_daily WHERE analysis_id=%s AND service_date='2026-09-30'",
        (result.analysis_id,),
    ) == [(None,), (None,)]
    assert query(
        db_url,
        "SELECT regular_known_departures, distinct_routes FROM gold.stop_daily WHERE analysis_id=%s AND service_date='2026-10-02' ORDER BY stop_id",
        (result.analysis_id,),
    ) == [(0, 0), (0, 0), (0, 0)]
    assert query(
        db_url,
        "SELECT total_events, known_departure_ratio FROM gold.coverage_daily WHERE analysis_id=%s AND service_date='2026-10-02'",
        (result.analysis_id,),
    ) == [(0, None)]
    assert result.coverage["covered_days"] == 3 and result.coverage["outside_calendar_days"] == 2
    assert result.coverage["total_events"] == 12
    outside = analyze(identity, "2026-11-01", "2026-11-02", db_url)
    assert outside.coverage["covered_days"] == 0 and outside.coverage["total_events"] is None
    assert outside.row_counts["route_stop_hourly"] == 0


def test_dst_service_axis_and_inclusive_one_day(db_url, make_raw, tmp_path):
    files = numerical_files()
    files["calendar.txt"] = csv_contents(
        CALENDAR_COLUMNS,
        [
            ["WD", 1, 1, 1, 1, 1, 1, 1, "20261025", "20261025"],
            ["WE", 0, 0, 0, 0, 0, 0, 0, "20261025", "20261025"],
        ],
    )
    identity = load_files(db_url, make_raw, tmp_path, files)
    result = analyze(identity, "2026-10-25", "2026-10-25", db_url)
    assert query(
        db_url,
        "SELECT trip_count FROM gold.route_daily WHERE analysis_id=%s AND route_id='R2'",
        (result.analysis_id,),
    ) == [(1,)]
    assert query(
        db_url,
        "SELECT service_date,first_departure_seconds FROM gold.service_span WHERE analysis_id=%s AND route_id='R2' AND stop_id='NA'",
        (result.analysis_id,),
    ) == [(date(2026, 10, 25), 90600)]
    assert result.source_context["agency_timezones"] == ["Europe/Warsaw"]
    assert "no UTC or DST" in result.coverage["time_axis"]


def test_refusals_before_any_gold_publication(db_url, make_raw, tmp_path):
    initialize(db_url)
    with pytest.raises(AnalyticsError, match="DATASET_NOT_FOUND"):
        analyze("gtfs_" + "0" * 64, "2026-10-01", "2026-10-01", db_url)
    files = sample_files()
    files["frequencies.txt"] = csv_contents(
        ["trip_id", "start_time", "end_time", "headway_secs"], [["T1", "08:00:00", "09:00:00", 600]]
    )
    identity = load_files(db_url, make_raw, tmp_path, files)
    with pytest.raises(AnalyticsError, match="UNSUPPORTED_FREQUENCIES"):
        analyze(identity, "2026-10-01", "2026-10-01", db_url)
    supported = load_files(db_url, make_raw, tmp_path, sample_files())
    with pytest.raises(AnalyticsError, match="LIMIT_EXCEEDED"):
        analyze(supported, "2026-10-01", "2026-10-02", db_url, max_events=1)
    with pytest.raises(AnalyticsError, match="LIMIT_EXCEEDED"):
        analyze(supported, "2026-10-01", "2026-10-02", db_url, max_grid_rows=1)
    assert query(db_url, "SELECT count(*) FROM meta.analyses") == [(0,)]
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "UPDATE meta.datasets SET capabilities=capabilities || '{\"quantitative_gold_supported\":false}'::jsonb WHERE dataset_id=%s",
            (supported,),
        )
    with pytest.raises(AnalyticsError, match="UNSUPPORTED_CAPABILITIES"):
        analyze(supported, "2026-10-01", "2026-10-01", db_url)


def test_upgrade_preserves_loaded_silver_and_001_checksum(db_url, silver):
    migrations = migration_files()
    with psycopg.connect(db_url) as conn:
        assert apply_migrations(conn, migrations[:1]) == ["001_warehouse.sql"]
    identity = load_silver(silver, db_url).dataset_id
    before = query(db_url, "SELECT source_manifest,logical_fingerprint FROM meta.datasets")
    with pytest.raises(AnalyticsError, match="MIGRATIONS_REQUIRED"):
        analyze(identity, "2026-10-01", "2026-10-01", db_url)
    assert initialize(db_url) == ["002_gold.sql"]
    assert query(db_url, "SELECT source_manifest,logical_fingerprint FROM meta.datasets") == before
    assert query(
        db_url, "SELECT checksum FROM meta.migrations WHERE version='001_warehouse.sql'"
    ) == [(migrations[0][1],)]
    assert query(db_url, "SELECT count(*) FROM silver.stop_times") == [(15,)]
    assert load_silver(silver, db_url).status == "ALREADY_LOADED"
    assert analyze(identity, "2026-10-01", "2026-10-01", db_url).status == "ANALYZED"


def test_parallel_and_isolated_analyses(db_url, silver, make_raw, tmp_path):
    initialize(db_url)
    identity = load_silver(silver, db_url).dataset_id
    barrier = Barrier(2)

    def concurrent():
        barrier.wait(timeout=20)
        return analyze(identity, "2026-10-01", "2026-10-02", db_url)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(concurrent) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert sorted(result.status for result in results) == ["ALREADY_ANALYZED", "ANALYZED"]
    another_range = analyze(identity, "2026-10-03", "2026-10-03", db_url)
    files = sample_files()
    files["stops.txt"] = files["stops.txt"].replace(b"Demo Centrum", b"Another dataset")
    other_identity = load_files(db_url, make_raw, tmp_path, files)
    other = analyze(other_identity, "2026-10-01", "2026-10-02", db_url)
    assert len({results[0].analysis_id, another_range.analysis_id, other.analysis_id}) == 3
    assert other.coverage == results[0].coverage and other.row_counts == results[0].row_counts
    assert query(db_url, "SELECT count(*) FROM meta.analyses") == [(3,)]


def test_gold_failure_and_changed_rules_rollback(db_url, silver, monkeypatch):
    initialize(db_url)
    identity = load_silver(silver, db_url).dataset_id
    old = analyze(identity, "2026-10-01", "2026-10-01", db_url)
    original = runner._execute
    original_rules = runner.rules_digest

    def fail(connection, name, parameters=None):
        if name == "write_spans.sql":
            raise RuntimeError("Injected gold publication failure")
        return original(connection, name, parameters)

    monkeypatch.setattr(runner, "_execute", fail)
    with pytest.raises(RuntimeError, match="Injected"):
        analyze(identity, "2026-10-02", "2026-10-02", db_url)
    new_id = analysis_id(identity, date(2026, 10, 2), date(2026, 10, 2))
    assert query(db_url, "SELECT count(*) FROM meta.analyses WHERE analysis_id=%s", (new_id,)) == [
        (0,)
    ]
    for table in runner.OUTPUTS:
        assert query(
            db_url,
            sql.SQL("SELECT count(*) FROM {} WHERE analysis_id=%s").format(
                sql.Identifier("gold", table)
            ),
            (new_id,),
        ) == [(0,)]
    assert analyze(identity, "2026-10-01", "2026-10-01", db_url).row_counts == old.row_counts

    def delay(connection, name, parameters=None):
        if name == "write_spans.sql":
            connection.execute("SELECT pg_sleep(2)")
        return original(connection, name, parameters)

    monkeypatch.setattr(runner, "_execute", delay)
    with pytest.raises(AnalyticsError, match="TIMEOUT"):
        analyze(identity, "2026-10-03", "2026-10-03", db_url, timeout_seconds=1)
    assert query(db_url, "SELECT count(*) FROM meta.analyses") == [(1,)]
    monkeypatch.setattr(runner, "_execute", original)
    monkeypatch.setattr(runner, "rules_digest", lambda: "0" * 64)
    with pytest.raises(AnalyticsError, match="CONFLICT"):
        analyze(identity, "2026-10-01", "2026-10-01", db_url)
    monkeypatch.setattr(runner, "rules_digest", original_rules)
    with psycopg.connect(db_url) as conn:
        conn.execute("UPDATE meta.datasets SET logical_fingerprint=%s", ("f" * 64,))
    with pytest.raises(AnalyticsError, match="CONFLICT"):
        analyze(identity, "2026-10-01", "2026-10-01", db_url)


def test_normal_loader_role_analytics_and_destructive_denials(db_url, silver):
    role, password = "wta_test_gold_" + uuid4().hex, uuid4().hex
    with psycopg.connect(db_url) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
    try:
        initialize(db_url, loader_role=role)
        restricted = make_conninfo(db_url, user=role, password=password)
        identity = load_silver(silver, restricted).dataset_id
        result = analyze(identity, "2026-10-01", "2026-10-02", restricted)
        assert result.status == "ANALYZED"
        assert (
            analyze(identity, "2026-10-01", "2026-10-02", restricted).status == "ALREADY_ANALYZED"
        )
        with psycopg.connect(restricted, autocommit=True) as conn:
            for statement in (
                "UPDATE meta.analyses SET status='complete'",
                "DELETE FROM gold.route_daily",
                "TRUNCATE gold.stop_daily",
                "CREATE TABLE gold.forbidden (id INT)",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(statement)
    finally:
        with psycopg.connect(db_url) as admin:
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_synthetic_benchmark_and_real_explain(db_url, make_raw, tmp_path):
    started = perf_counter()
    identity = load_files(db_url, make_raw, tmp_path, benchmark_files())
    import_seconds = perf_counter() - started
    started = perf_counter()
    result = analyze(identity, "2026-10-01", "2026-10-07", db_url)
    analysis_seconds = perf_counter() - started
    assert result.coverage["total_events"] == 140_000
    params = {
        "dataset_id": identity,
        "analysis_id": result.analysis_id,
        "start_date": date(2026, 10, 1),
        "end_date": date(2026, 10, 7),
    }
    with psycopg.connect(db_url) as conn, conn.transaction():
        runner._inputs(conn, params, {"max_events": 5_000_000, "max_grid_rows": 5_000_000})
        # Explain the exact SELECT body of the packaged window query, not a second KPI algorithm.
        select = runner.sql_text("departures.sql").split(" AS\n", 1)[1]
        window_plan = conn.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + select).fetchone()[
            0
        ]
        aggregate = runner.sql_text("write_headways.sql")
        aggregate = aggregate[aggregate.index("WITH ") :]
        aggregate_plan = conn.execute(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + aggregate
        ).fetchone()[0]
    plans = {"departures.sql SELECT": window_plan, "write_headways.sql SELECT": aggregate_plan}
    heaviest = max(plans, key=lambda name: plans[name][0]["Execution Time"])
    evidence = {
        "data_kind": "synthetic_benchmark",
        "dataset_id": identity,
        "analysis_id": result.analysis_id,
        "static_trips": 1000,
        "static_stop_times": 20_000,
        "days": 7,
        "expanded_events": 140_000,
        "import_seconds": import_seconds,
        "analysis_seconds": analysis_seconds,
        "heaviest_measured_select": heaviest,
        "explain_analyze_buffers": plans,
        "gold_row_counts": result.row_counts,
    }
    directory = Path(os.environ.get("WTA_EVIDENCE_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "synthetic-benchmark.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
