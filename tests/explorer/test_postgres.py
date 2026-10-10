"""Actual PostgreSQL: calendars, repeated visits, immutable shapes, isolation and ACLs."""

from datetime import date

import psycopg
import pytest
from tests.analytics.scenarios import numerical_files
from tests.dashboard.test_postgres import READER_PASSWORD, setup_reader
from tests.preparation.conftest import csv_contents

from wroclaw_transit_analytics.database import DatabaseError, initialize, load_silver
from wroclaw_transit_analytics.database.migrations import apply_migrations, migration_files
from wroclaw_transit_analytics.explorer import data
from wroclaw_transit_analytics.explorer.geometry import import_geometry
from wroclaw_transit_analytics.preparation import PrepareError, prepare

pytestmark = pytest.mark.integration


def load(db_url, make_raw, tmp_path, files, label):
    raw = make_raw(files)
    silver = prepare(raw, tmp_path / label).silver_manifest
    initialize(db_url)
    identity = load_silver(silver, db_url).dataset_id
    return raw, identity


def selected(dataset, route="R1", day=date(2026, 10, 1)):
    return data.fetch("variants", dataset, day, route)


def test_active_calendars_repeated_visits_missing_times_and_midnight(
    db_url, make_raw, tmp_path, monkeypatch
):
    _, dataset = load(db_url, make_raw, tmp_path, numerical_files(), "calendar")
    setup_reader(db_url, monkeypatch)
    first = selected(dataset)
    trips = [
        t
        for v in first
        for t in data.fetch("trips", dataset, date(2026, 10, 1), "R1", v["variant_key"])
    ]
    assert {t["trip_id"] for t in trips} == {"A", "B", "C"}
    added = selected(dataset, day=date(2026, 10, 2))
    assert sum(v["trip_count"] for v in added) == 4  # calendar_dates adds weekend W.
    assert selected(dataset, day=date(2026, 10, 5)) == []  # removes weekday service.
    assert selected(dataset, day=date(2026, 11, 1)) == []
    a = next(t for t in trips if t["trip_id"] == "A")
    visits = data.fetch("stops", dataset, date(2026, 10, 1), "R1", a["variant_key"], "A")
    assert [r["stop_id"] for r in visits] == ["0001", "NA", "0001"]
    departures = data.fetch("departures", dataset, date(2026, 10, 1), "R1", stop="0001")
    assert sum(r["trip_id"] == "A" for r in departures) == 2
    c = next(t for t in trips if t["trip_id"] == "C")
    missing = data.fetch("stops", dataset, date(2026, 10, 1), "R1", c["variant_key"], "C")
    assert missing[1]["departure_seconds"] is None
    v = selected(dataset, "R2")[0]
    late = data.fetch("stops", dataset, date(2026, 10, 1), "R2", v["variant_key"], "D")
    assert late[1]["departure_seconds"] == 90600
    assert late[2]["stop_sequence"] == 2**40
    assert len(first) == 2  # A repeats 0001; B and C share the same ordered stop pattern.
    assert data.fetch("variants", dataset, date(2026, 10, 1), "R1' OR 1=1 --") == []


def shape_files(lat=51.1, sequence=2):
    files = numerical_files()
    files["trips.txt"] = files["trips.txt"].replace(b"direction_id\n", b"direction_id,shape_id\n")
    lines = files["trips.txt"].decode().splitlines()
    files["trips.txt"] = (
        lines[0] + "\n" + "\n".join(r + ",shape" for r in lines[1:]) + "\n"
    ).encode()
    files["shapes.txt"] = csv_contents(
        ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"],
        [["shape", lat, 17.1, sequence], ["shape", 51.2, 17.2, 1]],
    )
    return files


