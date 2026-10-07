"""Bounded logical CSV records, followed by explicitly textual Pandas batches."""

import csv
from collections.abc import Iterator
from typing import BinaryIO

import pandas as pd

from ..gtfs.config import Limits
from .source import SOURCE_RECORD, PrepareError

DERIVED_NAMES = {"_agency_key", "arrival_seconds", "departure_seconds", "route_type_description"}


def read_record(stream: BinaryIO, byte_limit: int, *, first: bool = False) -> list[str] | None:
    used = 0

    def lines() -> Iterator[str]:
        nonlocal used
        initial = True
        while True:
            line = stream.readline(byte_limit - used + 1)
            used += len(line)
            if used > byte_limit:
                raise PrepareError(f"Rekord CSV przekracza limit {byte_limit} bajtów.")
            if not line:
                return
            yield line.decode("utf-8-sig" if first and initial else "utf-8")
            initial = False

    return next(csv.reader(lines(), strict=True), None)


def read_header(stream: BinaryIO, table: str, limits: Limits) -> list[str]:
    try:
        columns = read_record(stream, limits.max_header_bytes, first=True)
        if (
            not columns
            or any(not name.strip() for name in columns)
            or len(set(columns)) != len(columns)
        ):
            raise PrepareError("Pusty lub zduplikowany nagłówek.")
        if any(name.startswith("_wta_") or name in DERIVED_NAMES for name in columns):
            raise PrepareError("Kolizja nazwy kolumny ze zastrzeżonymi metadanymi.")
        return columns
    except (csv.Error, UnicodeError, PrepareError) as exc:
        raise PrepareError(f"{table}, nagłówek: {exc}") from exc


def batches(
    stream: BinaryIO, columns: list[str], table: str, batch_size: int, limits: Limits
) -> Iterator[pd.DataFrame]:
    rows: list[list[str]] = []
    records: list[int] = []
    record = 0
    while True:
        record += 1
        try:
            row = read_record(stream, limits.max_record_bytes)
            if row is None:
                break
            # Empty logical records are skipped before width checking, with numbers retained.
            if not any(field.strip() for field in row):
                continue
            if len(row) != len(columns):
                raise PrepareError(f"Oczekiwano {len(columns)} pól, otrzymano {len(row)}.")
        except (csv.Error, UnicodeError, PrepareError) as exc:
            raise PrepareError(f"{table}, rekord {record}: {exc}") from exc
        rows.append(row)
        records.append(record)
        if len(rows) == batch_size:
            frame = pd.DataFrame(rows, columns=columns, dtype=object)
            frame[SOURCE_RECORD] = records
            yield frame
            rows, records = [], []
    if rows:
        frame = pd.DataFrame(rows, columns=columns, dtype=object)
        frame[SOURCE_RECORD] = records
        yield frame
