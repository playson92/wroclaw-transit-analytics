"""Value, relational and failure-boundary tests on actual small Parquet outputs."""

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from wroclaw_transit_analytics.__main__ import main
from wroclaw_transit_analytics.preparation import (
    MODEL_VERSION,
    PrepareError,
    dataset_id,
    pipeline,
    prepare,
)
from wroclaw_transit_analytics.preparation.source import file_sha256, write_json
from wroclaw_transit_analytics.sample_data import sample_files, sample_zip_bytes, write_sample_data

from .conftest import csv_contents, rewrite


def document(path):
    return json.loads(path.read_text(encoding="utf-8"))


def silver_rows(result, table):
    return pq.read_table(result.silver_manifest.parent / f"{table}.parquet").to_pylist()


def failed_quality(raw, output, *, batch_size=2):
    with pytest.raises(PrepareError) as caught:
        prepare(raw, output, batch_size=batch_size)
    assert len(caught.value.manifests) == 2
    bronze, silver = caught.value.manifests
    assert document(bronze)["status"] == "passed"
    assert document(silver)["status"] == "failed"
    return document(silver.parent / "quality.json")


def test_round_trip_and_raw_unchanged(make_raw, tmp_path):
    raw = make_raw()
    before = {path.name: file_sha256(path) for path in raw.parent.iterdir()}
    result = prepare(raw, tmp_path / "out", batch_size=2)
    bronze, silver = document(result.bronze_manifest), document(result.silver_manifest)
    assert bronze["status"] == silver["status"] == "passed"
    assert silver["model_version"] == MODEL_VERSION
    assert silver["tables"]["stops"]["row_count"] == 7
    assert silver["tables"]["stop_times"]["row_count"] == 15
    assert silver["tables"]["routes"]["row_count"] == 2
    assert silver["tables"]["calendar_dates"]["row_count"] == 3
    stops = {row["stop_id"]: row for row in silver_rows(result, "stops")}
    assert set(stops) == {"0001", "NA", "NULL", "STATION", "ENTRANCE", "NODE", "AREA"}
    assert stops["NULL"]["stop_name"] == "Demo Pętla"
    assert stops["NODE"]["stop_lat"] is None
    assert stops["AREA"]["stop_lon"] is None
    assert stops["0001"]["location_type"] == 0
    events = silver_rows(result, "stop_times")
    late = next(row for row in events if row["trip_id"] == "LATE" and row["stop_sequence"] == 5)
    assert late["arrival_time"] == "25:10:00"
    assert late["departure_seconds"] == 90600
    missing = next(row for row in events if row["trip_id"] == "T2" and row["stop_sequence"] == 2)
    assert missing["departure_seconds"] is None and missing["departure_time"] == ""
    assert missing["timepoint"] == 0
    assert next(row for row in events if row["trip_id"] == "T1")["departure_seconds"] == 28800
    assert next(row for row in events if row["trip_id"] == "T1")["pickup_type"] == 0
    assert silver_rows(result, "agency")[0]["_agency_key"] == "__single_agency__"
    assert {row["_agency_key"] for row in silver_rows(result, "routes")} == {"__single_agency__"}
    quality = document(result.quality_report)
    assert quality["time_coverage"]["known_departures"] == 14
    assert quality["time_coverage"]["on_request_pickup_records"] == 1
    assert quality["time_coverage"]["no_pickup_records"] == 5
    assert quality["unknown_directions"] == 1
    assert quality["service_date_range"] == {"start_date": "2026-10-01", "end_date": "2026-10-31"}
    assert {path.name: file_sha256(path) for path in raw.parent.iterdir()} == before
    assert not list(result.silver_manifest.parent.glob("*.sqlite*"))


def test_identity_and_logical_hash_invariant_to_batch_size(make_raw, tmp_path):
    raw = make_raw()
    first = prepare(raw, tmp_path / "out", batch_size=1)
    second = prepare(raw, tmp_path / "out", batch_size=100)
    assert first.dataset_id == second.dataset_id
    assert first.processing_run_id != second.processing_run_id
    assert first.silver_manifest != second.silver_manifest
    first_tables = document(first.silver_manifest)["tables"]
    second_tables = document(second.silver_manifest)["tables"]
    assert {name: item["content_sha256"] for name, item in first_tables.items()} == {
        name: item["content_sha256"] for name, item in second_tables.items()
    }
    assert dataset_id(document(raw)["sha256"], "future-model") != first.dataset_id