def test_geometry_same_ids_in_two_snapshots_and_reader_acl(db_url, make_raw, tmp_path, monkeypatch):
    raw1, d1 = load(db_url, make_raw, tmp_path, shape_files(), "one")
    raw2, d2 = load(db_url, make_raw, tmp_path, shape_files(51.3), "two")
    assert d1 != d2
    assert import_geometry(raw1, db_url)["point_count"] == 2
    assert import_geometry(raw2, db_url)["point_count"] == 2
    assert import_geometry(raw1, db_url)["status"] == "ALREADY_IMPORTED"
    readonly = setup_reader(db_url, monkeypatch)
    for dataset, expected in ((d1, 51.1), (d2, 51.3)):
        v = next(v for v in selected(dataset) if v["trip_headsign"] == "")
        t = data.fetch("trips", dataset, date(2026, 10, 1), "R1", v["variant_key"])[0]
        geometry = data.fetch(
            "geometry", dataset, date(2026, 10, 1), "R1", v["variant_key"], t["trip_id"]
        )
        assert [r["shape_pt_sequence"] for r in geometry] == [1, 2]
        assert geometry[1]["latitude"] == expected
    with psycopg.connect(readonly, autocommit=True) as conn:
        for statement in (
            "SELECT * FROM silver.stop_times",
            "INSERT INTO explorer.shape_points SELECT * FROM explorer.shape_points WHERE false",
            "UPDATE explorer.shape_points SET latitude=latitude WHERE false",
            "DELETE FROM explorer.shape_points WHERE false",
            "TRUNCATE explorer.shape_points",
            "CREATE TABLE explorer.probe(id int)",
            "DROP VIEW explorer.trips",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)


@pytest.mark.parametrize("bad", ["duplicate", "coordinates"])
def test_invalid_geometry_rolls_back(db_url, make_raw, tmp_path, bad):
    files = shape_files(sequence=1) if bad == "duplicate" else shape_files(lat=float("nan"))
    raw, dataset = load(db_url, make_raw, tmp_path, files, "bad")
    with pytest.raises((DatabaseError, PrepareError)):
        import_geometry(raw, db_url)
    with psycopg.connect(db_url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM explorer.geometry_imports WHERE dataset_id=%s", (dataset,)
            ).fetchone()[0]
            == 0
        )
        assert conn.execute("SELECT count(*) FROM explorer.shape_points").fetchone()[0] == 0


def test_absent_shapes_and_mismatched_raw(db_url, make_raw, tmp_path):
    raw, dataset = load(db_url, make_raw, tmp_path, numerical_files(), "absent")
    assert import_geometry(raw, db_url)["geometry_status"] == "absent"
    unrelated = make_raw(shape_files())
    with pytest.raises(DatabaseError, match="Najpierw"):
        import_geometry(unrelated, db_url)
    assert import_geometry(raw, db_url)["point_count"] == 0


def test_upgrade_preserves_existing_dataset_and_gold(db_url, make_raw, tmp_path, monkeypatch):
    from wroclaw_transit_analytics.analytics import analyze

    old = migration_files()[:2]
    with psycopg.connect(db_url) as conn:
        apply_migrations(conn, old)
    raw = make_raw(numerical_files())
    silver = prepare(raw, tmp_path / "old").silver_manifest
    dataset = load_silver(silver, db_url).dataset_id
    with monkeypatch.context() as old_app:
        old_app.setattr("wroclaw_transit_analytics.analytics.runner.migration_files", lambda: old)
        analysis = analyze(dataset, "2026-10-01", "2026-10-02", db_url)
    monkeypatch.setenv("WTA_READER_PASSWORD", READER_PASSWORD)
    assert initialize(db_url, reader_role="wta_reader") == ["003_explorer.sql"]
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT count(*) FROM silver.stop_times").fetchone()[0] == 14
        assert (
            conn.execute("SELECT analysis_id FROM meta.analyses").fetchone()[0]
            == analysis.analysis_id
        )
        assert conn.execute("SELECT sum(trip_instances) FROM gold.analysis_days").fetchone()[0] == 9
    assert load_silver(silver, db_url).status == "ALREADY_LOADED"
