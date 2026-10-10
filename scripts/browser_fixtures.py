"""Two explicit synthetic snapshots through the existing prepare/load/analyze pipeline.

Run only against a disposable Compose test project, never the user's explorer database.
The standard demo and its 16/25/2/3 smoke checks remain independent of these fixtures.
"""

import argparse
import csv
import hashlib
import io
import json
import os
from dataclasses import asdict
from datetime import date
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import psycopg

from wroclaw_transit_analytics.analytics.runner import analyze
from wroclaw_transit_analytics.database.loader import load_silver
from wroclaw_transit_analytics.explorer.geometry import import_geometry
from wroclaw_transit_analytics.gtfs.validation import validate_archive
from wroclaw_transit_analytics.preparation.pipeline import prepare
from wroclaw_transit_analytics.sample_data import sample_files, write_sample_data


def csv_bytes(records):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(records[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return stream.getvalue().encode("utf-8")


def snapshot_files(label, start, end):
    tables = {
        name: list(csv.DictReader(io.StringIO(contents.decode("utf-8"))))
        for name, contents in sample_files().items()
    }
    for row in tables["calendar.txt"]:
        row["start_date"], row["end_date"] = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        # Fixtures deliberately have daily WD service; the ordinary demo keeps its own rules.
        for weekday in (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ):
            row[weekday] = "1" if row["service_id"] == "WD" else "0"
    for row in tables["calendar_dates.txt"]:
        row["date"] = (
            end.strftime("%Y%m%d") if row["date"] == "20261007" else start.strftime("%Y%m%d")
        )
    for row in tables["trips.txt"]:
        row["trip_id"] = label + "_" + row["trip_id"]
        row["trip_headsign"] = label + " " + row["trip_headsign"]
    for row in tables["stop_times.txt"]:
        row["trip_id"] = label + "_" + row["trip_id"]
    for row in tables["stops.txt"]:
        row["stop_name"] = label + " " + row["stop_name"] if row["stop_name"] else ""
    return {name: csv_bytes(records) for name, records in tables.items()}


def create_snapshot(root, label, start, end):
    sample = write_sample_data(root / label)
    # Only freshly generated, uniquely owned fixture files are modified.
    with ZipFile(sample.archive_path, "w") as archive:
        for name, contents in sorted(snapshot_files(label, start, end).items()):
            member = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            member.compress_type = ZIP_STORED
            member.create_system = 3
            member.external_attr = 0o100644 << 16
            archive.writestr(member, contents)
    validation = validate_archive(sample.archive_path)
    assert validation.status == "passed", validation.issues
    raw = json.loads(sample.manifest_path.read_text(encoding="utf-8"))
    raw.update(
        demo_version="wta-browser-disjoint-v1-" + label,
        sha256=hashlib.sha256(sample.archive_path.read_bytes()).hexdigest(),
        size_bytes=sample.archive_path.stat().st_size,
        validation={**asdict(validation), "status": validation.status},
    )
    sample.manifest_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    prepared = prepare(sample.manifest_path, root / label)
    loaded = load_silver(prepared.silver_manifest)
    repeated = load_silver(prepared.silver_manifest)
    assert repeated.status == "ALREADY_LOADED"
    analyzed = analyze(loaded.dataset_id, start, end)
    geometry = import_geometry(sample.manifest_path)
    assert geometry["geometry_status"] == "absent"
    return {
        "dataset_id": loaded.dataset_id,
        "analysis_id": analyzed.analysis_id,
        "data_kind": "synthetic_demo",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "prefix": label,
        "load": loaded.status,
        "repeat": repeated.status,
        "geometry": geometry["geometry_status"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("/work"))
    parser.add_argument("--verify", type=Path, help="Verify saved fixture identities after restart")
    args = parser.parse_args()
    if os.environ.get("WTA_BROWSER_FIXTURE_PROJECT") != "1":
        raise SystemExit(
            "Refusing fixture load: set WTA_BROWSER_FIXTURE_PROJECT=1 only in a disposable test project"
        )
    if args.verify:
        evidence = json.loads(args.verify.read_text(encoding="utf-8"))
    else:
        root = args.output_root.resolve() / ("browser-fixtures-" + uuid4().hex)
        root.mkdir(parents=True, exist_ok=False)
        evidence = {
            "version": "wta-browser-disjoint-v1",
            "A": create_snapshot(root, "A", date(2026, 10, 10), date(2026, 10, 16)),
            "B": create_snapshot(root, "B", date(2026, 10, 1), date(2026, 10, 7)),
        }
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        counts = {
            "datasets": conn.execute(
                "SELECT count(*) FROM meta.datasets WHERE status='complete'"
            ).fetchone()[0],
            "analyses": conn.execute(
                "SELECT count(*) FROM meta.analyses WHERE status='complete'"
            ).fetchone()[0],
            "route_daily": conn.execute("SELECT count(*) FROM gold.route_daily").fetchone()[0],
        }
        if args.verify:
            assert counts == evidence["persistence"], "Snapshot row counts changed after restart"
        else:
            evidence["persistence"] = counts
        for label in ("A", "B"):
            record = evidence[label]
            saved = conn.execute(
                "SELECT status,data_kind FROM meta.datasets WHERE dataset_id=%s",
                (record["dataset_id"],),
            ).fetchone()
            assert saved == ("complete", "synthetic_demo"), saved
            analysis = conn.execute(
                "SELECT status,start_date,end_date FROM meta.analyses WHERE analysis_id=%s AND dataset_id=%s",
                (record["analysis_id"], record["dataset_id"]),
            ).fetchone()
            assert analysis == (
                "complete",
                date.fromisoformat(record["start"]),
                date.fromisoformat(record["end"]),
            )
            assert (
                conn.execute(
                    "SELECT count(*) FROM gold.route_daily WHERE dataset_id=%s AND analysis_id=%s",
                    (record["dataset_id"], record["analysis_id"]),
                ).fetchone()[0]
                == 14
            )
    if not args.verify:
        (args.output_root / "browser-fixtures.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
