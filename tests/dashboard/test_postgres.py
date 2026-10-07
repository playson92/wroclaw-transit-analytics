"""Reader ACLs and hand-counted dashboard queries on actual PostgreSQL 17."""

import json
import os
from dataclasses import replace
from datetime import date
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from tests.analytics.scenarios import numerical_files
from tests.analytics.test_postgres import load_files

from wroclaw_transit_analytics import pipeline
from wroclaw_transit_analytics.analytics import analyze
from wroclaw_transit_analytics.dashboard import data
from wroclaw_transit_analytics.database import initialize

pytestmark = pytest.mark.integration
READER_PASSWORD = "disposable_test_reader_only"


def setup_reader(db_url, monkeypatch):
    monkeypatch.setenv("WTA_READER_PASSWORD", READER_PASSWORD)
    initialize(db_url, reader_role="wta_reader")
    readonly = make_conninfo(db_url, user="wta_reader", password=READER_PASSWORD)
    monkeypatch.setenv("READONLY_DATABASE_URL", readonly)
    return readonly


def evidence(name, value):
    if root := os.environ.get("WTA_EVIDENCE_DIR"):
        path = Path(root)
        path.mkdir(exist_ok=True)
        (path / name).write_text(json.dumps(value, default=str, indent=2), encoding="utf-8")


