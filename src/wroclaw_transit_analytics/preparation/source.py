"""Verify the existing raw v1 contract without modifying its files."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..gtfs.config import CATALOG_URL, DEFAULT_LIMITS, PROFILE, Limits, validate_url
from ..gtfs.exceptions import GTFSError
from ..gtfs.validation import validate_archive

MODEL_VERSION = "wta-silver-v1"
SOURCE_RECORD = "_wta_source_record"


class PrepareError(Exception):
    """A rejected source or failed stage, optionally with diagnostic manifests."""

    def __init__(self, message: str, *, manifests: tuple[Path, ...] = ()) -> None:
        super().__init__(message)
        self.manifests = manifests


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def dataset_id(source_sha256: str, model_version: str = MODEL_VERSION) -> str:
    """Identity includes source bytes and transformation semantics, never the run."""
    return (
        "gtfs_" + hashlib.sha256((model_version + "\0" + source_sha256).encode("utf-8")).hexdigest()
    )


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _invalid_json_constant(value: str):
    raise ValueError(f"Niedozwolona stała JSON: {value}.")


def _verify_timestamp(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise PrepareError(f"Brak poprawnego {field} raw.")
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(0):
        raise PrepareError(f"{field} raw musi być czasem UTC z jawną strefą.")


def write_json(path: Path, value: dict) -> None:
    """Create an owned temporary file; publish only a complete JSON document."""
    temporary = path.with_name(path.name + ".part")
    owns_temporary = False
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            owns_temporary = True
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        if path.exists():
            raise FileExistsError(f"Plik już istnieje: {path}")
        temporary.rename(path)
        owns_temporary = False
    finally:
        if owns_temporary:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class RawSource:
    manifest_path: Path
    archive_path: Path
    manifest_sha256: str
    manifest: dict
    sha256: str
    provenance: dict

    def verify_bytes(self) -> None:
        if (
            self.archive_path.stat().st_size != self.manifest["size_bytes"]
            or file_sha256(self.archive_path) != self.sha256
            or file_sha256(self.manifest_path) != self.manifest_sha256
        ):
            raise PrepareError("Pliki raw zmieniły się lub nie odpowiadają manifestowi.")


def _archive_path(manifest_path: Path, relative: object) -> Path:
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or ":" in relative
        or "\0" in relative
        or PurePosixPath(relative).is_absolute()
        or PureWindowsPath(relative).drive
        or any(part in ("", ".", "..") for part in relative.split("/"))
    ):
        raise PrepareError("archive_path musi być bezpieczną ścieżką względną katalogu raw.")
    root = manifest_path.parent
    candidate = root
    for component in relative.split("/"):
        candidate /= component
        if candidate.is_symlink():
            raise PrepareError("archive_path nie może prowadzić przez dowiązanie symboliczne.")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise PrepareError("Archiwum musi być plikiem wewnątrz katalogu manifestu raw.")
    return resolved


def read_source(path: Path, limits: Limits = DEFAULT_LIMITS) -> RawSource:
    """Verify bytes, provenance and the trusted local archive validator."""
    try:
        manifest_path = path.resolve(strict=True)
        with manifest_path.open(encoding="utf-8-sig") as stream:
            manifest = json.load(stream, parse_constant=_invalid_json_constant)
        if not isinstance(manifest, dict) or type(manifest.get("manifest_version")) is not int:
            raise PrepareError("Niepoprawny manifest raw.")
        if manifest["manifest_version"] != 1:
            raise PrepareError("Obsługiwany jest wyłącznie manifest_version=1.")
        validation = manifest.get("validation")
        if (
            not isinstance(validation, dict)
            or validation.get("status") != "passed"
            or validation.get("profile") != PROFILE
            or validation.get("issues") != []
        ):
            raise PrepareError("Wejście wymaga kompletnej walidacji raw passed, bez issues.")
        if not isinstance(manifest.get("run_id"), str) or not manifest["run_id"].strip():
            raise PrepareError("Brak run_id raw.")
        sha256 = manifest.get("sha256")
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise PrepareError("Niepoprawny SHA-256 raw.")
        size = manifest.get("size_bytes")
        if type(size) is not int or not 0 < size <= limits.max_download_bytes:
            raise PrepareError("Niepoprawny lub zbyt duży size_bytes raw.")
        kind = manifest.get("source_kind", "official_https")
        if kind == "official_https":
            validate_url(manifest.get("requested_url", ""))
            validate_url(manifest.get("final_url", ""))
            if manifest.get("catalog_url") != CATALOG_URL:
                raise PrepareError("Niepoprawny oficjalny catalog_url raw.")
            _verify_timestamp(manifest.get("downloaded_at"), "downloaded_at")
            if manifest.get("data_kind", "real_gtfs") != "real_gtfs":
                raise PrepareError("Sprzeczny data_kind oficjalnego źródła.")
            data_kind = "real_gtfs"
        elif kind == "local_synthetic":
            if manifest.get("data_kind") != "synthetic_demo" or any(
                manifest.get(field) is not None
                for field in ("requested_url", "final_url", "catalog_url", "downloaded_at")
            ):
                raise PrepareError("Demo musi być syntetyczne i nie może udawać pobrania HTTP.")
            data_kind = "synthetic_demo"
            _verify_timestamp(manifest.get("generated_at"), "generated_at")
        else:
            raise PrepareError(f"Nieobsługiwany source_kind: {kind!r}.")
        archive_path = _archive_path(manifest_path, manifest.get("archive_path"))
        provenance = {
            "source_kind": kind,
            "data_kind": data_kind,
            **{
                field: manifest.get(field)
                for field in (
                    "requested_url",
                    "final_url",
                    "catalog_url",
                    "downloaded_at",
                    "generated_at",
                )
            },
        }
        source = RawSource(
            manifest_path,
            archive_path,
            file_sha256(manifest_path),
            manifest,
            sha256,
            provenance,
        )
        source.verify_bytes()
        result = validate_archive(archive_path, limits)
        if result.status != "passed":
            details = "; ".join(f"{item.code}: {item.description}" for item in result.issues[:10])
            raise PrepareError(f"Ponowna walidacja ZIP failed: {details}")
        source.verify_bytes()
        return source
    except PrepareError:
        raise
    except (OSError, ValueError, TypeError, GTFSError) as exc:
        raise PrepareError(f"Nie można przyjąć manifestu raw: {exc}") from exc
