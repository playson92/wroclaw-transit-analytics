"""Explicit nullable silver types and bounded, source-record-based diagnostics."""

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import pyarrow as pa

from .source import SOURCE_RECORD

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
TABLES = ("agency", "stops", "routes", "trips", "stop_times", "calendar", "calendar_dates")
OPTIONAL_TABLES = {"calendar", "calendar_dates"}
MAX_INTEGER = 2**63 - 1
SINGLE_AGENCY_KEY = "__single_agency__"


@dataclass(frozen=True)
class Field:
    kind: str = "string"
    required: bool = False
    default: str | None = None
    choices: tuple[int, ...] | None = None


SPECS = {
    "agency": {
        "agency_id": Field("id"),
        "agency_name": Field(required=True),
        "agency_url": Field(required=True),
        "agency_timezone": Field(required=True),
    },
    "stops": {
        "stop_id": Field("id", required=True),
        "stop_name": Field(default=""),
        "stop_lat": Field("float"),
        "stop_lon": Field("float"),
        "location_type": Field("integer", default="0", choices=(0, 1, 2, 3, 4)),
        "parent_station": Field("id"),
    },
    "routes": {
        "route_id": Field("id", required=True),
        "agency_id": Field("id"),
        "route_short_name": Field(default=""),
        "route_long_name": Field(default=""),
        "route_type": Field("integer", required=True),
    },
    "trips": {
        "trip_id": Field("id", required=True),
        "route_id": Field("id", required=True),
        "service_id": Field("id", required=True),
        "direction_id": Field("integer", choices=(0, 1)),
        "trip_headsign": Field(default=""),
    },
    "stop_times": {
        "trip_id": Field("id", required=True),
        "stop_id": Field("id", required=True),
        "stop_sequence": Field("integer", required=True),
        "arrival_time": Field(default=""),
        "departure_time": Field(default=""),
        "pickup_type": Field("integer", default="0", choices=(0, 1, 2, 3)),
        "drop_off_type": Field("integer", default="0", choices=(0, 1, 2, 3)),
        "timepoint": Field("integer", default="1", choices=(0, 1)),
    },
    "calendar": {
        "service_id": Field("id", required=True),
        **{day: Field("integer", required=True, choices=(0, 1)) for day in DAYS},
        "start_date": Field("date", required=True),
        "end_date": Field("date", required=True),
    },
    "calendar_dates": {
        "service_id": Field("id", required=True),
        "date": Field("date", required=True),
        "exception_type": Field("integer", required=True, choices=(1, 2)),
    },
}
GENERATED = {
    "agency": {"_agency_key": pa.string()},
    "routes": {"_agency_key": pa.string(), "route_type_description": pa.string()},
    "stop_times": {"arrival_seconds": pa.int64(), "departure_seconds": pa.int64()},
}
ARROW_TYPES = {
    "id": pa.string(),
    "string": pa.string(),
    "integer": pa.int64(),
    "float": pa.float64(),
    "date": pa.date32(),
}
ROUTE_TYPES = {
    0: "tram",
    1: "subway",
    2: "rail",
    3: "bus",
    4: "ferry",
    5: "cable_tram",
    6: "aerial_lift",
    7: "funicular",
    11: "trolleybus",
    12: "monorail",
}


