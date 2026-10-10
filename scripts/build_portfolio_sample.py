"""Reproduce the small portfolio archive from an already verified local download.

This command never downloads a feed and never changes the original archive/manifest.
ZIP metadata, member order and CSV newline conventions are fixed for reproducibility.
"""

import argparse
import csv
import io
import json
from dataclasses import asdict
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from wroclaw_transit_analytics.gtfs.validation import validate_archive
from wroclaw_transit_analytics.preparation.source import (
    PrepareError,
    file_sha256,
    read_source,
    utc_now,
    write_json,
)

ORIGINAL_SHA256 = "11fccf1a82e170bb2fe3c77c81cfdb6434158e143064b38ff23a3a5888e56f01"
LINES = ("1", "10", "100", "106")
VERSION = "wta-portfolio-v1"
ARCHIVE_NAME = "wroclaw-sample-v1.zip"


def read_table(archive, name):
    with archive.open(name) as stream, io.TextIOWrapper(stream, encoding="utf-8-sig") as text:
        reader = csv.DictReader(text)
        return reader.fieldnames, list(reader)


def csv_bytes(columns, rows):
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return text.getvalue().encode("utf-8")


def build(raw_manifest: Path, destination: Path) -> dict:
    source = read_source(raw_manifest)
    if source.sha256 != ORIGINAL_SHA256 or source.provenance["source_kind"] != "official_https":
        raise PrepareError("Próbka v1 wymaga dokładnie wskazanego, zweryfikowanego oryginału.")
    selected = {}
    counts = {}
    with ZipFile(source.archive_path) as archive:
        columns, routes = read_table(archive, "routes.txt")
        routes = [row for row in routes if row["route_short_name"] in LINES]
        if {row["route_short_name"] for row in routes} != set(LINES):
            raise PrepareError("Oryginał nie zawiera wszystkich wybranych linii.")
        selected["routes.txt"] = csv_bytes(columns, routes)
        route_ids = {row["route_id"] for row in routes}
        columns, trips = read_table(archive, "trips.txt")
        trips = [row for row in trips if row["route_id"] in route_ids]
        selected["trips.txt"] = csv_bytes(columns, trips)
        trip_ids = {row["trip_id"] for row in trips}
        service_ids = {row["service_id"] for row in trips}
        shape_ids = {row["shape_id"] for row in trips if row.get("shape_id")}
        # Stream the largest table; keep its original row order and complete visits.
        with (
            archive.open("stop_times.txt") as stream,
            io.TextIOWrapper(stream, encoding="utf-8-sig") as text,
        ):
            reader = csv.DictReader(text)
            stop_times = [row for row in reader if row["trip_id"] in trip_ids]
            selected["stop_times.txt"] = csv_bytes(reader.fieldnames, stop_times)
        stop_ids = {row["stop_id"] for row in stop_times}
        columns, stops = read_table(archive, "stops.txt")
        by_id = {row["stop_id"]: row for row in stops}
        pending = list(stop_ids)
        while pending:
            parent = by_id[pending.pop()].get("parent_station")
            if parent and parent not in stop_ids:
                stop_ids.add(parent)
                pending.append(parent)
        selected["stops.txt"] = csv_bytes(
            columns, [row for row in stops if row["stop_id"] in stop_ids]
        )
        columns, agencies = read_table(archive, "agency.txt")
        agency_ids = {row.get("agency_id") for row in routes if row.get("agency_id")}
        if agency_ids:
            agencies = [row for row in agencies if row.get("agency_id") in agency_ids]
        selected["agency.txt"] = csv_bytes(columns, agencies)
        for name in ("calendar.txt", "calendar_dates.txt"):
            if name in archive.namelist():
                columns, rows = read_table(archive, name)
                selected[name] = csv_bytes(
                    columns, [row for row in rows if row["service_id"] in service_ids]
                )
        columns, shapes = read_table(archive, "shapes.txt")
        selected["shapes.txt"] = csv_bytes(
            columns, [row for row in shapes if row["shape_id"] in shape_ids]
        )
    for name, content in selected.items():
        counts[name.removesuffix(".txt")] = (
            len(list(csv.reader(io.StringIO(content.decode("utf-8"))))) - 1
        )
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / ARCHIVE_NAME
    with archive_path.open("xb") as stream, ZipFile(stream, "w") as archive:
        for name, contents in sorted(selected.items()):
            member = ZipInfo(name, date_time=(2026, 10, 10, 0, 0, 0))
            member.compress_type = ZIP_DEFLATED
            member.create_system = 3
            member.external_attr = 0o100644 << 16
            archive.writestr(member, contents, compresslevel=9)
    validation = validate_archive(archive_path)
    if validation.status != "passed":
        raise PrepareError("Próbka nie przeszła istniejącej walidacji ZIP.")
    sample_hash = file_sha256(archive_path)
    derivative = {
        "version": VERSION,
        "notice": "Próbka archiwalnego rozkładu — wybrane linie, nie cała sieć",
        "original": {
            field: source.manifest[field]
            for field in ("requested_url", "final_url", "catalog_url", "downloaded_at", "sha256")
        },
        "sample_sha256": sample_hash,
        "selection": {
            "route_short_names": list(LINES),
            "rule": "All trips and visits of the selected lines; referenced agencies, stops and "
            "recursive parent stations, services, calendar exceptions and complete shapes. "
            "Original identifiers, row order, times and calendar dates are retained.",
            "reproduction_script": "scripts/build_portfolio_sample.py",
            "zip_metadata": "Sorted members; UTC-date 2026-10-10 00:00:00; Unix mode 100644; "
            "UTF-8 CSV with LF newlines; DEFLATE level 9.",
        },
        "license": {
            "identifier": "CC0-1.0",
            "url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "metadata_url": "https://open-data.cui.wroclaw.pl/hdb/metadane/13/",
            "checked_at": "2026-10-10",
            "publisher": "Urząd Miejski Wrocławia — Wydział Transportu",
        },
        "row_counts": counts,
    }
    manifest = {
        "manifest_version": 1,
        "run_id": VERSION,
        "source_kind": "local_derivative",
        "data_kind": "real_gtfs",
        "archive_path": ARCHIVE_NAME,
        "requested_url": None,
        "final_url": None,
        "catalog_url": None,
        "downloaded_at": None,
        "generated_at": utc_now(),
        "size_bytes": archive_path.stat().st_size,
        "sha256": sample_hash,
        "validation": {**asdict(validation), "status": validation.status},
        "derivative_sample": derivative,
    }
    source.verify_bytes()
    write_json(destination / "manifest.json", manifest)
    return {"archive": ARCHIVE_NAME, "size_bytes": manifest["size_bytes"], **derivative}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.raw_manifest, args.output_dir), ensure_ascii=False, indent=2))
