"""Small real ZIP/Parquet fixtures, independent expected values, no network."""

import csv
import hashlib
import io
import json
from dataclasses import asdict
from zipfile import ZIP_STORED, ZipFile

import pytest

from wroclaw_transit_analytics.gtfs.validation import validate_archive
from wroclaw_transit_analytics.sample_data import sample_files


def rewrite(files: dict[str, bytes], name: str, change) -> None:
    rows = list(csv.reader(io.StringIO(files[name].decode("utf-8-sig"))))
    change(rows[0], rows[1:])
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    files[name] = stream.getvalue().encode("utf-8")


def csv_contents(columns, rows) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


@pytest.fixture
def make_raw(tmp_path):
    created = 0

    def create(files=None, updates=None):
        nonlocal created
        created += 1
        root = tmp_path / f"raw-{created}"
        root.mkdir()
        archive_path = root / "feed.zip"
        with ZipFile(archive_path, "w", compression=ZIP_STORED) as archive:
            for name, contents in (sample_files() if files is None else files).items():
                archive.writestr(name, contents)
        validation = validate_archive(archive_path)
        manifest = {
            "manifest_version": 1,
            "run_id": f"test-{created}",
            "source_kind": "local_synthetic",
            "data_kind": "synthetic_demo",
            "archive_path": "feed.zip",
            "requested_url": None,
            "final_url": None,
            "catalog_url": None,
            "downloaded_at": None,
            "generated_at": "2026-10-07T00:00:00+00:00",
            "size_bytes": archive_path.stat().st_size,
            "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            "validation": {**asdict(validation), "status": validation.status},
        }
        if updates:
            manifest.update(updates)
        path = root / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return path

    return create
