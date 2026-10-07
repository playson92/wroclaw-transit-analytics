"""Small immutable results shared across ingestion stages."""

from dataclasses import dataclass
from pathlib import Path

from .config import PROFILE


@dataclass(frozen=True)
class DownloadResult:
    requested_url: str
    final_url: str
    size_bytes: int
    sha256: str
    downloaded_at: str
    content_type: str | None
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class Issue:
    code: str
    file: str | None
    description: str


@dataclass(frozen=True)
class ValidationResult:
    issues: tuple[Issue, ...]
    profile: str = PROFILE
    scope: str = "ZIP integrity, safe members, MVP headers and nonempty tables"

    @property
    def status(self) -> str:
        return "failed" if self.issues else "passed"


@dataclass(frozen=True)
class IngestionResult:
    archive_path: Path
    manifest_path: Path
    download: DownloadResult
    validation: ValidationResult
