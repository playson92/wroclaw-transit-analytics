"""Bounded local ZIP integrity and project-specific static MVP structure checks."""

import csv
import lzma
import stat
import zlib
from collections import Counter
from collections.abc import Iterator
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO
from zipfile import ZIP_BZIP2, BadZipFile, ZipFile

from .config import DEFAULT_LIMITS, Limits
from .exceptions import StorageError
from .models import Issue, ValidationResult

HEADERS = {
    "agency.txt": {"agency_name", "agency_url", "agency_timezone"},
    "stops.txt": {"stop_id", "stop_name", "stop_lat", "stop_lon"},
    "routes.txt": {"route_id", "route_type"},
    "trips.txt": {"route_id", "service_id", "trip_id"},
    "stop_times.txt": {"trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"},
    "calendar.txt": {
        "service_id",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "start_date",
        "end_date",
    },
    "calendar_dates.txt": {"service_id", "date", "exception_type"},
}
CORE = {"agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt"}
CALENDARS = {"calendar.txt", "calendar_dates.txt"}


class _ReadLimit(Exception):
    """Stop decompression immediately after a project limit is reached."""


class _RecordLimit(Exception):
    """A logical CSV header or data record exceeds its byte budget."""


def _unsafe_path(name: str) -> bool:
    windows = PureWindowsPath(name)
    normalized = name.replace("\\", "/")
    return (
        not name
        or "\x00" in name
        or "\\" in name
        or ":" in name
        or windows.is_absolute()
        or bool(windows.drive)
        or PurePosixPath(normalized).is_absolute()
        or any(part in ("..", ".", "") for part in normalized.rstrip("/").split("/"))
    )


