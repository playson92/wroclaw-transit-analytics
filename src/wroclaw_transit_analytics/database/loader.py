"""One verified dataset, one transaction, COPY and per-dataset serialization."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq
from psycopg import sql
from psycopg.types.json import Jsonb

from ..preparation.contract import GENERATED, SPECS, TABLES
from ..preparation.source import SOURCE_RECORD
from .connection import DatabaseError, connect
from .verification import verified_silver

LOAD_ORDER = ("agency", "stops", "routes", "calendar", "calendar_dates", "trips", "stop_times")
SQL_COLUMNS = {name: (*SPECS[name], SOURCE_RECORD, *GENERATED.get(name, {})) for name in TABLES}


@dataclass(frozen=True)
class LoadResult:
    status: str
    dataset_id: str
    fingerprint: str
    row_counts: dict[str, int]


def _copy_table(connection, verified, name: str, batch_size: int) -> None:
    columns = SQL_COLUMNS[name]
    query = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier("silver", name),
        sql.SQL(", ").join(map(sql.Identifier, ("dataset_id", *columns, "extra_fields"))),
    )
    stream = verified.streams[name]
    stream.seek(0)
    with connection.cursor().copy(query) as copy:
        for batch in pq.ParquetFile(stream).iter_batches(batch_size=batch_size):
            # At most one batch, including original nullable text/IDs and exact int64s.
            for row in batch.to_pylist():
                extras = {key: value for key, value in row.items() if key not in columns}
                copy.write_row(
                    (verified.manifest["dataset_id"], *(row[col] for col in columns), Jsonb(extras))
                )


def load_silver(
    path: Path, database_url: str | None = None, *, batch_size: int = 50_000
) -> LoadResult:
    # Validation also happens for ALREADY_LOADED and before connecting to the database.
    with verified_silver(path, batch_size=batch_size) as verified:
        manifest = verified.manifest
        identity = manifest["dataset_id"]
        counts = {name: entry["row_count"] for name, entry in manifest["tables"].items()}
        lock_key = int.from_bytes(
            hashlib.sha256(identity.encode()).digest()[:8], "big", signed=True
        )
        with connect(database_url) as connection, connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
            existing = connection.execute(
                "SELECT source_sha256, model_version, logical_fingerprint, status "
                "FROM meta.datasets WHERE dataset_id = %s",
                (identity,),
            ).fetchone()
            if existing:
                if existing != (
                    manifest["source_sha256"],
                    manifest["model_version"],
                    verified.fingerprint,
                    "complete",
                ):
                    raise DatabaseError(
                        "CONFLICT: dataset_id ma inną zawartość lub metadane; overwrite zabronione."
                    )
                verified.assert_unchanged()
                return LoadResult("ALREADY_LOADED", identity, verified.fingerprint, counts)
            connection.execute(
                "INSERT INTO meta.datasets (dataset_id, source_sha256, model_version, "
                "logical_fingerprint, provenance, data_kind, capabilities, status, source_manifest, "
                "quality_report) VALUES (%s,%s,%s,%s,%s,%s,%s,'complete',%s,%s)",
                (
                    identity,
                    manifest["source_sha256"],
                    manifest["model_version"],
                    verified.fingerprint,
                    Jsonb(manifest["source"]),
                    manifest["data_kind"],
                    Jsonb(manifest["capabilities"]),
                    Jsonb(manifest),
                    Jsonb(verified.quality),
                ),
            )
            for name in LOAD_ORDER:
                _copy_table(connection, verified, name, batch_size)
                if name == "calendar_dates":
                    connection.execute(
                        "INSERT INTO silver.services (dataset_id, service_id) "
                        "SELECT dataset_id, service_id FROM silver.calendar WHERE dataset_id=%s "
                        "UNION SELECT dataset_id, service_id FROM silver.calendar_dates WHERE dataset_id=%s",
                        (identity, identity),
                    )
            verified.assert_unchanged()
        return LoadResult("LOADED", identity, verified.fingerprint, counts)
