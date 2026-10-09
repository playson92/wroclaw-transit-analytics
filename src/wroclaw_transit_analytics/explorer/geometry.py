"""Append-only, bounded shapes import from the verified raw snapshot, never from UI reruns."""

import math
from pathlib import Path
from zipfile import ZipFile

from ..database.connection import DatabaseError, connect
from ..gtfs.config import DEFAULT_LIMITS
from ..preparation.csv_reader import read_header, read_record
from ..preparation.source import PrepareError, dataset_id, read_source

MAX_POINTS = 2_000_000


def import_geometry(raw_manifest: Path, database_url: str | None = None) -> dict:
    source = read_source(raw_manifest)
    identity = dataset_id(source.sha256)
    try:
        with connect(database_url) as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (identity,))
            saved = conn.execute(
                "SELECT source_sha256 FROM meta.datasets WHERE dataset_id=%s AND status='complete'",
                (identity,),
            ).fetchone()
            if saved != (source.sha256,):
                raise DatabaseError("Najpierw załaduj silver z dokładnie tego snapshotu.")
            existing = conn.execute(
                "SELECT status,point_count,source_sha256 FROM explorer.geometry_imports "
                "WHERE dataset_id=%s",
                (identity,),
            ).fetchone()
            if existing:
                if existing[2] != source.sha256:
                    raise DatabaseError("Konflikt geometrii; istniejący import pozostał bez zmian.")
                source.verify_bytes()
                return {
                    "status": "ALREADY_IMPORTED",
                    "dataset_id": identity,
                    "geometry_status": existing[0],
                    "point_count": existing[1],
                }
            with ZipFile(source.archive_path) as archive:
                present = "shapes.txt" in archive.namelist()
                count = 0
                if present:
                    with (
                        archive.open("shapes.txt") as stream,
                        conn.cursor().copy(
                            "COPY explorer.shape_points "
                            "(dataset_id,source_sha256,shape_id,shape_pt_sequence,latitude,longitude) "
                            "FROM STDIN"
                        ) as copy,
                    ):
                        columns = read_header(stream, "shapes", DEFAULT_LIMITS)
                        required = {"shape_id", "shape_pt_sequence", "shape_pt_lat", "shape_pt_lon"}
                        if not required <= set(columns):
                            raise PrepareError("Brak wymaganych kolumn shapes.txt.")
                        while (
                            row := read_record(stream, DEFAULT_LIMITS.max_record_bytes)
                        ) is not None:
                            if not any(field.strip() for field in row):
                                continue
                            if len(row) != len(columns):
                                raise PrepareError("Niepoprawna szerokość rekordu shapes.txt.")
                            record = dict(zip(columns, row, strict=True))
                            shape = record["shape_id"]
                            sequence = int(record["shape_pt_sequence"])
                            latitude, longitude = (
                                float(record["shape_pt_lat"]),
                                float(record["shape_pt_lon"]),
                            )
                            if (
                                not shape
                                or sequence < 0
                                or sequence > 2**63 - 1
                                or not math.isfinite(latitude)
                                or not math.isfinite(longitude)
                                or not -90 <= latitude <= 90
                                or not -180 <= longitude <= 180
                            ):
                                raise PrepareError(
                                    "Niepoprawny identyfikator, sekwencja lub współrzędne shapes."
                                )
                            count += 1
                            if count > MAX_POINTS:
                                raise PrepareError("Przekroczono limit punktów shapes.")
                            copy.write_row(
                                (identity, source.sha256, shape, sequence, latitude, longitude)
                            )
                conn.execute(
                    "INSERT INTO explorer.geometry_imports "
                    "(dataset_id,source_sha256,importer_version,status,point_count) "
                    "VALUES (%s,%s,'wta-shapes-v1',%s,%s)",
                    (identity, source.sha256, "complete" if present else "absent", count),
                )
                source.verify_bytes()
            return {
                "status": "IMPORTED",
                "dataset_id": identity,
                "source_sha256": source.sha256,
                "geometry_status": "complete" if present else "absent",
                "point_count": count,
            }
    except (ValueError, OverflowError, OSError) as exc:
        raise PrepareError("Niepoprawny plik shapes; import wycofano.") from exc
