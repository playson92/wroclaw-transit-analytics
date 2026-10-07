"""Validate portable silver bytes and contract using bounded Parquet batches."""

import hashlib
import json
import re
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..preparation.contract import (
    OPTIONAL_TABLES,
    TABLES,
    content_digest,
    schema_for,
    update_digest,
)
from ..preparation.source import MODEL_VERSION, dataset_id
from .connection import DatabaseError


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _reject_constant(value):
    raise ValueError("Nonfinite JSON value")


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate JSON key")
        result[name] = value
    return result


def _json(stream: BinaryIO) -> dict:
    stream.seek(0)
    document = json.load(stream, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    if not isinstance(document, dict):
        raise DatabaseError("Dokument silver musi być obiektem JSON.")
    return document


def _no_links(path: Path) -> Path:
    absolute = path.absolute()
    for component in (*reversed(absolute.parents), absolute):
        if component.is_symlink() or component.is_junction():
            raise DatabaseError("Ścieżki silver nie mogą zawierać dowiązań ani junction.")
    resolved = absolute.resolve(strict=True)
    if not resolved.is_file():
        raise DatabaseError("Wejście silver musi być zwykłym plikiem.")
    return resolved


def safe_path(root: Path, relative: object) -> Path:
    if (
        not isinstance(relative, str)
        or not relative
        or any(char in relative for char in ("\\", ":", "\0"))
        or PurePosixPath(relative).is_absolute()
        or PureWindowsPath(relative).drive
        or any(part in ("", ".", "..") for part in relative.split("/"))
    ):
        raise DatabaseError("Niebezpieczna ścieżka względna silver.")
    path = _no_links(root / relative)
    if not path.is_relative_to(root):
        raise DatabaseError("Plik silver musi należeć do katalogu manifestu.")
    return path


def stream_sha256(stream: BinaryIO) -> str:
    stream.seek(0)
    digest = hashlib.sha256()
    while block := stream.read(1024 * 1024):
        digest.update(block)
    stream.seek(0)
    return digest.hexdigest()


def _hash(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _integer(value: object) -> bool:
    return type(value) is int and value >= 0


def _manifest_contract(manifest: dict) -> None:
    if (
        type(manifest.get("manifest_version")) is not int
        or manifest["manifest_version"] != 1
        or manifest.get("model_version") != MODEL_VERSION
        or manifest.get("stage") != "silver"
        or manifest.get("status") != "passed"
        or not _hash(manifest.get("source_sha256"))
        or manifest.get("dataset_id") != dataset_id(manifest["source_sha256"])
    ):
        raise DatabaseError("Wymagany kompletny manifest silver v1 z poprawną tożsamością.")
    if (
        not isinstance(manifest.get("processing_run_id"), str)
        or not manifest["processing_run_id"]
        or not isinstance(manifest.get("input"), dict)
        or not isinstance(manifest.get("source"), dict)
        or manifest.get("data_kind") not in ("real_gtfs", "synthetic_demo")
        or manifest["source"].get("data_kind") != manifest["data_kind"]
        or manifest["source"].get("source_kind")
        != {"real_gtfs": "official_https", "synthetic_demo": "local_synthetic"}[
            manifest["data_kind"]
        ]
        or not isinstance(manifest.get("capabilities"), dict)
        or not isinstance(manifest.get("inventory"), list)
        or not isinstance(manifest.get("tables"), dict)
        or set(manifest["tables"]) != set(TABLES)
    ):
        raise DatabaseError("Niekompletne metadane lub tabele manifestu silver.")


def _quality_contract(manifest: dict, quality: dict) -> None:
    dq = manifest["data_quality"]
    if (
        type(quality.get("report_version")) is not int
        or quality["report_version"] != 1
        or quality.get("status") != "passed"
        or type(quality.get("error_count")) is not int
        or quality["error_count"] != 0
        or quality.get("dataset_id") != manifest["dataset_id"]
        or quality.get("processing_run_id") != manifest["processing_run_id"]
        or quality.get("capabilities") != manifest["capabilities"]
        or quality.get("row_counts")
        != {name: entry["row_count"] for name, entry in manifest["tables"].items()}
        or not _integer(quality.get("warning_count"))
        or not isinstance(quality.get("checks"), list)
        or not isinstance(quality.get("examples"), list)
    ):
        raise DatabaseError("Raport quality.json nie odpowiada kompletnej zawartości silver.")
    for check in quality["checks"]:
        if (
            not isinstance(check, dict)
            or check.get("severity") != "warning"
            or not _integer(check.get("count"))
        ):
            raise DatabaseError("quality.json zawiera błędy lub niepoprawne checks.")
    if sum(check["count"] for check in quality["checks"]) != quality["warning_count"]:
        raise DatabaseError("Niespójna liczba ostrzeżeń quality.json.")
    for field, value in dq.items():
        if field not in ("path", "sha256") and quality.get(field) != value:
            raise DatabaseError("Podsumowanie data_quality nie odpowiada quality.json.")
    if dq.get("status") != "passed" or dq.get("error_count") != 0:
        raise DatabaseError("Wymagana jakość passed bez błędów.")


def logical_fingerprint(manifest: dict, quality: dict) -> str:
    # No file hashes, paths, timestamps, processing_run_id, batch sizes or durations.
    identity = {
        "fingerprint_version": 1,
        "dataset_id": manifest["dataset_id"],
        "source_sha256": manifest["source_sha256"],
        "model_version": manifest["model_version"],
        "data_kind": manifest["data_kind"],
        "source_kind": manifest["source"]["source_kind"],
        "capabilities": manifest["capabilities"],
        "tables": {
            name: {
                key: entry[key]
                for key in (
                    "content_sha256",
                    "columns",
                    "row_count",
                    "source_columns",
                    "added_columns",
                    "source_present",
                    "normalized_empty",
                )
            }
            for name, entry in manifest["tables"].items()
        },
        "quality": {key: value for key, value in quality.items() if key != "processing_run_id"},
    }
    return hashlib.sha256(canonical(identity)).hexdigest()


@dataclass(frozen=True)
class VerifiedSilver:
    manifest: dict
    quality: dict
    fingerprint: str
    streams: dict[str, BinaryIO]
    artifacts: tuple[tuple[BinaryIO, str], ...]

    def assert_unchanged(self) -> None:
        for stream, expected in self.artifacts:
            if stream_sha256(stream) != expected:
                raise DatabaseError("Pliki silver zmieniły się podczas weryfikacji lub load.")


@contextmanager
def verified_silver(path: Path, *, batch_size: int = 50_000):
    if type(batch_size) is not int or not 0 < batch_size <= 1_000_000:
        raise DatabaseError("batch_size musi być z zakresu 1..1000000.")
    try:
        with ExitStack() as stack:
            manifest_path = _no_links(path)
            manifest_stream = stack.enter_context(manifest_path.open("rb"))
            manifest_hash = stream_sha256(manifest_stream)
            manifest = _json(manifest_stream)
            _manifest_contract(manifest)
            streams = {}
            artifacts = [(manifest_stream, manifest_hash)]
            used_paths = {manifest_path}
            for name in TABLES:
                entry = manifest["tables"][name]
                if (
                    not isinstance(entry, dict)
                    or not _integer(entry.get("row_count"))
                    or not _integer(entry.get("size_bytes"))
                    or not _hash(entry.get("sha256"))
                    or not _hash(entry.get("content_sha256"))
                    or type(entry.get("source_present")) is not bool
                    or type(entry.get("normalized_empty")) is not bool
                    or entry["normalized_empty"] == entry["source_present"]
                    or (
                        not entry["source_present"]
                        and (name not in OPTIONAL_TABLES or entry["row_count"])
                    )
                    or not isinstance(entry.get("source_columns"), list)
                    or any(not isinstance(col, str) or not col for col in entry["source_columns"])
                    or len(set(entry["source_columns"])) != len(entry["source_columns"])
                    or any(
                        col.startswith("_wta_")
                        or col
                        in (
                            "_agency_key",
                            "arrival_seconds",
                            "departure_seconds",
                            "route_type_description",
                        )
                        for col in entry["source_columns"]
                    )
                ):
                    raise DatabaseError(f"Niepoprawny kontrakt tabeli {name}.")
                expected = schema_for(name, entry["source_columns"])
                columns = [
                    {"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in expected
                ]
                if entry.get("columns") != columns or entry.get("added_columns") != [
                    col for col in expected.names if col not in entry["source_columns"]
                ]:
                    raise DatabaseError(f"Niepoprawny deklarowany schemat tabeli {name}.")
                file_path = safe_path(manifest_path.parent, entry.get("path"))
                if file_path in used_paths:
                    raise DatabaseError("Powtórzona ścieżka pliku silver.")
                used_paths.add(file_path)
                stream = stack.enter_context(file_path.open("rb"))
                stream.seek(0, 2)
                if stream.tell() != entry["size_bytes"] or stream_sha256(stream) != entry["sha256"]:
                    raise DatabaseError(
                        f"Rozmiar/SHA-256 Parquet nie odpowiada manifestowi: {name}."
                    )
                parquet = pq.ParquetFile(stream)
                if not parquet.schema_arrow.equals(expected, check_metadata=False):
                    raise DatabaseError(
                        f"Rzeczywisty schemat Parquet nie odpowiada kontraktowi: {name}."
                    )
                digest = content_digest(expected)
                count = 0
                for batch in parquet.iter_batches(batch_size=batch_size):
                    update_digest(digest, batch.to_pandas(types_mapper=pd.ArrowDtype))
                    count += batch.num_rows
                if count != entry["row_count"] or digest.hexdigest() != entry["content_sha256"]:
                    raise DatabaseError(f"row_count/content_sha256 nie odpowiada Parquet: {name}.")
                streams[name] = stream
                artifacts.append((stream, entry["sha256"]))
            dq = manifest.get("data_quality")
            if not isinstance(dq, dict) or not _hash(dq.get("sha256")):
                raise DatabaseError("Brak poprawnego data_quality.")
            quality_path = safe_path(manifest_path.parent, dq.get("path"))
            if quality_path in used_paths:
                raise DatabaseError("Powtórzona ścieżka quality.json.")
            quality_stream = stack.enter_context(quality_path.open("rb"))
            if stream_sha256(quality_stream) != dq["sha256"]:
                raise DatabaseError("SHA-256 quality.json nie odpowiada manifestowi.")
            quality = _json(quality_stream)
            _quality_contract(manifest, quality)
            artifacts.append((quality_stream, dq["sha256"]))
            verified = VerifiedSilver(
                manifest, quality, logical_fingerprint(manifest, quality), streams, tuple(artifacts)
            )
            verified.assert_unchanged()
            yield verified
    except DatabaseError:
        raise
    except (OSError, ValueError, TypeError, KeyError, pa.ArrowException):
        raise DatabaseError(
            "Nie można odczytać kompletnego silver; sprawdź pliki i kontrakt."
        ) from None