def test_textual_bronze_all_columns_bom_and_empty_records(make_raw, tmp_path):
    files = sample_files()
    rows = [
        ["0001", "NA", "0001", ""],
        ["NA", "NULL", "51.1", "17.1"],
        ["NULL", "", "", ""],
    ]
    files["frequencies.txt"] = b"\xef\xbb\xbf" + csv_contents(
        ["trip_id", "extra", "start_time", "end_time"], rows
    )
    files["stops.txt"] = b"\xef\xbb\xbf" + files["stops.txt"].replace(b"\n", b"\n\n,,,,,\n", 1)
    files["shapes.txt"] = b"shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\ns,51,17,0\n"
    result = prepare(make_raw(files), tmp_path / "out", batch_size=1)
    bronze = document(result.bronze_manifest)
    values = pq.read_table(result.bronze_manifest.parent / "frequencies.parquet").to_pylist()
    assert values[0]["trip_id"] == "0001" and values[0]["extra"] == "NA"
    assert values[1]["extra"] == "NULL" and values[2]["start_time"] == ""
    assert values[0]["_wta_source_record"] == 1
    assert bronze["capabilities"]["frequencies"]["row_count"] == 3
    assert bronze["capabilities"]["quantitative_gold_supported"] is False
    assert bronze["capabilities"]["unprocessed_files"] == ["shapes.txt"]
    assert "frequencies" not in document(result.silver_manifest)["tables"]
    stops = pq.read_table(result.bronze_manifest.parent / "stops.parquet").to_pylist()
    assert stops[0]["_wta_source_record"] == 3  # Two skipped logical records, no renumbering.
    assert stops[0]["stop_lat"] == "51.10"


@pytest.mark.parametrize("missing", ["calendar", "calendar_dates"])
def test_calendar_variants_normalize_only_silver(make_raw, tmp_path, missing):
    files = sample_files()
    del files[missing + ".txt"]
    if missing == "calendar":
        files["calendar_dates.txt"] = csv_contents(
            ["service_id", "date", "exception_type"],
            [["WD", "20261007", 1], ["WE", "20261008", 1], ["EXTRA", "20261007", 1]],
        )
    else:
        files["trips.txt"] = files["trips.txt"].replace(b"D2,EXTRA,EXTRA", b"D2,WD,EXTRA")
    result = prepare(make_raw(files), tmp_path / "out", batch_size=1)
    bronze = document(result.bronze_manifest)["tables"][missing]
    silver = document(result.silver_manifest)["tables"][missing]
    assert bronze["path"] is None and bronze["source_present"] is False
    assert silver["source_present"] is False and silver["normalized_empty"] is True
    assert silver["row_count"] == 0 and silver_rows(result, missing) == []


@pytest.mark.parametrize(
    ("table", "column", "bad", "code"),
    [
        ("stops", "stop_id", "", "required_id"),
        ("stops", "stop_id", " 0001", "id_whitespace"),
        ("stops", "stop_lat", "91", "invalid_coordinate"),
        ("stops", "stop_lon", "NaN", "invalid_coordinate"),
        ("stops", "location_type", "9", "invalid_integer_or_enum"),
        ("stops", "parent_station", "ABSENT", "orphan_reference"),
        ("trips", "route_id", "ABSENT", "orphan_reference"),
        ("trips", "service_id", "ABSENT", "unknown_service"),
        ("trips", "direction_id", "3", "invalid_integer_or_enum"),
        ("stop_times", "trip_id", "ABSENT", "orphan_reference"),
        ("stop_times", "stop_id", "ABSENT", "orphan_reference"),
        ("stop_times", "stop_sequence", "-1", "invalid_integer_or_enum"),
        ("stop_times", "stop_sequence", "1.0", "invalid_integer_or_enum"),
        ("stop_times", "pickup_type", "4", "invalid_integer_or_enum"),
        ("stop_times", "drop_off_type", "4", "invalid_integer_or_enum"),
        ("stop_times", "timepoint", "3", "invalid_integer_or_enum"),
        ("stop_times", "arrival_time", "8:60:00", "invalid_gtfs_time"),
        ("stop_times", "departure_time", "25:10:60", "invalid_gtfs_time"),
        ("stop_times", "departure_time", "", "missing_exact_time"),
        ("calendar", "monday", "2", "invalid_integer_or_enum"),
        ("calendar", "start_date", "20260230", "invalid_date"),
        ("calendar", "start_date", "2026-10-01", "invalid_date"),
        ("calendar", "end_date", "20250930", "calendar_range"),
        ("calendar_dates", "exception_type", "3", "invalid_integer_or_enum"),
    ],
)
def test_bad_values_and_relations_block_silver(make_raw, tmp_path, table, column, bad, code):
    files = sample_files()

    def change(columns, rows):
        rows[0][columns.index(column)] = bad

    rewrite(files, table + ".txt", change)
    quality = failed_quality(make_raw(files), tmp_path / "out", batch_size=1)
    assert any(check["code"] == code and check["table"] == table for check in quality["checks"])