class Diagnostics:
    """Exact counts, with at most 50 examples total and 5 per check."""

    def __init__(self) -> None:
        self.counts: Counter = Counter()
        self.examples: list[dict] = []
        self.example_counts: Counter = Counter()

    def add(
        self,
        code: str,
        table: str,
        column: str | None,
        count: int,
        examples=(),
        *,
        severity: str = "error",
    ) -> None:
        if not count:
            return
        key = (severity, code, table, column)
        self.counts[key] += int(count)
        for example in examples:
            if len(self.examples) >= 50 or self.example_counts[key] >= 5:
                break
            self.examples.append(
                {"severity": severity, "code": code, "table": table, "column": column, **example}
            )
            self.example_counts[key] += 1

    def field(self, code: str, table: str, column: str, frame: pd.DataFrame, mask) -> None:
        mask = mask.fillna(False)
        count = int(mask.sum())
        if count:
            examples = (
                {"record": int(record), "value": str(value)[:100]}
                for record, value in frame.loc[mask, [SOURCE_RECORD, column]]
                .head(5)
                .itertuples(index=False, name=None)
            )
            self.add(code, table, column, count, examples)

    @property
    def error_count(self) -> int:
        return sum(count for key, count in self.counts.items() if key[0] == "error")

    def report(self) -> dict:
        return {
            "status": "failed" if self.error_count else "passed",
            "error_count": self.error_count,
            "warning_count": sum(
                count for key, count in self.counts.items() if key[0] == "warning"
            ),
            "checks": [
                {
                    "severity": severity,
                    "code": code,
                    "table": table,
                    "column": column,
                    "count": count,
                }
                for (severity, code, table, column), count in self.counts.items()
            ],
            "examples": self.examples,
            "example_limit": 50,
            "scope": "wta-silver-v1 static-table types, keys, relations and known service times",
            "full_gtfs_conformance": False,
        }


def schema_for(table: str, source_columns: list[str], *, bronze: bool = False) -> pa.Schema:
    fields = {column: pa.string() for column in source_columns}
    fields[SOURCE_RECORD] = pa.int64()
    if not bronze:
        for name, specification in SPECS[table].items():
            fields[name] = ARROW_TYPES[specification.kind]
        fields.update(GENERATED.get(table, {}))
    return pa.schema(
        [pa.field(name, kind, nullable=name != SOURCE_RECORD) for name, kind in fields.items()]
    )


def _identifier(text: pd.Series) -> pd.Series:
    return text.mask(text.eq(""), pd.NA)


def _integer(text: pd.Series, specification: Field) -> tuple[pd.Series, pd.Series]:
    normalized = text
    if specification.default is not None:
        normalized = normalized.mask(normalized.eq(""), specification.default)
    stripped_zeros = normalized.str.lstrip("0").mask(normalized.str.fullmatch("0+"), "0")
    valid = normalized.str.fullmatch("[0-9]+").fillna(False) & (
        stripped_zeros.str.len().lt(19)
        | (stripped_zeros.str.len().eq(19) & stripped_zeros.le(str(MAX_INTEGER)))
    )
    result = stripped_zeros.where(valid, pd.NA).astype("Int64")
    invalid = normalized.ne("") & ~valid
    if specification.required:
        invalid |= normalized.eq("")
    if specification.choices is not None:
        invalid |= result.notna() & ~result.isin(specification.choices)
    return result, invalid


def _date(value: str) -> date | None:
    if not re.fullmatch("[0-9]{8}", value):
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _float(value: str) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except ValueError:
        return None


def _parse_seconds(value: str) -> int | None:
    match = re.fullmatch(r"([0-9]+):([0-5][0-9]):([0-5][0-9])", value)
    if not match:
        return None
    hour_text, minute_text, second_text = match.groups()
    hour_text = hour_text.lstrip("0") or "0"
    if len(hour_text) > 16:
        return None
    hour, minute, second = int(hour_text), int(minute_text), int(second_text)
    result = hour * 3600 + minute * 60 + second
    return result if result <= MAX_INTEGER else None


@lru_cache(maxsize=100_000)
def _cached_seconds(value: str) -> int | None:
    return _parse_seconds(value)


def seconds(value: str) -> int | None:
    # Do not retain arbitrarily long strings in the bounded lookup cache.
    return _cached_seconds(value) if len(value) <= 32 else _parse_seconds(value)


