"""The public sample is real, closed over references and uses the normal parser."""

import csv
import io
import json
from pathlib import Path
from zipfile import ZipFile

import pyarrow.parquet as pq
import pytest

from wroclaw_transit_analytics.database import DatabaseError
from wroclaw_transit_analytics.database.verification import verified_silver
from wroclaw_transit_analytics.portfolio import runtime
from wroclaw_transit_analytics.preparation import prepare
from wroclaw_transit_analytics.preparation.source import PrepareError, read_source

ASSETS = Path(runtime.__file__).with_name("assets")
MANIFEST = ASSETS / "manifest.json"


def tables():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    with ZipFile(ASSETS / manifest["archive_path"]) as archive:
        return {
            name.removesuffix(".txt"): list(
                csv.DictReader(io.StringIO(archive.read(name).decode("utf-8")))
            )
            for name in archive.namelist()
        }


def test_sample_is_an_explicit_derivative_not_a_fake_http_download():
    source = read_source(MANIFEST)
    assert source.provenance["source_kind"] == "local_derivative"
    assert source.provenance["data_kind"] == "real_gtfs"
    assert source.provenance["downloaded_at"] is None
    derivative = source.provenance["derivative_sample"]
    assert derivative["original"]["sha256"] != source.sha256
    assert derivative["sample_sha256"] == source.sha256
    assert derivative["license"]["identifier"] == "CC0-1.0"
    assert source.archive_path.stat().st_size < 2_000_000
    assert not any(token in MANIFEST.read_text() for token in ("C:\\", "jonat", "/Users/"))


def test_reference_closure_and_representative_real_courses():
    data = tables()
    routes = {row["route_id"]: row for row in data["routes"]}
    trips = {row["trip_id"]: row for row in data["trips"]}
    stops = {row["stop_id"]: row for row in data["stops"]}
    services = {row["service_id"] for row in data["calendar"] + data["calendar_dates"]}
    shapes = {row["shape_id"] for row in data["shapes"]}
    agencies = {row["agency_id"] for row in data["agency"]}
    assert {row["route_short_name"] for row in routes.values()} == {"1", "10", "100", "106"}
    assert {row["route_type"] for row in routes.values()} >= {"0", "3"}
    assert all(row["agency_id"] in agencies for row in routes.values())
    assert all(
        row["route_id"] in routes and row["service_id"] in services for row in trips.values()
    )
    assert all(row["shape_id"] in shapes for row in trips.values())
    assert all(
        not row.get("parent_station") or row["parent_station"] in stops for row in stops.values()
    )
    assert all(row["trip_id"] in trips and row["stop_id"] in stops for row in data["stop_times"])
    for route in routes:
        assert {row["direction_id"] for row in trips.values() if row["route_id"] == route} >= {
            "0",
            "1",
        }
    assert any(int(row["departure_time"].split(":")[0]) >= 24 for row in data["stop_times"])
    assert any("Ś" in row["stop_name"] or "ą" in row["stop_name"] for row in stops.values())
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["derivative_sample"]["row_counts"]
    assert {name: len(rows) for name, rows in data.items()} == expected


def test_sample_passes_existing_prepare_and_retains_provenance(tmp_path):
    prepared = prepare(MANIFEST, tmp_path / "output")
    silver = json.loads(prepared.silver_manifest.read_text(encoding="utf-8"))
    quality = json.loads(prepared.quality_report.read_text(encoding="utf-8"))
    assert quality["status"] == "passed" and quality["error_count"] == 0
    assert silver["source"]["source_kind"] == "local_derivative"
    assert silver["source"]["derivative_sample"]["sample_sha256"] == silver["source_sha256"]
    stop_times = pq.read_table(prepared.silver_manifest.parent / "stop_times.parquet")
    assert max(stop_times["departure_seconds"].drop_null().to_pylist()) >= 24 * 3600
    assert silver["tables"]["trips"]["row_count"] == len(tables()["trips"])
    with verified_silver(prepared.silver_manifest) as verified:
        assert (
            verified.manifest["source"]["derivative_sample"]["sample_sha256"]
            == silver["source_sha256"]
        )


@pytest.mark.parametrize(
    "broken",
    [
        "http_claim",
        "sample_hash",
        "original_hash",
        "license",
        "numeric_url",
        "numeric_hash",
        "invalid_license_url",
    ],
)
def test_derivative_admission_rejects_misleading_provenance(tmp_path, broken):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["archive_path"] = "sample.zip"
    if broken == "http_claim":
        manifest["downloaded_at"] = "2026-10-10T00:00:00+00:00"
    elif broken == "sample_hash":
        manifest["derivative_sample"]["sample_sha256"] = "0" * 64
    elif broken == "original_hash":
        manifest["derivative_sample"]["original"]["sha256"] = "not-a-hash"
    elif broken == "numeric_url":
        manifest["derivative_sample"]["original"]["final_url"] = 1
    elif broken == "numeric_hash":
        manifest["derivative_sample"]["original"]["sha256"] = int("1" * 64)
    elif broken == "invalid_license_url":
        manifest["derivative_sample"]["license"]["url"] = "https://"
    else:
        manifest["derivative_sample"].pop("license")
    (tmp_path / "sample.zip").write_bytes((ASSETS / "wroclaw-sample-v1.zip").read_bytes())
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PrepareError):
        read_source(path)


@pytest.fixture(scope="module")
def prepared_sample(tmp_path_factory):
    return prepare(MANIFEST, tmp_path_factory.mktemp("derived-silver"))


@pytest.mark.parametrize(
    "broken",
    [
        "unknown_kind",
        "synthetic_kind",
        "sample_hash",
        "http_claim",
        "original_url",
        "license",
        "numeric_url",
        "numeric_hash",
        "invalid_license_url",
    ],
)
def test_loader_rejects_unknown_or_misleading_derivative_sources(prepared_sample, broken):
    manifest = json.loads(prepared_sample.silver_manifest.read_text(encoding="utf-8"))
    source = manifest["source"]
    if broken == "unknown_kind":
        source["source_kind"] = "unknown"
    elif broken == "synthetic_kind":
        source["source_kind"] = "local_synthetic"
    elif broken == "sample_hash":
        source["derivative_sample"]["sample_sha256"] = "f" * 64
    elif broken == "http_claim":
        source["requested_url"] = "https://open-data.cui.wroclaw.pl/hdb/download/141/"
    elif broken == "original_url":
        source["derivative_sample"]["original"]["final_url"] = "https://example.org/feed.zip"
    elif broken == "numeric_url":
        source["derivative_sample"]["original"]["final_url"] = True
    elif broken == "numeric_hash":
        source["derivative_sample"]["original"]["sha256"] = int("1" * 64)
    elif broken == "invalid_license_url":
        source["derivative_sample"]["license"]["url"] = "https://"
    else:
        source["derivative_sample"]["license"] = {}
    path = prepared_sample.silver_manifest.with_name(f"tampered-{broken}.json")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DatabaseError):
        with verified_silver(path):
            pytest.fail("Misleading derivative provenance must fail before loader admission.")
