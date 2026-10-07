"""Compose snapshot download, validation and the completion manifest."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from .config import CATALOG_URL, DEFAULT_LIMITS, Limits, validate_url
from .downloader import download
from .exceptions import StorageError
from .models import IngestionResult
from .validation import validate_archive


def _write_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_suffix(".json.part")
    owns_temporary = False
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as output:
            owns_temporary = True
            json.dump(manifest, output, ensure_ascii=False, indent=2)
            output.write("\n")
        temporary.rename(path)
        owns_temporary = False
    except OSError as exc:
        raise StorageError(f"Nie można zapisać manifestu {path}: {exc}") from exc
    finally:
        if owns_temporary:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                raise StorageError(f"Nie można usunąć częściowego manifestu: {exc}") from exc


def ingest(
    url: str,
    output_dir: Path = Path("data/raw/gtfs"),
    *,
    limits: Limits = DEFAULT_LIMITS,
    client: httpx.Client | None = None,
) -> IngestionResult:
    """A manifest marks completion; ZIP and manifest are separate rename operations."""
    validate_url(url)
    now = datetime.now(UTC)
    run_id = f"{now:%Y%m%dT%H%M%S%fZ}_{uuid4().hex}"
    run_dir = output_dir / f"{now:%Y-%m-%d}" / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise StorageError(f"Nie można utworzyć katalogu runu: {exc}") from exc
    archive_path = run_dir / "feed.zip"
    downloaded = download(url, archive_path, limits, client=client)
    validation = validate_archive(archive_path, limits)
    manifest_path = run_dir / "manifest.json"
    manifest = {
        "manifest_version": 1,
        "run_id": run_id,
        "catalog_url": CATALOG_URL,
        "archive_path": "feed.zip",  # Relative to the manifest's directory.
        **asdict(downloaded),
        "validation": {**asdict(validation), "status": validation.status},
    }
    _write_manifest(manifest_path, manifest)
    return IngestionResult(archive_path, manifest_path, downloaded, validation)
