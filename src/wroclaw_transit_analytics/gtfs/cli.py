"""Minimal terminal interface with explicit source configuration."""

import argparse
import sys
from pathlib import Path

from .config import resolve_url
from .exceptions import GTFSError, ValidationError
from .ingestion import ingest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pobierz oficjalny GTFS i zweryfikuj profil MVP.")
    parser.add_argument("--url", help="Jawny HTTPS URL archiwum; pierwszeństwo przed GTFS_URL.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/gtfs"),
        help="Katalog raw (domyślnie data/raw/gtfs), względny wobec katalogu uruchomienia.",
    )
    args = parser.parse_args(argv)
    try:
        result = ingest(resolve_url(args.url), args.output_dir)
        if result.validation.status == "failed":
            details = "\n".join(
                f"  {issue.code} [{issue.file or 'archiwum'}]: {issue.description}"
                for issue in result.validation.issues
            )
            raise ValidationError(
                f"Walidacja failed. ZIP: {result.archive_path}\n"
                f"Manifest: {result.manifest_path}\n{details}"
            )
    except GTFSError as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        return 1
    print(
        f"Walidacja passed\nZIP: {result.archive_path}\nManifest: {result.manifest_path}\n"
        f"Rozmiar: {result.download.size_bytes} bajtów\nSHA-256: {result.download.sha256}"
    )
    return 0