def convert(
    table: str,
    bronze: pd.DataFrame,
    diagnostics: Diagnostics,
    agency_keys: tuple[str, ...] = (),
) -> pd.DataFrame:
    frame = bronze.copy()
    for column in frame.columns:
        if column != SOURCE_RECORD:
            frame[column] = frame[column].astype("string")
    for column, spec in SPECS[table].items():
        if column not in frame:
            frame[column] = pd.Series(spec.default or "", index=frame.index, dtype="string")
        text = frame[column]
        if spec.kind == "id":
            diagnostics.field("id_whitespace", table, column, frame, text.ne(text.str.strip()))
            if spec.required:
                diagnostics.field("required_id", table, column, frame, text.eq(""))
            frame[column] = _identifier(text)
        elif spec.kind == "integer":
            result, invalid = _integer(text, spec)
            diagnostics.field("invalid_integer_or_enum", table, column, frame, invalid)
            frame[column] = result
        elif spec.kind == "date":
            result = text.map(_date)
            diagnostics.field("invalid_date", table, column, frame, result.isna())
            frame[column] = result
        elif spec.kind == "float":
            result = pd.Series(pd.array([_float(value) for value in text], dtype="Float64"))
            result.index = frame.index
            bound = 90 if column == "stop_lat" else 180
            invalid = text.ne("") & (result.isna() | result.lt(-bound) | result.gt(bound))
            diagnostics.field("invalid_coordinate", table, column, frame, invalid)
            frame[column] = result
        elif spec.required:
            diagnostics.field("required_text", table, column, frame, text.str.strip().eq(""))
    # Extra ID fields are preserved as strings; absent values normalize to null.
    for column in frame.columns:
        if column.endswith("_id") and column not in SPECS[table]:
            diagnostics.field(
                "id_whitespace", table, column, frame, frame[column].ne(frame[column].str.strip())
            )
            frame[column] = _identifier(frame[column])
    if table == "agency":
        frame["_agency_key"] = frame["agency_id"].fillna(SINGLE_AGENCY_KEY)
        for timezone in frame["agency_timezone"].unique():
            try:
                ZoneInfo(timezone)
            except (ZoneInfoNotFoundError, ValueError):
                diagnostics.field(
                    "invalid_timezone",
                    table,
                    "agency_timezone",
                    frame,
                    frame["agency_timezone"].eq(timezone),
                )
    elif table == "routes":
        frame["_agency_key"] = frame["agency_id"].copy()
        if len(agency_keys) == 1:
            frame["_agency_key"] = frame["_agency_key"].fillna(agency_keys[0])
        else:
            diagnostics.field(
                "ambiguous_agency", table, "agency_id", frame, frame["_agency_key"].isna()
            )
        frame["route_type_description"] = frame["route_type"].map(ROUTE_TYPES).fillna("other")
        diagnostics.field(
            "missing_route_name",
            table,
            "route_short_name",
            frame,
            frame["route_short_name"].str.strip().eq("")
            & frame["route_long_name"].str.strip().eq(""),
        )
    elif table == "stops":
        required_location = frame["location_type"].isin((0, 1, 2))
        diagnostics.field(
            "required_stop_name",
            table,
            "stop_name",
            frame,
            required_location & frame["stop_name"].str.strip().eq(""),
        )
        for column in ("stop_lat", "stop_lon"):
            diagnostics.field(
                "required_coordinate",
                table,
                column,
                frame,
                required_location & frame[column].isna(),
            )
    elif table == "stop_times":
        for column in ("arrival_time", "departure_time"):
            result = pd.Series(
                pd.array([seconds(value) for value in frame[column]], dtype="Int64"),
                index=frame.index,
            )
            diagnostics.field(
                "invalid_gtfs_time", table, column, frame, frame[column].ne("") & result.isna()
            )
            frame[column.replace("_time", "_seconds")] = result
        for column in (
            "location_group_id",
            "location_id",
            "start_pickup_drop_off_window",
            "end_pickup_drop_off_window",
        ):
            if column in frame:
                diagnostics.field(
                    "unsupported_flexible_service",
                    table,
                    column,
                    frame,
                    frame[column].notna() & frame[column].ne(""),
                )
    return frame


def python_value(value):
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def content_digest(schema: pa.Schema):
    """Logical content hash is invariant to Parquet row groups and batch size."""
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            [(field.name, str(field.type)) for field in schema], separators=(",", ":")
        ).encode()
        + b"\n"
    )
    return digest


def update_digest(digest, frame: pd.DataFrame) -> None:
    for row in frame.itertuples(index=False, name=None):
        values = [python_value(value) for value in row]
        values = [value.isoformat() if isinstance(value, date) else value for value in values]
        digest.update(
            json.dumps(values, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
                "utf-8"
            )
            + b"\n"
        )