@pytest.mark.parametrize(
    "table", ["agency", "stops", "routes", "trips", "stop_times", "calendar", "calendar_dates"]
)
def test_duplicate_keys_across_batches(make_raw, tmp_path, table):
    files = sample_files()
    text = files[table + ".txt"].decode().splitlines()
    files[table + ".txt"] += (text[1] + "\n").encode()
    quality = failed_quality(make_raw(files), tmp_path / "out", batch_size=1)
    assert any(
        check["code"] == "duplicate_key" and check["table"] == table for check in quality["checks"]
    )


def test_unsorted_times_checked_by_sequence_across_batches(make_raw, tmp_path):
    files = sample_files()

    def change(columns, rows):
        rows[0][columns.index("arrival_time")] = "8:30:00"
        rows[0][columns.index("departure_time")] = "8:30:00"

    rewrite(files, "stop_times.txt", change)
    quality = failed_quality(make_raw(files), tmp_path / "out", batch_size=1)
    assert any(check["code"] == "time_decreases" for check in quality["checks"])


def test_reversed_source_order_with_valid_times_passes(make_raw, tmp_path):
    files = sample_files()
    lines = files["stop_times.txt"].decode().splitlines()
    files["stop_times.txt"] = ("\n".join([lines[0], *reversed(lines[1:])]) + "\n").encode()
    result = prepare(make_raw(files), tmp_path / "out", batch_size=1)
    assert document(result.quality_report)["error_count"] == 0


@pytest.mark.parametrize("extra", [b"one\n", b'bad,"unterminated\n', b"\xff,bad\n"])
def test_late_malformed_csv_blocks_bronze(make_raw, tmp_path, extra):
    files = sample_files()
    files["stops.txt"] += extra
    raw = make_raw(files)
    assert (
        document(raw)["validation"]["status"] == "passed"
    )  # Existing validator checks first data.
    with pytest.raises(PrepareError, match="stops") as caught:
        prepare(raw, tmp_path / "out", batch_size=1)
    assert len(caught.value.manifests) == 1
    assert document(caught.value.manifests[0])["status"] == "failed"
    assert not list((tmp_path / "out").glob("silver/gtfs/*/manifest.json"))


@pytest.mark.parametrize(
    "column", ["_wta_source_record", "_wta_any", "arrival_seconds", "_agency_key"]
)
def test_reserved_column_collision(make_raw, tmp_path, column):
    files = sample_files()

    def change(columns, rows):
        columns.append(column)
        for row in rows:
            row.append("collision")

    rewrite(files, "stops.txt", change)
    with pytest.raises(PrepareError, match="Kolizja"):
        prepare(make_raw(files), tmp_path / "out")