def test_reader_upgrade_acl_and_no_password_rotation(db_url, monkeypatch, tmp_path):
    initialize(db_url)
    first = pipeline.demo(tmp_path / "first", db_url)
    assert first["status"] == "PASSED"
    readonly = setup_reader(db_url, monkeypatch)
    assert initialize(db_url, reader_role="wta_reader") == []
    monkeypatch.setenv("WTA_READER_PASSWORD", "different_ignored_existing_password")
    assert initialize(db_url, reader_role="wta_reader") == []
    with psycopg.connect(readonly, autocommit=True) as conn:
        flags = conn.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        assert flags == (False, False, False, False)
        assert not conn.execute(
            "SELECT has_schema_privilege(current_user,'silver','USAGE')"
        ).fetchone()[0]
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)"
            ).fetchone()[0]
            == 0
        )
        assert conn.execute("SELECT count(*) FROM meta.datasets").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM gold.route_daily").fetchone()[0] == 14
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM gold.active_services")
        rejected = []
        for query in (
            "INSERT INTO gold.analysis_days SELECT * FROM gold.analysis_days WHERE false",
            "UPDATE meta.datasets SET status=status WHERE false",
            "DELETE FROM gold.route_daily WHERE false",
            "TRUNCATE gold.route_daily",
            "UPDATE silver.stops SET stop_name=stop_name WHERE false",
            "CREATE TABLE gold.reader_probe(id int)",
            "ALTER TABLE gold.route_daily ADD COLUMN reader_probe int",
            "DROP TABLE gold.route_daily",
            "CREATE TABLE public.reader_probe(id int)",
            "CREATE SCHEMA reader_probe",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(query)
            rejected.append(query.split()[0:3])
    evidence(
        "reader-acl-upgrade.json",
        {
            "status": "PASS",
            "flags": flags,
            "rejected": rejected,
            "password_unchanged": True,
            "silver_usage": False,
            "role_memberships": 0,
            "unneeded_active_services_select": "DENIED",
            "preserved_datasets": 1,
            "preserved_gold_rows": 14,
        },
    )


def test_hand_counted_global_group_partial_coverage(db_url, make_raw, tmp_path, monkeypatch):
    dataset = load_files(db_url, make_raw, tmp_path, numerical_files())
    analysis = analyze(dataset, "2026-10-01", "2026-10-06", db_url)
    setup_reader(db_url, monkeypatch)
    context = data.Context(dataset, analysis.analysis_id, date(2026, 10, 1), date(2026, 10, 2))
    result = data.fetch("overview", context)
    assert result["kpi"]["trips"] == 9
    assert result["kpi"]["departures"] == 17
    assert result["kpi"]["active_routes"] == 2  # Same R1 on both days remains one distinct line.
    assert result["kpi"]["served_stops"] == 3
    assert result["kpi"]["catalog_stops"] == 7
    assert result["kpi"]["regular_events"] == 19
    group = data.fetch("group", replace(context, route="R1", stop="0001", direction="0"))
    assert [r["departures"] for r in group["daily"]] == [4, 4]
    assert [(r["median_seconds"], r["p90_seconds"]) for r in group["headways"]] == [
        (1200, 1680),
        (1200, 1680),
    ]
    missing = data.fetch("group", replace(context, route="R1", stop="NA", direction="0"))
    assert [r["departures"] for r in missing["daily"]] == [0, 0]
    assert [r["missing"] for r in missing["daily"]] == [1, 1]
    null_direction = data.fetch(
        "group", replace(context, route="R1", stop="0001", direction="NULL")
    )
    assert [r["departures"] for r in null_direction["daily"]] == [0, 1]
    huge = data.fetch("group", replace(context, route="R2", stop="NULL", direction="1"))
    assert huge["hourly"] == [{"service_hour": 1000000, "departures": 2}]
    outside = data.fetch(
        "overview", replace(context, start=date(2026, 10, 6), end=date(2026, 10, 6))
    )
    assert all(
        outside["kpi"][k] is None for k in ("trips", "departures", "active_routes", "served_stops")
    )
    mixed = data.fetch("overview", replace(context, end=date(2026, 10, 6)))
    assert mixed["kpi"]["covered_days"] == 5 and mixed["kpi"]["requested_days"] == 6
    covered_zero = data.fetch(
        "overview", replace(context, start=date(2026, 10, 5), end=date(2026, 10, 5))
    )
    assert covered_zero["kpi"]["trips"] == covered_zero["kpi"]["departures"] == 0
    evidence(
        "dashboard-numerical.json",
        {
            "status": "PASS",
            "dataset_id": dataset,
            "analysis_id": analysis.analysis_id,
            "overview": result,
            "group": group,
            "outside": outside,
            "mixed": mixed,
        },
    )


def test_dataset_and_overlapping_analysis_isolation(db_url, make_raw, tmp_path, monkeypatch):
    first = load_files(db_url, make_raw, tmp_path, numerical_files())
    files = numerical_files()
    files["routes.txt"] = files["routes.txt"].replace(b"R1,R1", b"R1,Other snapshot")
    second = load_files(db_url, make_raw, tmp_path, files)
    a1 = analyze(first, "2026-10-01", "2026-10-02", db_url)
    a2 = analyze(first, "2026-10-02", "2026-10-03", db_url)
    a3 = analyze(second, "2026-10-01", "2026-10-02", db_url)
    setup_reader(db_url, monkeypatch)
    assert len(data.catalog()["analyses"]) == 3
    context = data.Context(first, a1.analysis_id, date(2026, 10, 1), date(2026, 10, 2))
    assert data.fetch("overview", context)["kpi"]["trips"] == 9
    assert (
        data.fetch(
            "overview",
            replace(
                context, analysis=a2.analysis_id, start=date(2026, 10, 2), end=date(2026, 10, 3)
            ),
        )["kpi"]["trips"]
        == 7
    )
    assert (
        data.fetch("overview", replace(context, dataset=second, analysis=a3.analysis_id))["routes"][
            0
        ]["route_short_name"]
        == "Other snapshot"
    )
    with pytest.raises(data.DashboardError, match="Brak kompletnej"):
        data.fetch("overview", replace(context, dataset=second))


def test_full_demo_idempotence(db_url, tmp_path, monkeypatch):
    initialize(db_url)
    first = pipeline.demo(tmp_path / "first", db_url)
    second = pipeline.demo(tmp_path / "second", db_url)
    assert first["status"] == second["status"] == "PASSED"
    assert first["dataset_id"] == second["dataset_id"]
    assert first["analysis_id"] == second["analysis_id"]
    assert second["stages"]["load"]["status"] == "ALREADY_LOADED"
    assert second["stages"]["analyze"]["status"] == "ALREADY_ANALYZED"
    setup_reader(db_url, monkeypatch)
    with data.reader() as conn:
        assert conn.execute("SELECT count(*) AS n FROM meta.datasets").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM meta.analyses").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM gold.route_daily").fetchone()["n"] == 14
    evidence("demo-repeat.json", {"status": "PASS", "first": first, "second": second})


def test_no_admin_fallback_and_parameterized_filters(db_url, make_raw, tmp_path, monkeypatch):
    dataset = load_files(db_url, make_raw, tmp_path, numerical_files())
    analysis = analyze(dataset, "2026-10-01", "2026-10-02", db_url)
    setup_reader(db_url, monkeypatch)
    context = data.Context(
        dataset,
        analysis.analysis_id,
        date(2026, 10, 1),
        date(2026, 10, 2),
        route="R1' OR 1=1 --",
        stop="0001",
        direction="0",
    )
    assert all(r["departures"] == 0 for r in data.fetch("group", context)["daily"])
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.delenv("READONLY_DATABASE_URL")
    with pytest.raises(data.DashboardError, match="READONLY_DATABASE_URL"):
        data.catalog()
    monkeypatch.setenv("READONLY_DATABASE_URL", db_url)
    with pytest.raises(data.DashboardError, match="wta_reader"):
        data.catalog()
