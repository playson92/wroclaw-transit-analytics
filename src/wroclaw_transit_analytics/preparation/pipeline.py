"""Raw -> streamed bronze -> typed silver, with publication after completion."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from zipfile import ZipFile

import pyarrow as pa
import pyarrow.parquet as pq

from ..gtfs.config import DEFAULT_LIMITS, Limits
from .contract import (
    OPTIONAL_TABLES,
    SPECS,
    TABLES,
    Diagnostics,
    content_digest,
    convert,
    schema_for,
    update_digest,
)
from .csv_reader import batches, read_header
from .quality import QualityIndex
from .source import (
    MODEL_VERSION,
    PrepareError,
    dataset_id,
    file_sha256,
    read_source,
    utc_now,
    write_json,
)


@dataclass(frozen=True)
class PrepareResult:
    dataset_id: str
    processing_run_id: str
    bronze_manifest: Path
    silver_manifest: Path
    quality_report: Path
    data_kind: str


def _write_table(path: Path, schema: pa.Schema, frames) -> dict:
    started = perf_counter()
    digest = content_digest(schema)
    count = 0
    with pq.ParquetWriter(path, schema, compression="zstd") as writer:
        for frame in frames:
            frame = frame.loc[:, schema.names]
            arrow = pa.Table.from_pandas(frame, schema=schema, preserve_index=False, safe=True)
            writer.write_table(arrow.replace_schema_metadata(None))
            update_digest(digest, frame)
            count += len(frame)
    return {
        "path": path.name,
        "row_count": count,
        "size_bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "content_sha256": digest.hexdigest(),
        "columns": [
            {"name": field.name, "type": str(field.type), "nullable": field.nullable}
            for field in schema
        ],
        "processing_seconds": round(perf_counter() - started, 6),
    }


def _stage_paths(output_root: Path, stage: str, run_id: str) -> tuple[Path, Path]:
    parent = output_root / stage / "gtfs"
    working = parent / ".working" / run_id
    working.mkdir(parents=True, exist_ok=False)
    return working, parent / run_id


def _publish(working: Path, destination: Path, manifest: dict) -> Path:
    if destination.exists() or destination.is_symlink():
        raise PrepareError(f"Katalog wynikowy już istnieje: {destination}")
    path = working / "manifest.json"
    try:
        write_json(path, manifest)
        working.rename(destination)
    except OSError:
        # A failed publication must not leave an apparently successful manifest.
        path.unlink(missing_ok=True)
        raise
    return destination / "manifest.json"


def _failure(working: Path, destination: Path, manifest: dict, error: Exception) -> Path | None:
    failed = {
        **manifest,
        "status": "failed",
        "completed_at": utc_now(),
        "failure": {"message": str(error)},
    }
    try:
        return _publish(working, destination, failed)
    except (OSError, PrepareError):
        # Retain private partial files; they are never advertised as completed output.
        path = working / "manifest.json"
        return path if path.is_file() else None


def prepare(
    raw_manifest: Path,
    output_root: Path = Path("data"),
    *,
    batch_size: int = 50_000,
    limits: Limits = DEFAULT_LIMITS,
) -> PrepareResult:
    if type(batch_size) is not int or not 0 < batch_size <= 1_000_000:
        raise PrepareError("batch_size musi być liczbą całkowitą z zakresu 1..1000000.")
    source = read_source(raw_manifest, limits)
    started = perf_counter()
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}_{uuid4().hex}"
    identity = dataset_id(source.sha256)
    base = {
        "manifest_version": 1,
        "model_version": MODEL_VERSION,
        "dataset_id": identity,
        "processing_run_id": run_id,
        "source_sha256": source.sha256,
        "created_at": utc_now(),
        "source": source.provenance,
        "data_kind": source.provenance["data_kind"],
        "input": {
            "raw_manifest": str(source.manifest_path),
            "raw_manifest_sha256": source.manifest_sha256,
            "raw_run_id": source.manifest["run_id"],
            "archive_path": str(source.archive_path),
        },
        "batch_size": batch_size,
    }
    root = output_root.resolve()
    bronze_tables: dict = {}
    bronze_base = {**base, "stage": "bronze", "tables": bronze_tables}
    try:
        bronze_work, bronze_destination = _stage_paths(root, "bronze", run_id)
    except OSError as exc:
        raise PrepareError(f"Nie można utworzyć katalogu bronze: {exc}") from exc
    try:
        with ZipFile(source.archive_path) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            names = {item.filename for item in members}
            inventory = [
                {
                    "name": item.filename,
                    "size_bytes": item.file_size,
                    "handling": (
                        "bronze_and_silver"
                        if item.filename in {table + ".txt" for table in TABLES}
                        else "bronze_only"
                        if item.filename == "frequencies.txt"
                        else "raw_only"
                    ),
                }
                for item in members
            ]
            for table in (*TABLES, "frequencies"):
                filename = table + ".txt"
                if filename not in names:
                    if table not in OPTIONAL_TABLES and table != "frequencies":
                        raise PrepareError(f"Brak wymaganej tabeli {filename}.")
                    bronze_tables[table] = {
                        "source_present": False,
                        "path": None,
                        "row_count": 0,
                        "source_columns": [],
                    }
                    continue
                with archive.open(filename) as stream:
                    columns = read_header(stream, table, limits)
                    schema = schema_for(table, columns, bronze=True)
                    bronze_tables[table] = {
                        **_write_table(
                            bronze_work / f"{table}.parquet",
                            schema,
                            batches(stream, columns, table, batch_size, limits),
                        ),
                        "source_present": True,
                        "source_columns": columns,
                    }
        source.verify_bytes()
        frequencies = bronze_tables["frequencies"]
        capabilities = {
            "frequencies": {
                "present": frequencies["source_present"],
                "row_count": frequencies["row_count"],
                "handling": "textual_bronze_only",
            },
            "quantitative_gold_supported": frequencies["row_count"] == 0,
            "flexible_service_supported": False,
            "unprocessed_files": [
                item["name"] for item in inventory if item["handling"] == "raw_only"
            ],
            "calendar_sources": {
                table: bronze_tables[table]["source_present"] for table in OPTIONAL_TABLES
            },
            "untyped_extra_columns": {
                table: [
                    column
                    for column in bronze_tables[table]["source_columns"]
                    if column not in SPECS[table]
                ]
                for table in TABLES
            },
            "route_type_descriptions": "base_codes_only; other codes retained",
        }
        bronze_manifest = _publish(
            bronze_work,
            bronze_destination,
            {
                **bronze_base,
                "status": "passed",
                "completed_at": utc_now(),
                "duration_seconds": round(perf_counter() - started, 6),
                "inventory": inventory,
                "capabilities": capabilities,
                "quality_scope": "Complete UTF-8 CSV parsing, widths, namespace and byte limits",
            },
        )
    except (OSError, ValueError, PrepareError) as exc:
        failed_path = _failure(bronze_work, bronze_destination, bronze_base, exc)
        raise PrepareError(
            f"Bronze failed: {exc}. Pliki robocze: {bronze_work}",
            manifests=(failed_path,) if failed_path else (),
        ) from exc
    diagnostics = Diagnostics()
    silver_tables: dict = {}
    silver_base = {
        **base,
        "stage": "silver",
        "input": {
            **base["input"],
            "bronze_manifest": str(bronze_manifest),
            "bronze_manifest_sha256": file_sha256(bronze_manifest),
        },
        "tables": silver_tables,
        "capabilities": capabilities,
        "inventory": inventory,
    }
    try:
        silver_work, silver_destination = _stage_paths(root, "silver", run_id)
    except OSError as exc:
        raise PrepareError(
            f"Nie można utworzyć katalogu silver: {exc}", manifests=(bronze_manifest,)
        ) from exc
    quality_index = None
    try:
        quality_index = QualityIndex(silver_work / "quality-index.sqlite", diagnostics)
        agency_keys: tuple[str, ...] = ()
        for table in TABLES:
            entry = bronze_tables[table]
            columns = entry["source_columns"]
            schema = schema_for(table, columns)

            def typed_frames(table=table, entry=entry, keys=agency_keys):
                if not entry["source_present"]:
                    return
                path = bronze_manifest.parent / entry["path"]
                if file_sha256(path) != entry["sha256"]:
                    raise PrepareError(f"Hash bronze nie odpowiada manifestowi: {table}")
                for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_size):
                    frame = convert(table, batch.to_pandas(), diagnostics, keys)
                    quality_index.add(table, frame)
                    yield frame

            silver_tables[table] = {
                **_write_table(silver_work / f"{table}.parquet", schema, typed_frames()),
                "source_present": entry["source_present"],
                "normalized_empty": not entry["source_present"],
                "source_columns": columns,
                "added_columns": [name for name in schema.names if name not in columns],
            }
            if table == "agency":
                agency_keys = quality_index.agency_keys()
        metrics = quality_index.check()
        quality_index.close()
        quality_index = None
        quality = {
            "report_version": 1,
            "dataset_id": identity,
            "processing_run_id": run_id,
            **diagnostics.report(),
            **metrics,
            "capabilities": capabilities,
            "row_counts": {table: item["row_count"] for table, item in silver_tables.items()},
        }
        if not capabilities["quantitative_gold_supported"]:
            diagnostics.add(
                "unsupported_frequencies",
                "frequencies",
                None,
                capabilities["frequencies"]["row_count"],
                severity="warning",
            )
            quality.update(diagnostics.report())
        quality_path = silver_work / "quality.json"
        write_json(quality_path, quality)
        status = "failed" if diagnostics.error_count else "passed"
        silver_manifest = _publish(
            silver_work,
            silver_destination,
            {
                **silver_base,
                "status": status,
                "completed_at": utc_now(),
                "duration_seconds": round(perf_counter() - started, 6),
                "data_quality": {
                    "status": quality["status"],
                    "path": "quality.json",
                    "sha256": file_sha256(quality_path),
                    "error_count": quality["error_count"],
                    "warning_count": quality["warning_count"],
                    "checks": quality["checks"],
                    "examples": quality["examples"],
                    **metrics,
                },
            },
        )
    except (OSError, ValueError, TypeError, pa.ArrowException, sqlite3.Error, PrepareError) as exc:
        if quality_index is not None:
            quality_index.close()
        failed_path = _failure(
            silver_work,
            silver_destination,
            {**silver_base, "data_quality": diagnostics.report()},
            exc,
        )
        raise PrepareError(
            f"Silver failed: {exc}. Pliki robocze: {silver_work}",
            manifests=(bronze_manifest, failed_path) if failed_path else (bronze_manifest,),
        ) from exc
    if status != "passed":
        raise PrepareError(
            f"Silver failed: {diagnostics.error_count} błędów jakości. Raport: "
            f"{silver_manifest.parent / 'quality.json'}",
            manifests=(bronze_manifest, silver_manifest),
        )
    return PrepareResult(
        identity,
        run_id,
        bronze_manifest,
        silver_manifest,
        silver_manifest.parent / "quality.json",
        source.provenance["data_kind"],
    )