def validate_archive(path: Path, limits: Limits = DEFAULT_LIMITS) -> ValidationResult:
    """Never extract or rewrite; stream every safe member to EOF to verify CRC."""
    issues: list[Issue] = []

    def issue(code: str, file: str | None, description: str) -> None:
        issues.append(Issue(code, file, description))

    try:
        if not path.exists() or path.stat().st_size == 0:
            return ValidationResult((Issue("empty_archive", None, "Brak pliku lub pusty plik."),))
        with ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > limits.max_entries:
                issue("entry_limit", None, "Przekroczono limit liczby wpisów ZIP.")
            if sum(member.file_size for member in members) > limits.max_uncompressed_bytes:
                issue("uncompressed_limit", None, "Przekroczono deklarowany rozmiar dekompresji.")
            counts = Counter(member.filename for member in members)
            for name, count in counts.items():
                if count > 1:
                    issue("duplicate_entry", name, "Zduplikowana nazwa wpisu ZIP.")
            for member in members:
                if _unsafe_path(member.orig_filename):
                    issue("unsafe_path", member.orig_filename, "Niebezpieczna ścieżka wpisu ZIP.")
                if member.flag_bits & 1:
                    issue("encrypted_entry", member.filename, "Szyfrowany wpis ZIP.")
                if stat.S_ISLNK(member.external_attr >> 16):
                    issue("symlink_entry", member.filename, "Dowiązanie symboliczne w ZIP.")
            # Reject unsafe metadata before opening any member.
            if issues:
                return ValidationResult(tuple(issues))
            names = {member.filename for member in members if not member.is_dir()}
            for name in sorted(CORE - names):
                issue("missing_file", name, f"Brak wymaganego pliku w katalogu głównym: {name}.")
            if not names & CALENDARS:
                issue("missing_calendar", None, "Brak calendar.txt i calendar_dates.txt.")

            total = 0
            calendar_has_data = False
            current_name: str | None = None

            def account(data: bytes) -> bytes:
                nonlocal total
                total += len(data)
                if total > limits.max_uncompressed_bytes:
                    raise _ReadLimit
                return data

            def record_lines(
                stream: BinaryIO, byte_limit: int, *, header: bool = False
            ) -> Iterator[str]:
                used = 0
                first = True
                while True:
                    budget = min(byte_limit - used, limits.max_uncompressed_bytes - total)
                    line = account(stream.readline(budget + 1))
                    used += len(line)
                    if used > byte_limit:
                        raise _RecordLimit
                    if not line:
                        return
                    yield line.decode("utf-8-sig" if header and first else "utf-8")
                    first = False

            try:
                for member in members:
                    current_name = member.filename
                    with archive.open(member) as stream:
                        has_data = False
                        if current_name in HEADERS:
                            try:
                                columns = next(
                                    csv.reader(
                                        record_lines(stream, limits.max_header_bytes, header=True),
                                        strict=True,
                                    ),
                                    [],
                                )
                            except _RecordLimit:
                                issue(
                                    "header_limit",
                                    current_name,
                                    "Nagłówek przekracza limit bajtów.",
                                )
                                columns = None
                            except (UnicodeDecodeError, csv.Error) as exc:
                                issue(
                                    "invalid_header",
                                    current_name,
                                    f"Błędny nagłówek CSV/UTF-8: {exc}",
                                )
                                columns = None
                            if columns is not None:
                                if any(not column.strip() for column in columns):
                                    issue("empty_column", current_name, "Pusta nazwa kolumny.")
                                if len(set(columns)) != len(columns):
                                    issue(
                                        "duplicate_column",
                                        current_name,
                                        "Zduplikowana nazwa kolumny.",
                                    )
                                missing = HEADERS[current_name] - set(columns)
                                if missing:
                                    issue(
                                        "missing_columns",
                                        current_name,
                                        f"Brak kolumn: {', '.join(sorted(missing))}.",
                                    )
                                if current_name == "routes.txt" and not {
                                    "route_short_name",
                                    "route_long_name",
                                } & set(columns):
                                    issue(
                                        "missing_route_name",
                                        current_name,
                                        "Brak route_short_name lub route_long_name.",
                                    )
                                while True:
                                    try:
                                        row = next(
                                            csv.reader(
                                                record_lines(stream, limits.max_record_bytes),
                                                strict=True,
                                            ),
                                            None,
                                        )
                                    except _RecordLimit:
                                        issue(
                                            "record_limit",
                                            current_name,
                                            "Rekord CSV przekracza limit bajtów.",
                                        )
                                        break
                                    except (UnicodeDecodeError, csv.Error) as exc:
                                        issue(
                                            "invalid_record",
                                            current_name,
                                            f"Błędny odczytywany rekord CSV/UTF-8: {exc}",
                                        )
                                        break
                                    if row is None:
                                        break
                                    if any(field.strip() for field in row):
                                        has_data = True
                                        break
                        # Still drain every member after finding data or a CSV issue.
                        while account(
                            stream.read(min(65536, limits.max_uncompressed_bytes - total + 1))
                        ):
                            pass
                        if current_name in CORE and not has_data:
                            issue("empty_table", current_name, "Tabela nie zawiera rekordu danych.")
                        if current_name in CALENDARS and has_data:
                            calendar_has_data = True
                if names & CALENDARS and not calendar_has_data:
                    issue(
                        "empty_calendar", None, "Żaden plik kalendarza nie zawiera rekordu danych."
                    )
            except _ReadLimit:
                issue(
                    "uncompressed_limit",
                    current_name,
                    "Przekroczono faktyczny rozmiar dekompresji.",
                )
            except (
                BadZipFile,
                RuntimeError,
                NotImplementedError,
                EOFError,
                zlib.error,
                lzma.LZMAError,
            ) as exc:
                issue("corrupt_member", current_name, f"Błąd integralności/dekompresji ZIP: {exc}")
            except OSError as exc:
                # CPython's BZIP2 decoder uses this errno-less OSError for corrupt data.
                # Other OS errors (including EIO and PermissionError) retain storage semantics.
                if (
                    member.compress_type == ZIP_BZIP2
                    and type(exc) is OSError
                    and exc.errno is None
                    and exc.args == ("Invalid data stream",)
                ):
                    issue("corrupt_member", current_name, f"Błąd dekompresji BZIP2: {exc}")
                else:
                    raise
    except (BadZipFile, EOFError, UnicodeError) as exc:
        issue("invalid_zip", None, f"Nie można otworzyć ZIP: {exc}")
    except OSError as exc:
        raise StorageError(f"Nie można odczytać archiwum: {exc}") from exc
    return ValidationResult(tuple(issues))
