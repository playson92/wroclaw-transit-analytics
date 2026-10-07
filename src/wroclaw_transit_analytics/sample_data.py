"""Small deterministic, explicitly synthetic GTFS; source bytes never resemble a live download."""

import csv
import hashlib
import io
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from .gtfs.validation import validate_archive
from .preparation.source import PrepareError, utc_now, write_json

DEMO_VERSION = "wta-synthetic-v1"


def _csv(columns: list[str], rows: list[list]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def sample_files() -> dict[str, bytes]:
    """Return fresh source tables, also useful for small independently modified test feeds."""
    trips = [
        ["D1", "WD", "T1", "0", "Demo Pętla"],
        ["D1", "WD", "T2", "0", "Demo Pętla"],
        ["D2", "WD", "LATE", "1", "Demo Centrum"],
        ["D1", "WE", "WEEKEND", "", "Demo Pętla"],
        ["D2", "EXTRA", "EXTRA", "0", "Demo pętla powrotna"],
    ]
    timings = (
        ("T1", ("8:00:00", "8:10:00", "8:20:00")),
        ("T2", ("08:30:00", "", "08:55:00")),
        ("LATE", ("23:50:00", "24:10:00", "25:10:00")),
        ("WEEKEND", ("09:00:00", "09:10:00", "09:20:00")),
        ("EXTRA", ("10:00:00", "10:10:00", "10:20:00")),
    )
    events = []
    for trip, times in timings:
        for position, (sequence, time) in enumerate(zip((0, 2, 5), times, strict=True)):
            stop = ("0001", "NA", "NULL")[position]
            if trip == "EXTRA" and position == 2:
                stop = "0001"  # Repeated visit, distinct stop_sequence.
            pickup = "1" if position == 2 else "2" if trip == "WEEKEND" and position == 1 else ""
            events.append([trip, time, time, stop, sequence, pickup, "", "0" if not time else "1"])
    return {
        "agency.txt": _csv(
            ["agency_name", "agency_url", "agency_timezone"],
            [["WTA — DANE SYNTETYCZNE", "https://example.org/synthetic-transit", "Europe/Warsaw"]],
        ),
        "stops.txt": _csv(
            ["stop_id", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station"],
            [
                ["0001", "Demo Centrum", "51.10", "17.03", "", "STATION"],
                ["NA", "Demo Plac", "51.11", "17.04", "0", ""],
                ["NULL", "Demo Pętla", "51.12", "17.05", "0", ""],
                ["STATION", "Demo Stacja", "51.10", "17.03", "1", ""],
                ["ENTRANCE", "Demo Wejście", "51.101", "17.031", "2", "STATION"],
                ["NODE", "", "", "", "3", "STATION"],
                ["AREA", "", "", "", "4", "0001"],
            ],
        ),
        "routes.txt": _csv(
            ["route_id", "route_short_name", "route_long_name", "route_type"],
            [["D1", "D1", "Linia syntetyczna pierwsza", "0"], ["D2", "D2", "Linia demo", "3"]],
        ),
        "trips.txt": _csv(
            ["route_id", "service_id", "trip_id", "direction_id", "trip_headsign"], trips
        ),
        "stop_times.txt": _csv(
            [
                "trip_id",
                "arrival_time",
                "departure_time",
                "stop_id",
                "stop_sequence",
                "pickup_type",
                "drop_off_type",
                "timepoint",
            ],
            events,
        ),
        "calendar.txt": _csv(
            [
                "service_id",
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
                "start_date",
                "end_date",
            ],
            [
                ["WD", 1, 1, 1, 1, 1, 0, 0, "20261001", "20261031"],
                ["WE", 0, 0, 0, 0, 0, 1, 1, "20261001", "20261031"],
            ],
        ),
        "calendar_dates.txt": _csv(
            ["service_id", "date", "exception_type"],
            [["WD", "20261007", 2], ["WE", "20261006", 1], ["EXTRA", "20261007", 1]],
        ),
    }


def sample_zip_bytes() -> bytes:
    """Fixed member order, timestamps, permissions and stored compression."""
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, contents in sorted(sample_files().items()):
            member = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            member.compress_type = ZIP_STORED
            member.create_system = 3
            member.external_attr = 0o100644 << 16
            archive.writestr(member, contents)
    return buffer.getvalue()


@dataclass(frozen=True)
class SampleResult:
    manifest_path: Path
    archive_path: Path
    sha256: str


def write_sample_data(output_root: Path = Path("data")) -> SampleResult:
    run_id = f"sample_{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}_{uuid4().hex}"
    root = output_root.resolve() / "raw" / "gtfs" / "demo" / run_id
    root.mkdir(parents=True, exist_ok=False)
    archive_path = root / "feed.zip"
    contents = sample_zip_bytes()
    with archive_path.open("xb") as stream:
        stream.write(contents)
    validation = validate_archive(archive_path)
    if validation.status != "passed":
        raise PrepareError(f"Generator demo nie przeszedł walidacji: {validation.issues}")
    sha256 = hashlib.sha256(contents).hexdigest()
    manifest = {
        "manifest_version": 1,
        "run_id": run_id,
        "demo_version": DEMO_VERSION,
        "source_kind": "local_synthetic",
        "data_kind": "synthetic_demo",
        "archive_path": "feed.zip",
        "requested_url": None,
        "final_url": None,
        "catalog_url": None,
        "downloaded_at": None,
        "generated_at": utc_now(),
        "size_bytes": len(contents),
        "sha256": sha256,
        "content_type": "application/zip",
        "etag": None,
        "last_modified": None,
        "validation": {**asdict(validation), "status": validation.status},
    }
    manifest_path = root / "manifest.json"
    write_json(manifest_path, manifest)
    return SampleResult(manifest_path, archive_path, sha256)
