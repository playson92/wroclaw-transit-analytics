"""Real PostgreSQL 17: transaction boundaries, contract values and concurrent writes."""

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from threading import Barrier
from uuid import uuid4

import pandas as pd
import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from tests.preparation.conftest import csv_contents, rewrite

from wroclaw_transit_analytics.database import DatabaseError, initialize, load_silver, loader
from wroclaw_transit_analytics.database.migrations import apply_migrations, migration_files
from wroclaw_transit_analytics.preparation import prepare
from wroclaw_transit_analytics.preparation.contract import TABLES, content_digest, update_digest
from wroclaw_transit_analytics.preparation.source import file_sha256
from wroclaw_transit_analytics.sample_data import sample_files

pytestmark = pytest.mark.integration


def document(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def counts(url, identity):
    with psycopg.connect(url) as conn:
        return {
            name: conn.execute(
                sql.SQL("SELECT count(*) FROM {} WHERE dataset_id=%s").format(
                    sql.Identifier("silver", name)
                ),
                (identity,),
            ).fetchone()[0]
            for name in TABLES
        }


def rewrite_parquet(manifest_path, table, change):
    manifest = document(manifest_path)
    path = manifest_path.parent / manifest["tables"][table]["path"]
    original = pq.read_table(path)
    rows = original.to_pylist()
    change(rows)
    updated = pa.Table.from_pylist(rows, schema=original.schema)
    pq.write_table(updated, path)
    digest = content_digest(updated.schema)
    update_digest(digest, updated.to_pandas(types_mapper=pd.ArrowDtype))
    manifest["tables"][table].update(
        size_bytes=path.stat().st_size,
        sha256=file_sha256(path),
        content_sha256=digest.hexdigest(),
    )
    write(manifest_path, manifest)


def test_migration_noop_checksum_and_transaction_rollback(db_url):
    assert initialize(db_url) == ["001_warehouse.sql"]
    assert initialize(db_url) == []
    with psycopg.connect(db_url) as conn:
        history = conn.execute(
            "SELECT version, checksum, applied_at FROM meta.migrations"
        ).fetchall()
        assert len(history) == 1 and history[0][2].tzinfo is not None
        conn.execute("UPDATE meta.migrations SET checksum=%s", ("0" * 64,))
    with pytest.raises(DatabaseError, match="checksum"):
        initialize(db_url)
    with psycopg.connect(db_url) as conn:
        conn.execute("UPDATE meta.migrations SET checksum=%s", (migration_files()[0][1],))
    entries = [
        *migration_files(),
        (
            "002_failed.sql",
            "1" * 64,
            "CREATE TABLE meta.rollback_probe (id INT); SELECT * FROM meta.no_such_table;",
        ),
    ]
    with psycopg.connect(db_url) as conn:
        with pytest.raises(psycopg.errors.UndefinedTable):
            apply_migrations(conn, entries)
        assert conn.execute("SELECT to_regclass('meta.rollback_probe')").fetchone()[0] is None
        assert conn.execute("SELECT count(*) FROM meta.migrations").fetchone()[0] == 1


def test_concurrent_init_serializes(db_url):
    barrier = Barrier(2)

    def initialize_at_once():
        barrier.wait(timeout=20)
        return initialize(db_url)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(initialize_at_once) for _ in range(2)]
        assert sorted(future.result(timeout=30) for future in futures) == [
            [],
            ["001_warehouse.sql"],
        ]