@pytest.mark.parametrize(
    "updates",
    [
        {"manifest_version": 2},
        {"manifest_version": True},
        {"sha256": "0" * 64},
        {"size_bytes": 1},
        {"archive_path": "../feed.zip"},
        {"archive_path": "C:/feed.zip"},
        {"archive_path": "/feed.zip"},
        {"archive_path": "sub/../../feed.zip"},
        {"source_kind": "unknown"},
        {"requested_url": "https://example.org/fake-download"},
        {"generated_at": None},
        {"generated_at": "2026-10-07T12:00:00"},
    ],
)
def test_rejected_raw_has_no_downstream_output(make_raw, tmp_path, updates):
    with pytest.raises(PrepareError):
        prepare(make_raw(updates=updates), tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_failed_raw_and_tampered_zip_are_rejected(make_raw, tmp_path):
    raw = make_raw()
    value = document(raw)
    value["validation"]["status"] = "failed"
    raw.write_text(json.dumps(value))
    with pytest.raises(PrepareError, match="raw passed"):
        prepare(raw, tmp_path / "out")
    raw = make_raw()
    with (raw.parent / "feed.zip").open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(PrepareError, match="raw"):
        prepare(raw, tmp_path / "out")


def test_symlink_escape_rejected(make_raw, tmp_path):
    raw = make_raw()
    external = tmp_path / "outside.zip"
    external.write_bytes((raw.parent / "feed.zip").read_bytes())
    link = raw.parent / "link.zip"
    try:
        link.symlink_to(external)
    except OSError:
        pytest.skip("Windows account cannot create symlinks; the Linux CI exercises this guard.")
    value = document(raw)
    value["archive_path"] = "link.zip"
    raw.write_text(json.dumps(value))
    with pytest.raises(PrepareError, match="dowiązanie"):
        prepare(raw, tmp_path / "out")


def test_silver_write_failure_cannot_publish_passed_manifest(make_raw, tmp_path, monkeypatch):
    original = pipeline.pq.ParquetWriter

    class FailingWriter:
        def __init__(self, path, schema, **kwargs):
            self.writer = original(path, schema, **kwargs)

        def __enter__(self):
            return self

        def write_table(self, table):
            raise OSError("simulated storage failure")

        def __exit__(self, *args):
            self.writer.close()

    def writer(path, schema, **kwargs):
        if "silver" in Path(path).parts and Path(path).name == "stop_times.parquet":
            return FailingWriter(path, schema, **kwargs)
        return original(path, schema, **kwargs)

    monkeypatch.setattr(pipeline.pq, "ParquetWriter", writer)
    with pytest.raises(PrepareError, match="simulated storage failure") as caught:
        prepare(make_raw(), tmp_path / "out", batch_size=2)
    bronze, silver = caught.value.manifests
    assert document(bronze)["status"] == "passed"
    assert document(silver)["status"] == "failed"
    assert all(
        document(path)["status"] != "passed"
        for path in (tmp_path / "out").glob("silver/gtfs/**/manifest.json")
    )


def test_json_writer_preserves_unowned_partial_file(tmp_path):
    target = tmp_path / "manifest.json"
    partial = tmp_path / "manifest.json.part"
    partial.write_text("existing")
    with pytest.raises(FileExistsError):
        write_json(target, {"status": "passed"})
    assert partial.read_text() == "existing" and not target.exists()


def test_demo_deterministic_and_cli_full_pipeline(tmp_path, capsys):
    assert sample_zip_bytes() == sample_zip_bytes()
    first, second = write_sample_data(tmp_path / "data"), write_sample_data(tmp_path / "data")
    assert first.sha256 == second.sha256 and first.manifest_path != second.manifest_path
    value = document(first.manifest_path)
    assert value["data_kind"] == "synthetic_demo"
    assert value["requested_url"] is value["final_url"] is value["downloaded_at"] is None
    assert (
        main(
            [
                "prepare",
                "--raw-manifest",
                str(first.manifest_path),
                "--output-root",
                str(tmp_path / "out"),
                "--batch-size",
                "2",
            ]
        )
        == 0
    )
    assert "Prepare passed" in capsys.readouterr().out
    assert main(["sample-data", "--output-root", str(tmp_path / "another")]) == 0
    assert "DANE SYNTETYCZNE" in capsys.readouterr().out
    assert main(["sample-data", "--output-root", str(tmp_path / "json-sample"), "--json"]) == 0
    structured = json.loads(capsys.readouterr().out)
    assert structured["data_kind"] == "synthetic_demo"
    assert Path(structured["raw_manifest"]).is_file()
    assert main(["prepare", "--raw-manifest", str(tmp_path / "missing.json")]) == 1
    assert "Błąd" in capsys.readouterr().err


def test_multi_agency_mapping_and_timezone(make_raw, tmp_path):
    files = sample_files()
    files["agency.txt"] = csv_contents(
        ["agency_id", "agency_name", "agency_url", "agency_timezone"],
        [
            ["A", "Demo A", "https://example.org/a", "Europe/Warsaw"],
            ["B", "Demo B", "https://example.org/b", "Europe/Warsaw"],
        ],
    )

    def change(columns, rows):
        columns.append("agency_id")
        for row in rows:
            row.append("A" if row[0] == "D1" else "B")

    rewrite(files, "routes.txt", change)
    result = prepare(make_raw(files), tmp_path / "out", batch_size=1)
    assert {row["route_id"]: row["_agency_key"] for row in silver_rows(result, "routes")} == {
        "D1": "A",
        "D2": "B",
    }
    assert document(result.quality_report)["agency_count"] == 2
    files["agency.txt"] = files["agency.txt"].replace(b"B,Demo B", b",Demo B")
    quality = failed_quality(make_raw(files), tmp_path / "out")
    assert any(check["code"] == "multi_agency_missing_id" for check in quality["checks"])


def test_multi_agency_requires_explicit_route_mapping(make_raw, tmp_path):
    files = sample_files()
    files["agency.txt"] = csv_contents(
        ["agency_id", "agency_name", "agency_url", "agency_timezone"],
        [
            ["A", "Demo A", "https://example.org/a", "Europe/Warsaw"],
            ["B", "Demo B", "https://example.org/b", "Europe/Warsaw"],
        ],
    )
    quality = failed_quality(make_raw(files), tmp_path / "out")
    assert any(check["code"] == "ambiguous_agency" for check in quality["checks"])


def test_unknown_route_type_and_header_only_frequencies(make_raw, tmp_path):
    files = sample_files()
    files["routes.txt"] = files["routes.txt"].replace(b",0\n", b",9999\n")
    files["frequencies.txt"] = b"trip_id,start_time,end_time,headway_secs\n"
    result = prepare(make_raw(files), tmp_path / "out")
    routes = {row["route_id"]: row for row in silver_rows(result, "routes")}
    assert routes["D1"]["route_type"] == 9999
    assert routes["D1"]["route_type_description"] == "other"
    capabilities = document(result.silver_manifest)["capabilities"]
    assert capabilities["frequencies"]["present"] is True
    assert capabilities["frequencies"]["row_count"] == 0
    assert capabilities["quantitative_gold_supported"] is True


def test_missing_time_does_not_reset_temporal_check(make_raw, tmp_path):
    files = sample_files()

    def change(columns, rows):
        for row in rows:
            if row[0] == "T2" and row[columns.index("stop_sequence")] == "5":
                row[columns.index("arrival_time")] = "08:00:00"
                row[columns.index("departure_time")] = "08:00:00"

    rewrite(files, "stop_times.txt", change)
    quality = failed_quality(make_raw(files), tmp_path / "out", batch_size=1)
    assert any(check["code"] == "time_decreases" for check in quality["checks"])


def test_late_record_byte_limit_is_enforced(make_raw, tmp_path):
    files = sample_files()
    files["stops.txt"] += ("oversized," + "a" * (64 * 1024) + ",51,17,0,\n").encode()
    raw = make_raw(files)
    assert document(raw)["validation"]["status"] == "passed"
    with pytest.raises(PrepareError, match="limit"):
        prepare(raw, tmp_path / "out", batch_size=2)


def test_publication_failure_leaves_no_passed_silver_manifest(make_raw, tmp_path, monkeypatch):
    original = Path.rename

    def rename(path, target):
        if path.parent.name == ".working" and "silver" in path.parts:
            raise OSError("simulated publication failure")
        return original(path, target)

    monkeypatch.setattr(Path, "rename", rename)
    with pytest.raises(PrepareError, match="publication failure") as caught:
        prepare(make_raw(), tmp_path / "out")
    assert document(caught.value.manifests[0])["status"] == "passed"
    assert all(
        document(path)["status"] != "passed"
        for path in (tmp_path / "out").glob("silver/gtfs/**/manifest.json")
    )


def test_existing_zip_validator_rejects_unsafe_member_even_if_raw_claims_passed(make_raw, tmp_path):
    files = {**sample_files(), "../unsafe.txt": b"not admissible"}
    raw = make_raw(
        files,
        updates={
            "validation": {"profile": "wroclaw-static-mvp-v1", "status": "passed", "issues": []}
        },
    )
    with pytest.raises(PrepareError, match="unsafe_path"):
        prepare(raw, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_nonfinite_raw_json_is_rejected(make_raw, tmp_path):
    raw = make_raw()
    value = document(raw)
    value["unrelated"] = float("nan")
    raw.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(PrepareError, match="JSON"):
        prepare(raw, tmp_path / "out")


def test_error_examples_are_bounded_but_counts_complete(make_raw, tmp_path):
    files = sample_files()
    files["stops.txt"] += csv_contents(
        [], [[f" BAD{number}", "Demo", "51", "17", "0", ""] for number in range(80)]
    ).lstrip(b"\n")
    quality = failed_quality(make_raw(files), tmp_path / "out", batch_size=7)
    assert len(quality["examples"]) <= 50
    whitespace = next(
        check
        for check in quality["checks"]
        if check["code"] == "id_whitespace" and check["table"] == "stops"
    )
    assert whitespace["count"] == 80