def test_prepare_load_values_metadata_and_idempotence(db_url, make_raw, tmp_path):
    files = sample_files()

    def route_changes(columns, rows):
        rows[0][columns.index("route_type")] = str(2**40)
        columns.append("municipal_note")
        for row in rows:
            row.append("NA" if row[0] == "D1" else "")

    rewrite(files, "routes.txt", route_changes)

    def event_changes(columns, rows):
        for row in rows:
            if row[columns.index("stop_sequence")] == "5":
                row[columns.index("stop_sequence")] = str(2**40)
                if row[columns.index("trip_id")] == "LATE":
                    row[columns.index("departure_time")] = "1000000:00:00"

    rewrite(files, "stop_times.txt", event_changes)
    raw = make_raw(files)
    first = prepare(raw, tmp_path / "out", batch_size=1).silver_manifest
    second = prepare(raw, tmp_path / "out", batch_size=100).silver_manifest
    rewrite_parquet(first, "agency", lambda rows: rows[0].update(_wta_source_record=2**40))
    # Apply the same logical record provenance to both physical encodings.
    rewrite_parquet(second, "agency", lambda rows: rows[0].update(_wta_source_record=2**40))
    initialize(db_url)
    loaded = load_silver(first, db_url, batch_size=2)
    assert loaded.status == "LOADED"
    assert counts(db_url, loaded.dataset_id) == {
        "agency": 1,
        "stops": 7,
        "routes": 2,
        "trips": 5,
        "stop_times": 15,
        "calendar": 2,
        "calendar_dates": 3,
    }
    assert load_silver(first, db_url).status == "ALREADY_LOADED"
    assert load_silver(second, db_url).status == "ALREADY_LOADED"
    with psycopg.connect(db_url) as conn:
        assert set(row[0] for row in conn.execute("SELECT stop_id FROM silver.stops")) >= {
            "0001",
            "NA",
            "NULL",
        }
        assert conn.execute(
            "SELECT stop_name, stop_lat FROM silver.stops WHERE stop_id='NODE'"
        ).fetchone() == ("", None)
        assert conn.execute(
            "SELECT arrival_time, departure_seconds, stop_sequence FROM silver.stop_times WHERE trip_id='LATE' ORDER BY stop_sequence DESC LIMIT 1"
        ).fetchone() == ("25:10:00", 3_600_000_000, 2**40)
        assert conn.execute(
            "SELECT departure_time, departure_seconds FROM silver.stop_times WHERE trip_id='T2' AND stop_sequence=2"
        ).fetchone() == ("", None)
        assert conn.execute(
            "SELECT agency_id, _agency_key, _wta_source_record FROM silver.agency"
        ).fetchone() == (None, "__single_agency__", 2**40)
        assert conn.execute(
            "SELECT route_type, extra_fields FROM silver.routes WHERE route_id='D1'"
        ).fetchone() == (2**40, {"municipal_note": "NA"})
        assert conn.execute(
            "SELECT extra_fields FROM silver.routes WHERE route_id='D2'"
        ).fetchone() == ({"municipal_note": ""},)
        assert conn.execute(
            "SELECT start_date FROM silver.calendar WHERE service_id='WD'"
        ).fetchone()[0] == date(2026, 10, 1)
        metadata = conn.execute(
            "SELECT source_manifest, quality_report, capabilities, status FROM meta.datasets"
        ).fetchone()
        assert metadata == (
            document(first),
            document(first.parent / "quality.json"),
            document(first)["capabilities"],
            "complete",
        )
        assert conn.execute("SELECT count(*) FROM meta.datasets").fetchone()[0] == 1
    with (first.parent / "stops.parquet").open("ab") as stream:
        stream.write(b"tampered even for ALREADY_LOADED")
    with pytest.raises(DatabaseError):
        load_silver(first, db_url)


@pytest.mark.parametrize("present_empty", [False, True])
def test_dates_only_calendar_and_frequencies_capabilities(
    db_url, make_raw, tmp_path, present_empty
):
    files = sample_files()
    if present_empty:
        files["calendar.txt"] = files["calendar.txt"].splitlines(keepends=True)[0]
    else:
        del files["calendar.txt"]
    files["calendar_dates.txt"] = csv_contents(
        ["service_id", "date", "exception_type"],
        [["WD", "20261007", 1], ["WE", "20261008", 1], ["EXTRA", "20261007", 1]],
    )
    files["frequencies.txt"] = csv_contents(
        ["trip_id", "start_time", "end_time", "headway_secs"], [["T1", "08:00:00", "09:00:00", 600]]
    )
    silver = prepare(make_raw(files), tmp_path / "out", batch_size=1).silver_manifest
    portable = tmp_path / "portable"
    shutil.copytree(silver.parent, portable)
    shutil.rmtree(tmp_path / "out")
    initialize(db_url)
    result = load_silver(portable / "manifest.json", db_url)
    assert result.status == "LOADED"
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT count(*) FROM silver.services").fetchone()[0] == 3
        source_manifest, capabilities, quality = conn.execute(
            "SELECT source_manifest, capabilities, quality_report FROM meta.datasets"
        ).fetchone()
        assert source_manifest["tables"]["calendar"]["source_present"] is present_empty
        assert source_manifest["tables"]["calendar"]["normalized_empty"] is not present_empty
        assert capabilities["quantitative_gold_supported"] is False
        assert capabilities["frequencies"]["row_count"] == 1
        assert any(check["code"] == "unsupported_frequencies" for check in quality["checks"])


def test_conflict_and_two_dataset_isolation(db_url, silver, make_raw, tmp_path):
    initialize(db_url)
    first = load_silver(silver, db_url)
    changed = tmp_path / "conflicting"
    shutil.copytree(silver.parent, changed)
    rewrite_parquet(
        changed / "manifest.json",
        "stops",
        lambda rows: rows[0].update(stop_name="Different logical contents"),
    )
    with pytest.raises(DatabaseError, match="CONFLICT"):
        load_silver(changed / "manifest.json", db_url)
    files = sample_files()
    files["stops.txt"] = files["stops.txt"].replace(b"Demo Centrum", b"Different source")
    second_manifest = prepare(make_raw(files), tmp_path / "other", batch_size=2).silver_manifest
    second = load_silver(second_manifest, db_url)
    assert first.dataset_id != second.dataset_id
    assert counts(db_url, first.dataset_id) == counts(db_url, second.dataset_id)
    with psycopg.connect(db_url) as conn:
        assert (
            conn.execute("SELECT count(*) FROM silver.trips WHERE trip_id='T1'").fetchone()[0] == 2
        )
        # A reference cannot find a route solely in another dataset.
        conn.execute(
            "INSERT INTO silver.routes SELECT dataset_id, 'ONLY_FIRST', agency_id, route_short_name, route_long_name, route_type, _agency_key, route_type_description, _wta_source_record, extra_fields FROM silver.routes WHERE dataset_id=%s LIMIT 1",
            (first.dataset_id,),
        )
    with psycopg.connect(db_url) as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation), conn.transaction():
            conn.execute(
                "UPDATE silver.trips SET route_id='ONLY_FIRST' WHERE dataset_id=%s AND trip_id='T1'",
                (second.dataset_id,),
            )
    assert counts(db_url, first.dataset_id)["routes"] == 3
    assert counts(db_url, second.dataset_id)["routes"] == 2


def test_copy_failure_rolls_back_only_new_dataset(db_url, silver, make_raw, tmp_path, monkeypatch):
    initialize(db_url)
    old = load_silver(silver, db_url)
    old_counts = counts(db_url, old.dataset_id)
    files = sample_files()
    files["stops.txt"] = files["stops.txt"].replace(b"Demo Centrum", b"New dataset")
    new = prepare(make_raw(files), tmp_path / "new", batch_size=1).silver_manifest
    original = loader._copy_table

    def fail_during_stop_times(connection, verified, name, batch_size):
        if name == "stop_times":
            with connection.cursor().copy(
                "COPY silver.stop_times (dataset_id, trip_id, stop_id, stop_sequence, arrival_time, departure_time, pickup_type, drop_off_type, timepoint, _wta_source_record, extra_fields) FROM STDIN"
            ) as copy:
                copy.write_row(
                    (
                        verified.manifest["dataset_id"],
                        "T1",
                        "0001",
                        1,
                        "08:00:00",
                        "08:00:00",
                        0,
                        0,
                        1,
                        1,
                        "{}",
                    )
                )
                raise RuntimeError("Injected failure after an actual COPY row")
        return original(connection, verified, name, batch_size)

    monkeypatch.setattr(loader, "_copy_table", fail_during_stop_times)
    with pytest.raises(RuntimeError, match="Injected failure"):
        load_silver(new, db_url, batch_size=1)
    assert counts(db_url, old.dataset_id) == old_counts
    assert all(value == 0 for value in counts(db_url, document(new)["dataset_id"]).values())
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT count(*) FROM meta.datasets").fetchone()[0] == 1


def test_simultaneous_loads_use_distinct_connections(db_url, silver, monkeypatch):
    initialize(db_url)
    barrier = Barrier(2)
    original = loader.verified_silver

    @contextmanager
    def synchronize(*args, **kwargs):
        with original(*args, **kwargs) as verified:
            barrier.wait(timeout=20)
            yield verified

    monkeypatch.setattr(loader, "verified_silver", synchronize)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(load_silver, silver, db_url, batch_size=1) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert sorted(result.status for result in results) == ["ALREADY_LOADED", "LOADED"]
    assert counts(db_url, results[0].dataset_id) == results[0].row_counts


def test_loader_role_can_load_but_cannot_change_existing_rows(db_url, silver):
    role = "wta_test_loader_" + uuid4().hex
    password = uuid4().hex
    with psycopg.connect(db_url) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
    try:
        initialize(db_url, loader_role=role)
        restricted = make_conninfo(db_url, user=role, password=password)
        assert load_silver(silver, restricted).status == "LOADED"
        assert load_silver(silver, restricted).status == "ALREADY_LOADED"
        with psycopg.connect(restricted, autocommit=True) as conn:
            assert conn.execute(
                "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user"
            ).fetchone() == (False, False, False)
            for query in (
                "CREATE TABLE silver.forbidden (id INT)",
                "UPDATE meta.datasets SET status='complete'",
                "DELETE FROM silver.trips",
                "TRUNCATE silver.stop_times",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(query)
    finally:
        with psycopg.connect(db_url) as admin:
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
